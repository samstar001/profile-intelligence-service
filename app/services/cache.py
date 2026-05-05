# app/services/cache.py
#
# ─── What This File Does ───────────────────────────────────────────────────────
# This file provides caching for the Profile Intelligence Service.
# Caching means: store the result of an expensive operation (database query)
# in fast memory (Redis) so the next identical request gets the result
# instantly without hitting the database again.
#
# ─── The Problem It Solves ────────────────────────────────────────────────────
# Without caching:
#   Request 1: GET /api/profiles?gender=male → hits database → 200ms
#   Request 2: GET /api/profiles?gender=male → hits database → 200ms
#   Request 3: GET /api/profiles?gender=male → hits database → 200ms
#   (Each request does identical work, wasting database resources)
#
# With caching:
#   Request 1: GET /api/profiles?gender=male → hits database → 200ms → saves to Redis
#   Request 2: GET /api/profiles?gender=male → reads Redis → 5ms ✅
#   Request 3: GET /api/profiles?gender=male → reads Redis → 5ms ✅
#   (40x faster for repeated queries, zero database load)
#
# ─── TTL (Time To Live) ───────────────────────────────────────────────────────
# Cached results expire after 300 seconds (5 minutes).
# After expiry, the next request hits the database again and refreshes the cache.
# This ensures data doesn't stay stale forever.

import os
import json
import hashlib
import logging
from typing import Optional, Any
from dotenv import load_dotenv

load_dotenv()
# load_dotenv() reads your .env file so os.getenv() can find UPSTASH_* values

logger = logging.getLogger(__name__)
# Logger records cache hits/misses so you can monitor performance

# ─── Configuration ────────────────────────────────────────────────────────────

CACHE_TTL = 300
# TTL = Time To Live
# 300 seconds = 5 minutes
# Every cached result automatically expires after this time
# Why 5 minutes? Short enough that stale data rarely matters for analytics.
# Analysts query trends over days/weeks — a 5-minute delay is invisible.

REDIS_URL   = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
# Read Redis credentials from environment variables
# Returns None if not set (cache gracefully disabled in that case)

CACHE_ENABLED = bool(REDIS_URL and REDIS_TOKEN)
# CACHE_ENABLED = True only if BOTH values are set
# bool("some_string") = True
# bool(None) = False
# bool("") = False
# This means: if either credential is missing, cache is disabled

# ─── Redis Client Initialisation ──────────────────────────────────────────────

if CACHE_ENABLED:
    try:
        from upstash_redis import Redis
        redis_client = Redis(url=REDIS_URL, token=REDIS_TOKEN)
        # Redis() creates the connection client
        # It uses REST API (HTTP calls) not a persistent TCP connection
        # This is why Upstash works with Vercel serverless — no persistent connections needed
        logger.info("Cache: Redis connection established ✓")
    except Exception as e:
        # If Redis package not installed or connection fails:
        # Don't crash the app — just disable cache and continue
        logger.warning(f"Cache: Redis init failed — {e}. Cache disabled.")
        CACHE_ENABLED = False
        redis_client = None
else:
    redis_client = None
    logger.info("Cache: No Redis credentials found — cache disabled (app works normally)")


# ─── Part 2: Query Normalisation ─────────────────────────────────────────────
#
# THE PROBLEM:
# "Nigerian females between 20 and 45"
#     → parser returns: {gender: "female", country_id: "NG", min_age: 20, max_age: 45}
#
# "Women aged 20-45 living in Nigeria"
#     → parser returns: {country_id: "NG", gender: "female", max_age: 45, min_age: 20}
#
# These are THE SAME QUERY but the dictionary keys are in different order.
# Without normalisation:
#     Key 1: "profiles:gender=female:country_id=NG:min_age=20:max_age=45"
#     Key 2: "profiles:country_id=NG:gender=female:max_age=45:min_age=20"
#     → DIFFERENT keys → BOTH hit database → cache is useless
#
# With normalisation:
#     Both become: "profiles:country_id=ng:gender=female:max_age=45:min_age=20"
#     → SAME key → second query hits cache → 40x faster

