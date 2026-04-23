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
| POST | /api/profiles | Create a new profile |
| GET | /api/profiles | List all profiles (filterable) |
| GET | /api/profiles/{id} | Get profile by ID |
| DELETE | /api/profiles/{id} | Delete a profile |

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload
```

API docs available at: http://localhost:8000/docs

## Live URL
https://your-app.vercel.app