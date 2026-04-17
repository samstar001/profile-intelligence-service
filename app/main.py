from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.database import init_db
from app.routes import profiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Profile Intelligence Service",
    version="1.0.0",
    lifespan=lifespan
)

# ── CORS — required for grading script ────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Custom error response shapes ───────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid request data"}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )


# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(profiles.router, prefix="/api")


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "success",
        "message": "Profile Intelligence Service is running"
    }