def normalise_filters(filters: dict) -> dict:
    """
    Converts any filter dictionary into a canonical (standard) form.

    What 'canonical' means:
    - All string values are lowercased ("Male" → "male", "NG" → "ng")
    - All string values are stripped of whitespace ("  male  " → "male")
    - None values are removed (they have no effect on the query)
    - Float values are rounded to 4 decimal places (prevents key differences
      from floating point precision: 0.80000000001 vs 0.8)
    - Keys are sorted alphabetically (ensures consistent ordering)

    Examples:
        {gender: "Male", country_id: "NG"} → {country_id: "ng", gender: "male"}
        {min_age: None, max_age: 40}       → {max_age: 40}
        {limit: 10, page: 1}               → {limit: 10, page: 1}
    """
    canonical = {}

    for key, value in filters.items():
        # Skip None values — they represent "no filter applied"
        # Having None in the cache key would be wrong:
        # ?gender=male (no country filter) and ?gender=male&country_id=None
        # should produce the same key
        if value is None:
            continue

        if isinstance(value, str):
            # Lowercase and strip all string values
            canonical[key] = value.lower().strip()

        elif isinstance(value, float):
            # Round floats to avoid precision differences
            # 0.90000000001 and 0.9 should produce the same cache key
            canonical[key] = round(value, 4)

        else:
            # int, bool, etc. — use as-is
            canonical[key] = value

    # Sort by key alphabetically
    # dict(sorted(...)) ensures {b:1, a:2} → {a:2, b:1}
    # This is the key step that makes "different order, same intent" work
    return dict(sorted(canonical.items()))


def build_cache_key(prefix: str, params: dict) -> str:
    """
    Builds a unique, deterministic cache key from query parameters.

    Steps:
    1. Normalise the params (lowercase, sort, remove None)
    2. Serialise to JSON string (sorted keys for consistency)
    3. SHA256 hash the string (produces a short, fixed-length key)
    4. Combine with prefix for namespace separation

    Why hashing?
    - The raw param string could be very long
    - Hash is always exactly 16 characters
    - SHA256 is collision-resistant (two different inputs never produce the same hash)

    Example:
        prefix = "profiles"
        params = {gender: "male", country_id: "NG", page: 1, limit: 10}

        After normalise: {country_id: "ng", gender: "male", limit: 10, page: 1}
        After JSON:      '{"country_id": "ng", "gender": "male", "limit": 10, "page": 1}'
        After hash:      "a3f8c2d1e4b56789"
        Final key:       "profiles:a3f8c2d1e4b56789"
    """
    normalised  = normalise_filters(params)
    serialised  = json.dumps(normalised, sort_keys=True)
    # sort_keys=True in json.dumps is an extra safety net —
    # even if normalise_filters misses something, JSON serialisation
    # will sort the keys consistently
    hash_val    = hashlib.sha256(serialised.encode()).hexdigest()[:16]
    # hexdigest() returns a 64-char hex string
    # [:16] takes the first 16 chars — short enough for Redis keys
    # collision probability at 16 chars is astronomically low
    return f"{prefix}:{hash_val}"


# ─── Cache Read ───────────────────────────────────────────────────────────────

