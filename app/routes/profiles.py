import os
import csv
import io
import math
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, JSONResponse, StreamingResponse
from fastapi import UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, asc, desc

from app.database import get_db
from app.models import Profile, User
from app.schemas import ProfileCreate, ProfileData, ProfileListItem, UserResponse
from app.schemas import CSVUploadResponse, SkipReasons
from app.services.enrichment import fetch_enrichment_data
from app.services.nlp_parser import parse_natural_language_query
from app.dependencies import require_admin, require_any_role
from app.auth import generate_uuid7

router = APIRouter()

VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDERS = {"asc", "desc"}


# ─── Pagination Helper ─────────────────────────────────────────────────────────

def build_pagination_response(
    profiles, total, page, limit, base_url, query_params: dict
):
    total_pages = math.ceil(total / limit) if total > 0 else 1

    def build_url(p: int) -> str:
        params = {**query_params, "page": p, "limit": limit}
        query_str = "&".join(
            f"{k}={v}" for k, v in params.items() if v is not None
        )
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


# ─── GET /api/users/me ────────────────────────────────────────────────────────

@router.get("/users/me")
async def get_current_user_profile(
    current_user: User = Depends(require_any_role),
):
    """
    Returns the current authenticated user's profile.
    Accessible by both admin and analyst roles.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": UserResponse.model_validate(
                current_user
            ).model_dump(mode="json")
        }
    )


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

    result = await db.execute(
        select(Profile).where(Profile.name == name)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileData.model_validate(
                    existing
                ).model_dump(mode="json")
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
            detail={
                "status": "error",
                "message": "Only format=csv is supported"
            }
        )

    query = select(Profile)

    if gender:
        query = query.where(func.lower(Profile.gender) == gender.lower())
    if country_id:
        query = query.where(
            func.upper(Profile.country_id) == country_id.upper()
        )
    if age_group:
        query = query.where(
            func.lower(Profile.age_group) == age_group.lower()
        )
    if min_age is not None:
        query = query.where(Profile.age >= min_age)
    if max_age is not None:
        query = query.where(Profile.age <= max_age)
    if sort_by and sort_by in VALID_SORT_FIELDS:
        sort_column = getattr(Profile, sort_by)
        query = query.order_by(
            asc(sort_column) if order == "asc" else desc(sort_column)
        )

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
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )

# ─── POST /api/profiles/upload (Admin only) ───────────────────────────────────

VALID_GENDERS   = {"male", "female"}
VALID_AGE_GROUPS = {"child", "teenager", "adult", "senior"}
REQUIRED_FIELDS  = {"name", "gender", "gender_probability", "age",
                    "age_group", "country_id", "country_name", "country_probability"}
BATCH_SIZE = 1000


def validate_row(row: dict) -> tuple[bool, str]:
    # Check all required fields present and non-empty
    for field in REQUIRED_FIELDS:
        if not row.get(field, "").strip():
            return False, "missing_fields"

    # Validate gender
    if row["gender"].strip().lower() not in VALID_GENDERS:
        return False, "invalid_gender"

    # Validate age
    try:
        age = int(row["age"])
        if age < 0 or age > 150:
            return False, "invalid_age"
    except (ValueError, TypeError):
        return False, "invalid_age"

    # Validate probabilities
    try:
        gp = float(row["gender_probability"])
        cp = float(row["country_probability"])
        if not (0.0 <= gp <= 1.0) or not (0.0 <= cp <= 1.0):
            return False, "invalid_age"
    except (ValueError, TypeError):
        return False, "malformed_row"

    return True, ""


async def insert_batch(session, batch: list) -> int:
    # Bulk insert using insert().values() — much faster than one-by-one
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import insert as sa_insert

    if not batch:
        return 0

    try:
        stmt = sa_insert(Profile).values(batch)
        await session.execute(stmt)
        await session.commit()
        return len(batch)
    except Exception:
        await session.rollback()
        return 0


@router.post("/profiles/upload", response_model=CSVUploadResponse)
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # ── Validate file type ─────────────────────────────────────────────────
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Only CSV files are accepted"}
        )

    # ── Counters ───────────────────────────────────────────────────────────
    total_rows      = 0
    inserted_count  = 0
    skip_reasons    = {
        "duplicate_name": 0,
        "invalid_age": 0,
        "invalid_gender": 0,
        "missing_fields": 0,
        "malformed_row": 0,
    }

    # ── Stream and process in batches ──────────────────────────────────────
    batch_to_insert = []

    try:
        # Read file content — stream via SpooledTemporaryFile
        content = await file.read()
        text    = content.decode("utf-8", errors="replace")
        reader  = csv.DictReader(io.StringIO(text))

        # Verify required headers exist
        if not reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "CSV file is empty or has no headers"}
            )

        missing_headers = REQUIRED_FIELDS - set(f.strip() for f in reader.fieldnames)
        if missing_headers:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": f"Missing CSV columns: {missing_headers}"}
            )

        # ── Collect all names in this file for bulk duplicate check ────────
        all_names_in_file = []
        all_rows          = []

        for row in reader:
            total_rows += 1

            # Skip malformed rows (wrong column count)
            if len(row) < len(REQUIRED_FIELDS):
                skip_reasons["malformed_row"] += 1
                continue

            valid, reason = validate_row(row)
            if not valid:
                skip_reasons[reason] += 1
                continue

            name = row["name"].strip().lower()
            all_names_in_file.append(name)
            all_rows.append(row)

        # ── Bulk check which names already exist in database ───────────────
        if all_names_in_file:
            existing_result = await db.execute(
                select(Profile.name).where(Profile.name.in_(all_names_in_file))
            )
            existing_names = {r[0] for r in existing_result.fetchall()}
        else:
            existing_names = set()

        # ── Build insert batches skipping duplicates ───────────────────────
        seen_in_file = set()

        for row in all_rows:
            name = row["name"].strip().lower()

            # Skip duplicates from database
            if name in existing_names:
                skip_reasons["duplicate_name"] += 1
                continue

            # Skip duplicates within the file itself
            if name in seen_in_file:
                skip_reasons["duplicate_name"] += 1
                continue

            seen_in_file.add(name)

            # Build profile record
            from datetime import datetime, timezone
            batch_to_insert.append({
                "id":                   generate_uuid7(),
                "name":                 name,
                "gender":               row["gender"].strip().lower(),
                "gender_probability":   float(row["gender_probability"]),
                "age":                  int(row["age"]),
                "age_group":            row["age_group"].strip().lower(),
                "country_id":           row["country_id"].strip().upper(),
                "country_name":         row["country_name"].strip(),
                "country_probability":  float(row["country_probability"]),
                "sample_size":          None,
                "created_at":           datetime.now(timezone.utc).replace(tzinfo=None),
            })

            # ── Insert when batch is full ──────────────────────────────────
            if len(batch_to_insert) >= BATCH_SIZE:
                count = await insert_batch(db, batch_to_insert)
                inserted_count  += count
                batch_to_insert  = []

        # ── Insert remaining rows (last partial batch) ─────────────────────
        if batch_to_insert:
            count = await insert_batch(db, batch_to_insert)
            inserted_count += count

        # ── Invalidate caches after upload ─────────────────────────────────
        from app.services.cache import invalidate_prefix
        await invalidate_prefix("profiles")
        await invalidate_prefix("search")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Upload failed: {str(e)}"}
        )

    total_skipped = sum(skip_reasons.values())

    return {
        "status":     "success",
        "total_rows": total_rows,
        "inserted":   inserted_count,
        "skipped":    total_skipped,
        "reasons":    skip_reasons,
    }


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
            detail={
                "status": "error",
                "message": "Query parameter 'q' is required"
            }
        )

    filters = parse_natural_language_query(q.strip())
    if filters is None:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "Unable to interpret query"
            }
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
            "/api/profiles/search", {"q": q}
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
    min_gender_probability: Optional[float] = Query(
        default=None, ge=0.0, le=1.0
    ),
    min_country_probability: Optional[float] = Query(
        default=None, ge=0.0, le=1.0
    ),
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
            detail={
                "status": "error",
                "message": "Invalid query parameters"
            }
        )
    if order not in VALID_ORDERS:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "Invalid query parameters"
            }
        )

    query = select(Profile)

    if gender:
        query = query.where(
            func.lower(Profile.gender) == gender.lower()
        )
    if country_id:
        query = query.where(
            func.upper(Profile.country_id) == country_id.upper()
        )
    if age_group:
        query = query.where(
            func.lower(Profile.age_group) == age_group.lower()
        )
    if min_age is not None:
        query = query.where(Profile.age >= min_age)
    if max_age is not None:
        query = query.where(Profile.age <= max_age)
    if min_gender_probability is not None:
        query = query.where(
            Profile.gender_probability >= min_gender_probability
        )
    if min_country_probability is not None:
        query = query.where(
            Profile.country_probability >= min_country_probability
        )
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
            "data": ProfileData.model_validate(
                profile
            ).model_dump(mode="json")
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