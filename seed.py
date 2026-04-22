"""
Run this once to seed the database with all 2026 profiles.
Usage: python seed.py
Re-running is safe — it skips existing records (idempotent).
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

for param in ["?sslmode=require", "&sslmode=require", "?ssl=require", "&ssl=require"]:
    DATABASE_URL = DATABASE_URL.replace(param, "")


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


async def seed():
    from app.database import Base
    from app.models import Profile

    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"ssl": "require"}
    )

    async_session = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    seed_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_profiles.json")

    if not os.path.exists(seed_file):
        print(f"❌ ERROR: seed_profiles.json not found at {seed_file}")
        return

    with open(seed_file, "r") as f:
        data = json.load(f)

    profiles = data["profiles"]
    print(f"📦 Found {len(profiles)} profiles to seed...")

    inserted = 0
    skipped = 0

    async with async_session() as session:
        for p in profiles:
            name = p["name"].strip().lower()

            result = await session.execute(
                select(Profile).where(Profile.name == name)
            )
            existing = result.scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            profile = Profile(
                id=generate_uuid7(),
                name=name,
                gender=p["gender"],
                gender_probability=p["gender_probability"],
                age=p["age"],
                age_group=p["age_group"],
                country_id=p["country_id"],
                country_name=p["country_name"],
                country_probability=p["country_probability"],
                sample_size=None,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            session.add(profile)
            inserted += 1

            if inserted % 100 == 0:
                await session.commit()
                print(f"  ✅ Inserted {inserted} so far...")

        await session.commit()

    print(f"\n🎉 Seeding complete!")
    print(f"   Inserted : {inserted}")
    print(f"   Skipped  : {skipped} (already existed)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())