async def get_cached(key: str) -> Optional[Any]:
    """
    Retrieves a cached value by its key.

    Returns:
        The cached Python object (dict/list) if found
        None if the key doesn't exist or has expired

    Why async?
    The function is async to be compatible with FastAPI's async routing.
    Upstash uses REST API calls (HTTP) which are I/O operations.
    Making it async means FastAPI can handle other requests while
    waiting for the Redis response.

    Error handling:
    If Redis is down or times out, we catch the exception and return None.
    The route handler then falls through to the database — the app keeps
    working, just without cache acceleration.
    """
    if not CACHE_ENABLED or not redis_client:
        return None
    # If cache is disabled, always return None → always query database
    # This makes the cache completely transparent — the app works
    # identically with or without cache, just at different speeds

    try:
        value = redis_client.get(key)
        # redis_client.get() returns:
        #   - The stored string if key exists
        #   - None if key doesn't exist or has expired

        if value is not None:
            logger.debug(f"Cache HIT: {key}")
            # json.loads() converts the stored JSON string back to
            # a Python dict/list — the same object that was stored
            return json.loads(value) if isinstance(value, str) else value

        logger.debug(f"Cache MISS: {key}")
        return None

    except Exception as e:
        # Redis errors (network timeout, connection refused, etc.)
        # must NEVER crash the application
        # Log the warning so you can monitor it, then return None
        # so the route handler falls back to the database
        logger.warning(f"Cache get error for key '{key}': {e}")
        return None


# ─── Cache Write ──────────────────────────────────────────────────────────────

async def set_cached(key: str, value: Any, ttl: int = CACHE_TTL) -> None:
    """
    Stores a value in Redis with an automatic expiry time (TTL).

    Parameters:
        key:   The cache key (from build_cache_key)
        value: The Python dict/list to cache (will be JSON-serialised)
        ttl:   Seconds until this entry expires (default: 300 = 5 minutes)

    How TTL works:
        redis_client.setex(key, ttl, value)
        setex = SET with EXpiry
        After ttl seconds, Redis automatically deletes the key
        The next request for that key gets a cache MISS and queries the database
        This keeps data reasonably fresh without manual cache management

    Error handling:
        Cache write failures are silently logged.
        A failed cache write means the next request will also be a cache miss
        (hits the database) — not ideal for performance but not a bug.
        The API response is unaffected.
    """
    if not CACHE_ENABLED or not redis_client:
        return

    try:
        serialised = json.dumps(value)
        # json.dumps() converts Python dict/list to a JSON string
        # Redis can only store strings — we serialise and deserialise
        # transparently so the route handler never knows

        redis_client.setex(key, ttl, serialised)
        logger.debug(f"Cache SET: {key} (TTL={ttl}s)")

    except Exception as e:
        logger.warning(f"Cache set error for key '{key}': {e}")


# ─── Cache Invalidation ───────────────────────────────────────────────────────

async def invalidate_prefix(prefix: str) -> None:
    """
    Deletes ALL cache keys that start with the given prefix.

    When is this needed?
    When a profile is created or deleted, the list query results
    are now stale (the new profile should appear in the list, or
    the deleted one should be gone).

    Instead of trying to figure out WHICH specific cache keys are affected
    (complex and error-prone), we simply delete ALL keys for that category.
    The next request for any list query will be a cache miss and rebuild
    from the current database state.

    Example:
        invalidate_prefix("profiles")
        → Deletes: profiles:a3f8c2..., profiles:b7d4e1..., profiles:c9f2a3...
        → All profile list caches are cleared

    Why SCAN not KEYS?
    redis_client.keys("profiles:*") works for small datasets.
    In production with millions of keys, KEYS blocks Redis.
    SCAN iterates without blocking. For Upstash's size this is fine either way.
    """
    if not CACHE_ENABLED or not redis_client:
        return

    try:
        keys = redis_client.keys(f"{prefix}:*")
        # Find all keys matching pattern "prefix:*"
        # e.g. "profiles:*" matches "profiles:a3f8c2", "profiles:b7d4e1", etc.

        if keys:
            redis_client.delete(*keys)
            # *keys unpacks the list: delete(key1, key2, key3, ...)
            # Redis deletes all of them in one command (efficient)
            logger.info(f"Cache: cleared {len(keys)} keys with prefix '{prefix}'")
    except Exception as e:
        logger.warning(f"Cache invalidation error for prefix '{prefix}': {e}")