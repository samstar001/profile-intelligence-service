import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env file")

# Convert to asyncpg format
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Strip SSL params from URL — passed via connect_args instead
for param in ["?sslmode=require", "&sslmode=require", "?ssl=require", "&ssl=require"]:
    DATABASE_URL = DATABASE_URL.replace(param, "")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": "require"}
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