import os
import csv
import io
import math
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, asc, desc

from app.database import get_db
from app.models import Profile, User
from app.schemas import ProfileCreate, ProfileData, ProfileListItem
from app.services.enrichment import fetch_enrichment_data
from app.services.nlp_parser import parse_natural_language_query
from app.dependencies import require_admin, require_any_role
from app.auth import generate_uuid7

router = APIRouter()

VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDERS = {"asc", "desc"}


# ─── Pagination Helper ─────────────────────────────────────────────────────────

def build_pagination_response(profiles, total, page, limit, base_url, query_params: dict):
    total_pages = math.ceil(total / limit) if total > 0 else 1

    def build_url(p: int) -> str:
        params = {**query_params, "page": p, "limit": limit}
        query_str = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        return f"{base_url}?{query_str}"

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": {
            "self": build_url(page),
            "next": build_url(page + 1) if page < total_pages else None,
            "prev": build_url(page - 1) if page > 1 else None,
        },
        "data": [
            ProfileListItem.model_validate(p).model_dump(mode="json")
            for p in profiles
        ]
    }


# ─── POST /api/profiles (Admin only) ──────────────────────────────────────────

@router.post("/profiles")
async def create_profile(
    body: ProfileCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Name is required"}
        )

    name = body.name.strip().lower()

    result = await db.execute(select(Profile).where(Profile.name == name))
    existing = result.scalar_one_or_none()

    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileData.model_validate(existing).model_dump(mode="json")
            }
        )

    enriched = await fetch_enrichment_data(name)
    profile = Profile(
        id=generate_uuid7(),
        name=name,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        **enriched
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return JSONResponse(
        status_code=201,
        content={
            "status": "success",
            "data": ProfileData.model_validate(profile).model_dump(mode="json")
        }
    )


# ─── GET /api/profiles/export ─────────────────────────────────────────────────

@router.get("/profiles/export")
async def export_profiles(
    request: Request,
    format: str = Query(default="csv"),
    gender: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None, ge=0),
    max_age: Optional[int] = Query(default=None, ge=0),
    sort_by: Optional[str] = Query(default=None),
    order: Optional[str] = Query(default="asc"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    if format != "csv":
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Only format=csv is supported"}
        )

    query = select(Profile)

    if gender:
        query = query.where(func.lower(Profile.gender) == gender.lower())
    if country_id:
        query = query.where(func.upper(Profile.country_id) == country_id.upper())
    if age_group:
        query = query.where(func.lower(Profile.age_group) == age_group.lower())
    if min_age is not None:
        query = query.where(Profile.age >= min_age)
    if max_age is not None:
        query = query.where(Profile.age <= max_age)
    if sort_by and sort_by in VALID_SORT_FIELDS:
        sort_column = getattr(Profile, sort_by)
        query = query.order_by(asc(sort_column) if order == "asc" else desc(sort_column))

    result = await db.execute(query)
    profiles = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "gender", "gender_probability",
        "age", "age_group", "country_id", "country_name",
        "country_probability", "created_at"
    ])
    for p in profiles:
        writer.writerow([
            p.id, p.name, p.gender, p.gender_probability,
            p.age, p.age_group, p.country_id, p.country_name,
            p.country_probability,
            p.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        ])

    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"profiles_{timestamp}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─── GET /api/profiles/search ─────────────────────────────────────────────────

@router.get("/profiles/search")
async def search_profiles(
    request: Request,
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    limit = min(limit, 50)

    if not q or not q.strip():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Query parameter 'q' is required"}
        )

    filters = parse_natural_language_query(q.strip())
    if filters is None:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Unable to interpret query"}
        )

    query = select(Profile)
    if "gender" in filters:
        query = query.where(Profile.gender == filters["gender"])
    if "age_group" in filters:
        query = query.where(Profile.age_group == filters["age_group"])
    if "country_id" in filters:
        query = query.where(
            func.upper(Profile.country_id) == filters["country_id"].upper()
        )
    if "min_age" in filters:
        query = query.where(Profile.age >= filters["min_age"])
    if "max_age" in filters:
        query = query.where(Profile.age <= filters["max_age"])

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar()

    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    profiles = result.scalars().all()

    return JSONResponse(
        status_code=200,
        content=build_pagination_response(
            profiles, total, page, limit,
            "/api/profiles/search",
            {"q": q}
        )
    )


# ─── GET /api/profiles ────────────────────────────────────────────────────────

@router.get("/profiles")
async def list_profiles(
    request: Request,
    gender: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None, ge=0),
    max_age: Optional[int] = Query(default=None, ge=0),
    min_gender_probability: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    min_country_probability: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    sort_by: Optional[str] = Query(default=None),
    order: Optional[str] = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    limit = min(limit, 50)

    if sort_by and sort_by not in VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Invalid query parameters"}
        )
    if order not in VALID_ORDERS:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Invalid query parameters"}
        )

    query = select(Profile)

    if gender:
        query = query.where(func.lower(Profile.gender) == gender.lower())
    if country_id:
        query = query.where(func.upper(Profile.country_id) == country_id.upper())
    if age_group:
        query = query.where(func.lower(Profile.age_group) == age_group.lower())
    if min_age is not None:
        query = query.where(Profile.age >= min_age)
    if max_age is not None:
        query = query.where(Profile.age <= max_age)
    if min_gender_probability is not None:
        query = query.where(Profile.gender_probability >= min_gender_probability)
    if min_country_probability is not None:
        query = query.where(Profile.country_probability >= min_country_probability)
    if sort_by:
        sort_column = getattr(Profile, sort_by)
        query = query.order_by(
            asc(sort_column) if order == "asc" else desc(sort_column)
        )

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar()

    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    profiles = result.scalars().all()

    query_params = {
        k: v for k, v in {
            "gender": gender,
            "country_id": country_id,
            "age_group": age_group,
            "min_age": min_age,
            "max_age": max_age,
            "sort_by": sort_by,
            "order": order if sort_by else None,
        }.items() if v is not None
    }

    return JSONResponse(
        status_code=200,
        content=build_pagination_response(
            profiles, total, page, limit,
            "/api/profiles", query_params
        )
    )


# ─── GET /api/profiles/{id} ───────────────────────────────────────────────────

@router.get("/profiles/{profile_id}")
async def get_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    result = await db.execute(
        select(Profile).where(Profile.id == profile_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "message": "Profile not found"}
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": ProfileData.model_validate(profile).model_dump(mode="json")
        }
    )


# ─── DELETE /api/profiles/{id} (Admin only) ───────────────────────────────────

@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(Profile).where(Profile.id == profile_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "message": "Profile not found"}
        )

    await db.delete(profile)
    await db.commit()
    return Response(status_code=204)