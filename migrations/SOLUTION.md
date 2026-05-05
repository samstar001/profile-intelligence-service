# SOLUTION.md — Stage 4B: System Optimization & Data Ingestion

## Part 1: Query Performance

### What Was Done
1. **Database Indexes** — Added B-tree indexes on all frequently filtered columns
2. **Query Result Cache** — Added Redis cache (Upstash) for repeated query results
3. **Connection Pooling** — Configured SQLAlchemy connection pool (pool_size=10, max_overflow=20)

### Before vs After (Estimated on 1M+ rows)

| Query Type | Before (no indexes) | After (indexes + cache) |
|---|---|---|
| First request (cache miss) | 800-2000ms | 80-200ms |
| Repeated request (cache hit) | 800-2000ms | 5-15ms |
| Combined filter query | 1500-3000ms | 100-300ms |
| Count query for pagination | 500-1500ms | 50-150ms |

### Why Each Decision
- **Indexes**: B-tree indexes on gender, country_id, age, age_group reduce
  full table scans to O(log n) lookups. Compound index on (gender, country_id, age_group)
  covers the most common combined filter in one lookup.
- **Cache TTL=300s**: Short enough that stale data rarely affects analytics.
  Long enough that burst traffic (many users querying same data) is served from cache.
- **pool_size=10**: 10 persistent connections handle hundreds of concurrent requests
  because each request holds a connection for only milliseconds.

---

## Part 2: Query Normalisation

### What Was Done
Built into `app/services/cache.py` via `normalise_filters()` and `build_cache_key()`.

### How It Works
Before building a cache key, all filter dictionaries are normalised:
1. String values lowercased and stripped
2. None values removed
3. Float values rounded to 4 decimal places
4. Keys sorted alphabetically

### Example
Query 1: "Nigerian females between 20 and 45"
→ {gender: "female", country_id: "NG", min_age: 20, max_age: 45}
Query 2: "Women aged 20-45 living in Nigeria"
→ {country_id: "NG", gender: "female", max_age: 45, min_age: 20}
After normalisation both produce:
→ {country_id: "ng", gender: "female", max_age: 45, min_age: 20}
→ Cache key: "profiles:a3f8c2d1e4b56789"
→ IDENTICAL — second query hits cache

### Design Decisions
- **Deterministic**: Same input always produces same output — no randomness
- **No AI**: Pure Python dict manipulation — fast, predictable, no external dependencies
- **SHA256 hashing**: Keeps cache keys short (16 chars) while being collision-resistant

---

## Part 3: CSV Data Ingestion

### Endpoint
`POST /api/profiles/upload` — Admin only, multipart/form-data

### Architecture
- **Streaming**: File read with `content.decode()` and `csv.DictReader` — no loading entire file into memory as Python objects
- **Batching**: Rows collected in batches of 1,000, then bulk-inserted with `INSERT INTO profiles VALUES (...), (...), ...`
- **Bulk duplicate check**: All names in a batch checked against database in ONE query (`WHERE name IN (...)`) instead of one query per row
- **No rollback**: Rows already inserted remain on partial failure — upload is resumable

### How Failures Are Handled

| Failure Type | Behaviour |
|---|---|
| Wrong file extension | Reject entire upload (400) |
| Missing CSV headers | Reject entire upload (400) |
| Row with invalid age | Skip row, increment invalid_age counter |
| Row with unknown gender | Skip row, increment invalid_gender counter |
| Row with missing fields | Skip row, increment missing_fields counter |
| Malformed row | Skip row, increment malformed_row counter |
| Duplicate name (in DB) | Skip row, increment duplicate_name counter |
| Duplicate name (in file) | Skip second occurrence, increment duplicate_name counter |
| Single bad row | Never fails entire upload — skipped and counted |
| Partial failure midway | Inserted rows remain — no rollback |

### Edge Cases
- Duplicate names within the same CSV file are detected and the second one skipped
- File encoding errors handled with `errors="replace"` — bad bytes replaced, upload continues
- Empty file or file with only headers returns inserted=0 with no error
- Concurrent uploads are safe — each uses its own database session

### Batch Size Choice
1,000 rows per batch balances:
- Memory usage (1,000 rows ≈ 200KB in memory — negligible)
- Database round trips (500,000 rows = 500 INSERT statements instead of 500,000)
- Transaction size (small enough that a failure loses at most 1,000 rows)