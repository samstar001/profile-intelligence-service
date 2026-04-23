# Profile Intelligence Service

A RESTful API that enriches names with demographic data and provides
a queryable intelligence engine for demographic analysis.

Built for **Insighta Labs** — a demographic intelligence company whose clients
(marketing teams, product teams, growth analysts) rely on this API to segment
users, identify patterns, and query large datasets quickly.

---

## Tech Stack

- **Python 3.12**
- **FastAPI** — async web framework
- **PostgreSQL** (Neon cloud) — production database
- **SQLAlchemy** (async) — ORM and query builder
- **httpx** — async HTTP client for external API calls
- **Vercel** — deployment platform

---

## Live URL

https://profile-intelligence-service-rcl7.vercel.app

---

## Endpoints

### Stage 1 — Core CRUD

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/profiles | Create a new profile from a name |
| GET | /api/profiles/{id} | Get a single profile by UUID |
| DELETE | /api/profiles/{id} | Delete a profile by UUID |

### Stage 2 — Intelligence Query Engine

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/profiles | List profiles with filtering, sorting, pagination |
| GET | /api/profiles/search | Natural language query search |

---

## Filtering (GET /api/profiles)

All filters are combinable. Results strictly match all conditions.

| Parameter | Type | Example | Description |
|-----------|------|---------|-------------|
| gender | string | male | Filter by gender |
| age_group | string | adult | child, teenager, adult, senior |
| country_id | string | NG | ISO 2-letter country code |
| min_age | int | 20 | Minimum age (inclusive) |
| max_age | int | 40 | Maximum age (inclusive) |
| min_gender_probability | float | 0.8 | Minimum gender confidence |
| min_country_probability | float | 0.5 | Minimum country confidence |
| sort_by | string | age | age, created_at, gender_probability |
| order | string | desc | asc or desc (default: asc) |
| page | int | 1 | Page number (default: 1) |
| limit | int | 10 | Results per page (default: 10, max: 50) |

**Example:**