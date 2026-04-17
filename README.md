# Profile Intelligence Service

A REST API that enriches names with demographic data using Genderize, Agify, and Nationalize APIs.

## Tech Stack
- Python 3.12
- FastAPI
- PostgreSQL (Neon)
- SQLAlchemy (async)

## Endpoints

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