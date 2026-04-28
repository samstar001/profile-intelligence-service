# Insighta Labs — Profile Intelligence Service

> A secure, multi-interface demographic intelligence API built with **FastAPI**, **PostgreSQL**, and **GitHub OAuth 2.0 + PKCE**.

**Live API:** `https://profile-intelligence-service-rcl7.vercel.app/`

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Authentication Flow](#authentication-flow)
- [Token Handling](#token-handling)
- [Role Enforcement](#role-enforcement)
- [API Reference](#api-reference)
- [Filtering & Sorting](#filtering--sorting)
- [Pagination](#pagination)
- [Natural Language Search](#natural-language-search)
- [Rate Limiting & Logging](#rate-limiting--logging)
- [Database Schema](#database-schema)
- [Project Structure](#project-structure)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
- [Commit Convention](#commit-convention)

---

## Overview

Insighta Labs is a demographic intelligence platform that:

- Collects profile data from **Genderize**, **Agify**, and **Nationalize** APIs
- Stores structured profiles in a **PostgreSQL** database (Neon.tech)
- Exposes secure **RESTful endpoints** with authentication and role-based access
- Supports **advanced filtering**, sorting, and pagination across 2026+ profiles
- Includes a **natural language search engine** (rule-based, no AI/LLM)
- Provides **CSV export** for analysts and data teams

Built across three stages:
- **Stage 1** — Data collection and basic CRUD
- **Stage 2** — Advanced querying and natural language search
- **Stage 3** — Authentication, RBAC, rate limiting, CLI, and web portal

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                        CLIENTS                           │
│                                                          │
│     CLI Tool (insighta)       Web Portal (React)         │
└──────────────────┬────────────────────┬──────────────────┘
                   │                    │
                   ▼                    ▼
┌──────────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND                        │
│                                                          │
│   /auth/*  — GitHub OAuth, JWT tokens, sessions          │
│   /api/*   — Profiles CRUD, search, export               │
│                                                          │
│   Middleware: API versioning, logging, rate limiting     │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                PostgreSQL — Neon.tech                    │
│                                                          │
│       profiles  |  users  |  refresh_tokens              │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│               External Enrichment APIs                   │
│                                                          │
│    Genderize.io  |  Agify.io  |  Nationalize.io          │
└──────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI |
| Database | PostgreSQL (Neon.tech) |
| ORM | SQLAlchemy (async) |
| Auth | GitHub OAuth 2.0 + PKCE |
| Tokens | JWT via PyJWT |
| HTTP Client | httpx (async) |
| Rate Limiting | slowapi |
| Server | uvicorn |
| Deployment | Vercel |

---

## Authentication Flow

This system uses **GitHub OAuth 2.0 with PKCE** (Proof Key for Code Exchange).
PKCE adds an extra layer of security by requiring the client to prove it generated
the original authorization request — preventing code interception attacks.

### Step by Step

```
1. Client generates:
   ├── state          → random UUID (prevents CSRF attacks)
   ├── code_verifier  → random secret string (PKCE secret)
   └── code_challenge → SHA256(code_verifier), base64url encoded

2. Client opens browser to:
   GET /auth/github?source=cli&code_challenge=xxx&code_challenge_method=S256

3. Backend adds code_challenge to GitHub OAuth redirect URL

4. User logs in and approves on GitHub

5. GitHub redirects back to:
   GET /auth/github/callback?code=xxx&state=xxx

6. Backend:
   ├── Extracts source (cli or web) from state
   ├── Exchanges code + code_verifier with GitHub
   ├── Fetches user profile and primary email from GitHub API
   ├── Creates new user (analyst role) or updates existing user
   ├── Issues access_token (3 min) + refresh_token (5 min)
   └── Saves refresh_token to database

7. Response:
   ├── CLI source  → JSON body with both tokens
   └── Web source  → HTTP-only cookies + redirect to /dashboard
```

### CLI Login Example

```bash
insighta login
# Opens browser to GitHub OAuth
# Stores tokens in ~/.insighta/credentials.json
# Prints: Logged in as @samstar001
```

### Web Login Example

```
User clicks "Continue with GitHub"
→ Browser redirects to GitHub
→ GitHub redirects to /auth/github/callback
→ Backend sets HTTP-only cookies
→ Browser redirects to /dashboard
```

---

## Token Handling

| Token | Expiry | Stored In | Purpose |
|---|---|---|---|
| Access Token | 3 minutes | CLI: credentials file / Web: memory | Authenticates every API request |
| Refresh Token | 5 minutes | CLI: credentials file / Web: HTTP-only cookie | Gets a new access token when it expires |

### Refresh Flow

```
Access token expires (after 3 min)
         ↓
Client sends refresh token to POST /auth/refresh
         ↓
Backend validates refresh token (JWT + database check)
         ↓
Old refresh token immediately marked as is_used = true
         ↓
Brand new access_token + refresh_token issued
         ↓
Client stores new tokens, retries original request
```

### Security Rules

- Every refresh token can only be used **once** (one-time rotation)
- Used tokens are permanently invalidated in the database
- Web portal tokens are stored in **HTTP-only cookies** (not accessible via JavaScript)
- Inactive users (`is_active = false`) are blocked with **403 Forbidden** on all requests

---

## Role Enforcement

All new users default to the `analyst` role on first login.

| Endpoint | Admin | Analyst |
|---|---|---|
| GET /api/profiles | ✅ | ✅ |
| GET /api/profiles/:id | ✅ | ✅ |
| GET /api/profiles/search | ✅ | ✅ |
| GET /api/profiles/export | ✅ | ✅ |
| POST /api/profiles | ✅ | ❌ 403 |
| DELETE /api/profiles/:id | ✅ | ❌ 403 |

Role checks are enforced through FastAPI dependency injection using
`require_admin` and `require_any_role` guards defined in `dependencies.py`.
There are no scattered inline checks — all access control is centralized.

---

## API Reference

### Required Headers for All /api/* Endpoints

```
Authorization: Bearer <access_token>
x-api-version: 1
```

Missing or wrong `x-api-version` returns:
```json
{"status": "error", "message": "API version header required"}
```

---

### Auth Endpoints

#### GET /auth/github
Redirects to GitHub OAuth page.

Query params:
- `source` — `cli` or `web` (default: `web`)
- `code_challenge` — PKCE challenge string
- `code_challenge_method` — `S256`

---

#### GET /auth/github/callback
Handles GitHub OAuth callback. Called automatically by GitHub after user approves.

Returns (CLI):
```json
{
  "status": "success",
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "username": "samstar001",
  "role": "analyst"
}
```

Returns (Web): HTTP-only cookies + redirect to frontend dashboard.

---

#### POST /auth/refresh
Issues a new token pair. Immediately invalidates the provided refresh token.

Request:
```json
{"refresh_token": "eyJ..."}
```

Response:
```json
{
  "status": "success",
  "access_token": "eyJ...",
  "refresh_token": "eyJ..."
}
```

---

#### POST /auth/logout
Invalidates the refresh token server-side. Always returns 200.

Request:
```json
{"refresh_token": "eyJ..."}
```

Response:
```json
{"status": "success", "message": "Logged out successfully"}
```

---

#### GET /auth/me
Returns the currently authenticated user's profile.

Response:
```json
{
  "status": "success",
  "data": {
    "id": "019dce48-...",
    "username": "samstar001",
    "email": "user@example.com",
    "avatar_url": "https://avatars.githubusercontent.com/...",
    "role": "analyst",
    "is_active": true,
    "last_login_at": "2026-04-28T10:00:00Z",
    "created_at": "2026-04-20T08:00:00Z"
  }
}
```

---

### Profile Endpoints

#### POST /api/profiles — Admin only

Creates a new profile by calling Genderize, Agify, and Nationalize APIs.

Request:
```json
{"name": "Harriet Tubman"}
```

Response (201 Created):
```json
{
  "status": "success",
  "data": {
    "id": "019dce48-...",
    "name": "harriet tubman",
    "gender": "female",
    "gender_probability": 0.97,
    "age": 28,
    "age_group": "adult",
    "country_id": "US",
    "country_name": "United States",
    "country_probability": 0.89,
    "created_at": "2026-04-28T10:00:00Z"
  }
}
```

If name already exists, returns 200 with `"message": "Profile already exists"`.

---

#### GET /api/profiles — Any role

Lists profiles with optional filtering, sorting, and pagination.

```
GET /api/profiles?gender=male&country_id=NG&min_age=25&sort_by=age&order=desc&page=1&limit=10
```

---

#### GET /api/profiles/search — Any role

Natural language search. See [Natural Language Search](#natural-language-search) section.

```
GET /api/profiles/search?q=young males from nigeria&page=1&limit=10
```

---

#### GET /api/profiles/export — Any role

Downloads all matching profiles as a CSV file.

```
GET /api/profiles/export?format=csv&gender=male&country_id=NG
```

Response headers:
```
Content-Type: text/csv
Content-Disposition: attachment; filename="profiles_20260428_120000.csv"
```

CSV columns (in order):
```
id, name, gender, gender_probability, age, age_group,
country_id, country_name, country_probability, created_at
```

---

#### GET /api/profiles/:id — Any role

Returns a single profile by UUID.

Response (200):
```json
{
  "status": "success",
  "data": { "id": "...", "name": "...", ... }
}
```

Response (404):
```json
{"status": "error", "message": "Profile not found"}
```

---

#### DELETE /api/profiles/:id — Admin only

Deletes a profile. Returns 204 No Content with empty body.

---

## Filtering & Sorting

### Available Filters

| Parameter | Type | Description | Example |
|---|---|---|---|
| `gender` | string | Filter by gender | `gender=male` |
| `age_group` | string | Filter by age group | `age_group=adult` |
| `country_id` | string | ISO 2-letter country code | `country_id=NG` |
| `min_age` | integer | Minimum age (inclusive) | `min_age=25` |
| `max_age` | integer | Maximum age (inclusive) | `max_age=40` |
| `min_gender_probability` | float | Minimum gender confidence | `min_gender_probability=0.8` |
| `min_country_probability` | float | Minimum country confidence | `min_country_probability=0.5` |

### Sorting

| Parameter | Values | Description |
|---|---|---|
| `sort_by` | `age`, `created_at`, `gender_probability` | Field to sort by |
| `order` | `asc`, `desc` | Sort direction (default: `asc`) |

### Combined Example

```
GET /api/profiles?gender=male&country_id=NG&min_age=25&max_age=45&sort_by=age&order=desc&page=1&limit=20
```

---

## Pagination

All list endpoints return this structure:

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "total_pages": 203,
  "links": {
    "self": "/api/profiles?page=1&limit=10",
    "next": "/api/profiles?page=2&limit=10",
    "prev": null
  },
  "data": [ ... ]
}
```

- Default page: `1`
- Default limit: `10`
- Maximum limit: `50`
- `prev` is `null` on page 1
- `next` is `null` on the last page

---

## Natural Language Search

**Endpoint:** `GET /api/profiles/search?q=your query here`

### How It Works

The parser is entirely **rule-based** — no AI, no external APIs, no LLMs.
It processes the query string using pattern matching and keyword dictionaries.

**Step by step:**
1. Lowercase and tokenize the query
2. Scan for gender keywords
3. Scan for age group keywords
4. Scan for age comparisons (`above`, `over`, `under`, `between`)
5. Check for the word `young` → maps to ages 16–24
6. Match country names against a 30+ country dictionary → ISO code

### Example Mappings

| Query | Filters Applied |
|---|---|
| `young males from nigeria` | gender=male, min_age=16, max_age=24, country_id=NG |
| `females above 30` | gender=female, min_age=30 |
| `adult males from kenya` | gender=male, age_group=adult, country_id=KE |
| `seniors from south africa` | age_group=senior, country_id=ZA |
| `male and female teenagers above 17` | age_group=teenager, min_age=17 |
| `women under 25` | gender=female, max_age=25 |
| `people from angola` | country_id=AO |
| `children from ghana` | age_group=child, country_id=GH |

### Uninterpretable Queries

If the parser cannot extract any filters from the query:

```json
{"status": "error", "message": "Unable to interpret query"}
```

---

## Rate Limiting & Logging

### Rate Limits

| Scope | Limit | Exceeded Response |
|---|---|---|
| `/auth/*` endpoints | 10 requests / minute | 429 Too Many Requests |
| All other endpoints | 60 requests / minute per user | 429 Too Many Requests |

### Request Logging

Every request is logged automatically:

```
2026-04-28 10:00:01 | INFO | GET /api/profiles → 200 (43ms)
2026-04-28 10:00:02 | INFO | POST /api/profiles → 201 (312ms)
2026-04-28 10:00:03 | INFO | GET /api/profiles/abc → 404 (11ms)
```

Logged fields: method, path, status code, response time in milliseconds.

---

## Database Schema

### profiles

| Column | Type | Notes |
|---|---|---|
| id | VARCHAR | UUID v7, primary key |
| name | VARCHAR | Unique, lowercase |
| gender | VARCHAR | `male` or `female` |
| gender_probability | FLOAT | 0.0 to 1.0 |
| age | INTEGER | |
| age_group | VARCHAR | `child`, `teenager`, `adult`, `senior` |
| country_id | VARCHAR(2) | ISO 2-letter code |
| country_name | VARCHAR | Full country name |
| country_probability | FLOAT | 0.0 to 1.0 |
| created_at | TIMESTAMP | UTC |

### users

| Column | Type | Notes |
|---|---|---|
| id | VARCHAR | UUID v7, primary key |
| github_id | VARCHAR | Unique — GitHub's user ID |
| username | VARCHAR | GitHub username |
| email | VARCHAR | Primary verified email |
| avatar_url | VARCHAR | GitHub profile picture URL |
| role | VARCHAR | `admin` or `analyst` |
| is_active | BOOLEAN | `false` = account disabled (403) |
| last_login_at | TIMESTAMP | Updated on every login |
| created_at | TIMESTAMP | UTC |

### refresh_tokens

| Column | Type | Notes |
|---|---|---|
| id | VARCHAR | UUID v7, primary key |
| token | VARCHAR | Unique JWT string |
| user_id | VARCHAR | References users.id |
| expires_at | TIMESTAMP | UTC |
| is_used | BOOLEAN | `true` = invalidated, cannot be reused |
| created_at | TIMESTAMP | UTC |

---

## Project Structure

```
profile-intelligence-service/
│
├── app/
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py           # OAuth, login, logout, refresh, /me
│   │   └── profiles.py       # All profile endpoints
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── enrichment.py     # Calls Genderize, Agify, Nationalize
│   │   └── nlp_parser.py     # Rule-based natural language parser
│   │
│   ├── __init__.py
│   ├── auth.py               # JWT creation, verification, UUID generation
│   ├── database.py           # SQLAlchemy engine, session, init_db
│   ├── dependencies.py       # Auth guards: get_current_user, require_admin
│   ├── main.py               # App setup, middleware, CORS, routers
│   ├── models.py             # SQLAlchemy table definitions
│   └── schemas.py            # Pydantic request/response models
│
├── seed.py                   # Seeds database with 2026 profiles
├── seed_profiles.json        # Profile dataset (2026 entries)
├── requirements.txt          # All Python dependencies
├── .env.example              # Template for environment variables
├── .gitignore
└── README.md
```

---

## Local Setup

### Prerequisites

- Python 3.11 or 3.12
- A Neon.tech PostgreSQL database
- A GitHub OAuth App

### 1. Clone the repository

```bash
git clone https://github.com/samstar001/profile-intelligence-service.git
cd profile-intelligence-service
```

### 2. Create virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
# Open .env and fill in your values
```

### 5. Seed the database

```bash
python seed.py
# Output: Seeding complete: 2026 inserted, 0 skipped
```

### 6. Start the server

```bash
uvicorn app.main:app --reload
# Server running at http://localhost:8000
```

### 7. Test the login flow

Open in browser:
```
http://localhost:8000/auth/github?source=cli
```

Copy the `access_token` from the response for use in API calls.

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@host/dbname?ssl=require

# GitHub OAuth App
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
GITHUB_REDIRECT_URI=http://localhost:8000/auth/github/callback

# JWT
JWT_SECRET_KEY=your_random_secret_key_at_least_32_chars
JWT_ALGORITHM=HS256

# Token expiry in minutes
ACCESS_TOKEN_EXPIRE_MINUTES=3
REFRESH_TOKEN_EXPIRE_MINUTES=5

# Frontend URL (for web portal cookie redirect)
FRONTEND_URL=http://localhost:5173
```

### Generating a secure JWT_SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Deployment

### Backend — Vercel


## Error Responses

All errors follow this consistent structure:

```json
{"status": "error", "message": "<description>"}
```

| Status Code | Meaning |
|---|---|
| 400 | Bad request — missing parameter or wrong API version header |
| 401 | Unauthorized — invalid or expired token |
| 403 | Forbidden — wrong role or inactive account |
| 404 | Not found — profile or resource does not exist |
| 422 | Unprocessable — wrong data type in request |
| 429 | Too many requests — rate limit exceeded |
| 500 | Internal server error |
| 502 | Bad gateway — external API failed |

---

## Commit Convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description
```

### Types

| Type | When to use |
|---|---|
| `feat` | New feature added |
| `fix` | Bug fixed |
| `docs` | Documentation changes |
| `chore` | Config, dependencies, setup |
| `refactor` | Code restructured without behavior change |
| `test` | Tests added or updated |

### Examples from this project

```
feat(auth): add github oauth with pkce and jwt token issuance
feat(profiles): add advanced filtering, sorting, and pagination
feat(search): add rule-based natural language query parser
feat(export): add csv export endpoint with filter support
feat(middleware): add api version enforcement and request logging
fix(auth): handle missing primary email from github api
chore(db): add users and refresh_tokens tables to models
docs(readme): add full system documentation for stage 3
```

---

## External APIs Used

| API | URL | Data Extracted |
|---|---|---|
| Genderize.io | `https://api.genderize.io?name={name}` | gender, probability, count (→ sample_size) |
| Agify.io | `https://api.agify.io?name={name}` | age (→ age_group computed) |
| Nationalize.io | `https://api.nationalize.io?name={name}` | top country by probability |

All three APIs are free and require no API key.

---

## Stage History

| Stage | What was built |
|---|---|
| Stage 1 | Data collection from 3 external APIs, basic CRUD, PostgreSQL storage |
| Stage 2 | Advanced filtering, sorting, pagination, natural language search, 2026 profile seed |
| Stage 3 | GitHub OAuth + PKCE, JWT tokens, RBAC, rate limiting, logging, CSV export, API versioning |
