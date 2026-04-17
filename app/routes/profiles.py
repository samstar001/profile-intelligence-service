import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import Profile
from app.schemas import (
    ProfileCreate,
    ProfileData,
    ProfileListItem,
    ProfileListResponse,
)
from app.services.enrichment import fetch_enrichment_data

router = APIRouter()


# ── UUID v7 Generator ──────────────────────────────────────────────────────────
def generate_uuid7() -> str:
    timestamp_ms = int(time.time() * 1000)
    ts_bytes = timestamp_ms.to_bytes(6, "big")
    rand_bytes = os.urandom(10)

    b = bytearray(16)
    b[0:6] = ts_bytes
    b[6:16] = rand_bytes

    # Version 7
    b[6] = (b[6] & 0x0F) | 0x70
    # Variant 10xx
    b[8] = (b[8] & 0x3F) | 0x80

    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ── POST /api/profiles ─────────────────────────────────────────────────────────
@router.post("/profiles", status_code=201)
async def create_profile(
    body: ProfileCreate,
    db: AsyncSession = Depends(get_db)
):
    # 400 — missing or empty name
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Name is required"}
        )

    name = body.name.strip().lower()

    # Idempotency — return existing record if name already exists
    result = await db.execute(
        select(Profile).where(Profile.name == name)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return {
            "status": "success",
            "message": "Profile already exists",
            "data": ProfileData.model_validate(existing)
        }

    # Call all 3 external APIs
    enriched = await fetch_enrichment_data(name)

    # Build profile record
    profile = Profile(
        id=generate_uuid7(),
        name=name,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        **enriched
    )

    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return {
        "status": "success",
        "data": ProfileData.model_validate(profile)
    }


# ── GET /api/profiles ──────────────────────────────────────────────────────────
@router.get("/profiles", status_code=200)
async def list_profiles(
    gender: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    query = select(Profile)

    if gender:
        query = query.where(
            func.lower(Profile.gender) == gender.lower()
        )
    if country_id:
        query = query.where(
            func.lower(Profile.country_id) == country_id.lower()
        )
    if age_group:
        query = query.where(
            func.lower(Profile.age_group) == age_group.lower()
        )

    result = await db.execute(query)
    profiles = result.scalars().all()

    return {
        "status": "success",
        "count": len(profiles),
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