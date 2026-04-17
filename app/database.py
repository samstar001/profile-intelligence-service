import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Convert standard postgresql:// to async version if needed
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remove sslmode/ssl query param — asyncpg handles SSL via connect_args
DATABASE_URL = DATABASE_URL.replace("?ssl=require", "").replace("&ssl=require", "")
DATABASE_URL = DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": "require"}  # ← Neon requires this
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def init_db():
    """Creates all tables on startup"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Dependency that provides a DB session per request"""
    async with AsyncSessionLocal() as session:
        yield session