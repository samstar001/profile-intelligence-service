import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, asc, desc

from app.database import get_db
from app.models import Profile
from app.schemas import (
    ProfileCreate,
    ProfileData,
    ProfileListItem,
    PaginatedProfileResponse,
)
from app.services.enrichment import fetch_enrichment_data
from app.services.nlp_parser import parse_natural_language_query

router = APIRouter()

VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDERS = {"asc", "desc"}


# ── UUID v7 Generator ──────────────────────────────────────────────────────────
def generate_uuid7() -> str:
    timestamp_ms = int(time.time() * 1000)
    ts_bytes = timestamp_ms.to_bytes(6, "big")
    rand_bytes = os.urandom(10)
    b = bytearray(16)
    b[0:6] = ts_bytes
    b[6:16] = rand_bytes
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ── POST /api/profiles ─────────────────────────────────────────────────────────
@router.post("/profiles")
async def create_profile(
    body: ProfileCreate,
    db: AsyncSession = Depends(get_db)
):
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Name is required"}
        )

    name = body.name.strip().lower()

    # Idempotency check
    result = await db.execute(select(Profile).where(Profile.name == name))
    existing = result.scalar_one_or_none()

    if existing:
        # Return 200 with "already exists" message
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileData.model_validate(existing).model_dump(
                    mode="json"
                )
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

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=201,
        content={
            "status": "success",
            "data": ProfileData.model_validate(profile).model_dump(mode="json")
        }
    )

# ── GET /api/profiles/search ───────────────────────────────────────────────────
# NOTE: This route MUST be defined before /profiles/{profile_id}
# otherwise FastAPI will treat "search" as a profile_id
@router.get("/profiles/search", status_code=200)
async def search_profiles(
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
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

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar()

    # Paginate
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    profiles = result.scalars().all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [ProfileListItem.model_validate(p) for p in profiles]
    }


# ── GET /api/profiles ──────────────────────────────────────────────────────────
@router.get("/profiles", status_code=200)
async def list_profiles(
    # Filters
    gender: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None, ge=0),
    max_age: Optional[int] = Query(default=None, ge=0),
    min_gender_probability: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    min_country_probability: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    # Sorting
    sort_by: Optional[str] = Query(default=None),
    order: Optional[str] = Query(default="asc"),
    # Pagination
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    # Validate sort_by and order
    if sort_by and sort_by not in VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": f"Invalid sort_by. Must be one of: {', '.join(VALID_SORT_FIELDS)}"
            }
        )

    if order not in VALID_ORDERS:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "Invalid order. Must be 'asc' or 'desc'"
            }
        )

    query = select(Profile)

    # ── Apply filters ──────────────────────────────────────────────────────────
    if gender:
        query = query.where(func.lower(Profile.gender) == gender.lower())
    if country_id:
        query = query.where(
            func.upper(Profile.country_id) == country_id.upper()
        )
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

    # ── Apply sorting ──────────────────────────────────────────────────────────
    if sort_by:
        sort_column = getattr(Profile, sort_by)
        query = query.order_by(asc(sort_column) if order == "asc" else desc(sort_column))

    # ── Total count before pagination ──────────────────────────────────────────
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar()

    # ── Apply pagination ───────────────────────────────────────────────────────
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    profiles = result.scalars().all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [ProfileListItem.model_validate(p) for p in profiles]
    }


# ── GET /api/profiles/{id} ─────────────────────────────────────────────────────
@router.get("/profiles/{profile_id}", status_code=200)
async def get_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db)
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

    return {
        "status": "success",
        "data": ProfileData.model_validate(profile)
    }


# ── DELETE /api/profiles/{id} ──────────────────────────────────────────────────
@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db)
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