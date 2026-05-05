# database.py — Database Connection and Session Management
#
# ─── What Changed for Stage 4B ────────────────────────────────────────────────
# Added connection pool configuration:
#   pool_size, max_overflow, pool_pre_ping, pool_recycle
#
# ─── Why Connection Pooling Matters ───────────────────────────────────────────
# Problem without pooling:
#   Every HTTP request creates a NEW database connection.
#   Creating a connection takes ~100ms (network handshake, auth).
#   At 500 requests/minute, that's 500 new connections opening simultaneously.
#   PostgreSQL has a limit (~100 connections by default).
#   Result: "too many connections" errors — requests start failing.
#
# Solution with pooling:
#   SQLAlchemy keeps a POOL of pre-established connections (10 by default).
#   When a request needs the database, it BORROWS a connection from the pool.
#   When done, it RETURNS it — the connection stays open for the next request.
#   Connection creation overhead (~100ms) only happens 10 times (pool startup).
#   All subsequent requests reuse these 10 connections.

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env file")

# ─── URL Format Conversion ─────────────────────────────────────────────────────
# Neon gives: postgresql://user:pass@host/db
# asyncpg needs: postgresql+asyncpg://user:pass@host/db
# The +asyncpg tells SQLAlchemy which driver to use for async operations

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Remove SSL parameters from URL — asyncpg handles SSL via connect_args instead
for param in ["?sslmode=require", "&sslmode=require", "?ssl=require", "&ssl=require"]:
    DATABASE_URL = DATABASE_URL.replace(param, "")

# ─── Database Engine ───────────────────────────────────────────────────────────
# The engine is the core component — it manages the connection pool
# and translates Python SQLAlchemy calls into PostgreSQL SQL

engine = create_async_engine(
    DATABASE_URL,

    echo=False,
    # echo=True would print every SQL statement to the terminal
    # Useful for debugging, noisy in production — keep False

    # ── Connection Pool Settings ─────────────────────────────────────────
    pool_size=10,
    # How many connections to keep open permanently in the pool.
    # These connections are established when the app starts and
    # stay open throughout the app's lifetime.
    # 10 connections can serve hundreds of concurrent requests because
    # most requests only hold a connection for milliseconds.

    max_overflow=20,
    # Extra connections allowed when all pool_size connections are busy.
    # These are created on demand and closed when no longer needed.
    # Total max connections = pool_size + max_overflow = 10 + 20 = 30
    # At 30 connections we're well within Neon's free tier limits.

    pool_pre_ping=True,
    # Before giving a connection to a request, send a quick "ping" to
    # verify the connection is still alive.
    # Why needed: Neon may close idle connections after a timeout.
    # Without pre_ping: request gets a dead connection → error.
    # With pre_ping: dead connection detected → new one created → no error.
    # Small overhead (~1ms) but prevents connection errors in production.

    pool_recycle=300,
    # After 300 seconds (5 minutes), discard a connection and create a fresh one.
    # Why: some database servers (including Neon) have connection timeouts.
    # Recycling prevents using connections that the server has already closed.
    # Complements pool_pre_ping — belt and suspenders approach.

    connect_args={
        "ssl": "require",
        # All connections to Neon must be encrypted.
        # Neon rejects unencrypted connections.

        "command_timeout": 30,
        # If a database query takes longer than 30 seconds, kill it.
        # Prevents one slow query from holding a connection forever
        # and blocking other requests.

        "timeout": 10,
        # If the database connection itself cannot be established
        # within 10 seconds, fail fast with an error.
        # Prevents requests from hanging indefinitely during outages.
    }
)

# ─── Session Factory ────────────────────────────────────────────────────────────
# AsyncSessionLocal is a FACTORY — calling it creates a new session object.
# Each HTTP request gets its own session via the get_db() dependency.
# A session = one unit of work with the database (like one conversation).

AsyncSessionLocal = sessionmaker(
    bind=engine,
    # Use our configured engine with the connection pool

    class_=AsyncSession,
    # Create async sessions that support await syntax

    expire_on_commit=False
    # By default, after commit() all object attributes are expired
    # (cleared to force a reload from DB on next access).
    # expire_on_commit=False keeps attributes accessible after commit.
    # Without this: accessing profile.id after db.commit() would trigger
    # another database query just to get the ID we already have.
)

# ─── Declarative Base ───────────────────────────────────────────────────────────
# Base is the parent class all models (Profile, User, RefreshToken) inherit from.
# SQLAlchemy uses Base.metadata to track all model classes.
# Base.metadata.create_all() reads all models and creates their tables.

Base = declarative_base()


# ─── Database Initialisation ────────────────────────────────────────────────────

async def init_db():
    """
    Creates all database tables on application startup.

    Called once in main.py's lifespan function (before accepting requests).
    Uses CREATE TABLE IF NOT EXISTS — safe to call every startup.
    If tables already exist, nothing happens.
    If a new model is added, its table is created automatically.
    """
    async with engine.begin() as conn:
        # engine.begin() opens a connection AND starts a transaction
        # run_sync wraps the synchronous create_all() in async context
        await conn.run_sync(Base.metadata.create_all)


# ─── Request-Scoped Database Session ────────────────────────────────────────────

async def get_db():
    """
    FastAPI dependency that provides a database session for each request.

    How it works:
        1. FastAPI calls get_db() before your route handler runs
        2. A new session is created from the pool
        3. The session is yielded (passed) to the route handler as 'db'
        4. Route handler uses db to query/write data
        5. After route handler returns, the session is automatically closed
        6. The database connection is returned to the pool

    Usage in routes:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Profile))

    Error handling:
        If an exception occurs in the route handler, the 'async with'
        block catches it and closes the session cleanly.
        The connection is returned to the pool regardless of success/failure.
        No connection leaks.
    """
    async with AsyncSessionLocal() as session:
        yield session
        # yield pauses this generator here
        # FastAPI injects the session into the route handler
        # When the route handler finishes, execution resumes here
        # 'async with' then closes the session automatically