import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
from dotenv import load_dotenv

from app.database import init_db
from app.routes.profiles import router as profiles_router
from app.routes.auth import router as auth_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Profile Intelligence Service",
    version="3.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Runs on every request.
    1. Checks X-API-Version header on all /api/* routes FIRST (before auth)
    2. Logs method, path, status code, response time
    """
    start_time = time.time()

    # API Version check runs BEFORE auth so it always returns 400 first
    if request.url.path.startswith("/api/"):
        api_version = request.headers.get("x-api-version")
        if not api_version or api_version.strip() != "1":
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "API version header required"
                }
            )

    response = await call_next(request)
    duration = round((time.time() - start_time) * 1000, 2)

    logger.info(
        f"{request.method} {request.url.path} "
        f"→ {response.status_code} ({duration}ms)"
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid query parameters"}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )


app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(profiles_router, prefix="/api", tags=["Profiles"])


@app.get("/")
async def root():
    return {
        "status": "success",
        "message": "Profile Intelligence Service v3.0 is running"
    }