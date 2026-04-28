import os
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv

from app.database import get_db
from app.models import User, RefreshToken
from app.schemas import RefreshTokenRequest, UserResponse
from app.auth import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    get_token_expiry,
    generate_uuid7,
    REFRESH_TOKEN_EXPIRE_MINUTES,
)
from app.dependencies import get_current_user

load_dotenv()

router = APIRouter()

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


# ─── GET /auth/github ──────────────────────────────────────────────────────────

@router.get("/github")
async def github_login(request: Request):
    """
    Redirects to GitHub OAuth page.
    Encodes 'source' (cli or web) into the state parameter
    so it survives the GitHub redirect back to our callback.
    """
    source = request.query_params.get("source", "web")
    base_state = generate_uuid7()

    # Format: "uuid:source" e.g. "019dce48-5347-7ed3-a1cb-48206ebc98c8:cli"
    state = f"{base_state}:{source}"

    code_challenge = request.query_params.get("code_challenge")
    code_challenge_method = request.query_params.get("code_challenge_method", "S256")

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": "read:user user:email",
        "state": state,
    }

    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = code_challenge_method

    github_url = "https://github.com/login/oauth/authorize"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{github_url}?{query}")


# ─── GET /auth/github/callback ────────────────────────────────────────────────

@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """
    GitHub redirects here after user authorizes.
    1. Extracts source from state
    2. Exchanges code for GitHub access token
    3. Fetches GitHub user info
    4. Creates or updates user in database
    5. Issues access + refresh tokens
    6. Returns JSON (CLI) or sets cookies and redirects (web)
    """

    # ── Extract source from state ──────────────────────────────────────────
    # State format: "uuid:source" e.g. "019dce48-5347-7ed3-a1cb:cli"
    state_parts = state.split(":", 1)
    source = state_parts[1] if len(state_parts) > 1 else "web"

    code_verifier = request.query_params.get("code_verifier")

    # ── Exchange code for GitHub access token ──────────────────────────────
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_data = {
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": GITHUB_REDIRECT_URI,
        }
        if code_verifier:
            token_data["code_verifier"] = code_verifier

        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            data=token_data,
            headers={"Accept": "application/json"}
        )
        token_json = token_res.json()

    github_access_token = token_json.get("access_token")
    if not github_access_token:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Failed to get token from GitHub"}
        )

    # ── Fetch user info from GitHub ────────────────────────────────────────
    async with httpx.AsyncClient(timeout=30.0) as client:
        user_res = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {github_access_token}",
                "Accept": "application/vnd.github+json"
            }
        )
        github_user = user_res.json()

        email_res = await client.get(
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {github_access_token}",
                "Accept": "application/vnd.github+json"
            }
        )
        emails = email_res.json()

    # Get primary verified email
    primary_email = None
    if isinstance(emails, list):
        for e in emails:
            if e.get("primary") and e.get("verified"):
                primary_email = e.get("email")
                break

    github_id = str(github_user.get("id"))
    username = github_user.get("login")
    avatar_url = github_user.get("avatar_url")

    # ── Create or update user in database ─────────────────────────────────
    result = await db.execute(
        select(User).where(User.github_id == github_id)
    )
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if not user:
        # First time login — create new user with analyst role
        user = User(
            id=generate_uuid7(),
            github_id=github_id,
            username=username,
            email=primary_email,
            avatar_url=avatar_url,
            role="analyst",
            is_active=True,
            last_login_at=now,
            created_at=now,
        )
        db.add(user)
    else:
        # Returning user — update their profile info
        user.username = username
        user.email = primary_email or user.email
        user.avatar_url = avatar_url
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)

    # ── Issue access + refresh tokens ──────────────────────────────────────
    access_token = create_access_token(user.id, user.username, user.role)
    refresh_token_str = create_refresh_token(user.id)

    # Save refresh token to database
    refresh_token_record = RefreshToken(
        id=generate_uuid7(),
        token=refresh_token_str,
        user_id=user.id,
        expires_at=get_token_expiry(REFRESH_TOKEN_EXPIRE_MINUTES).replace(tzinfo=None),
        is_used=False,
        created_at=now,
    )
    db.add(refresh_token_record)
    await db.commit()

    # ── Return response based on source ───────────────────────────────────
    if source == "cli":
        # CLI gets tokens as JSON in response body
        return JSONResponse(content={
            "status": "success",
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "username": user.username,
            "role": user.role,
        })

    # Web portal gets tokens as HTTP-only cookies + redirect to dashboard
    response = RedirectResponse(url=f"{FRONTEND_URL}/dashboard")
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,       # Not accessible via JavaScript (security)
        secure=False,        # Set to True in production (HTTPS)
        samesite="lax",      # CSRF protection
        max_age=3 * 60,      # 3 minutes — matches ACCESS_TOKEN_EXPIRE_MINUTES
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=5 * 60,      # 5 minutes — matches REFRESH_TOKEN_EXPIRE_MINUTES
    )
    return response


# ─── POST /auth/refresh ───────────────────────────────────────────────────────

@router.post("/refresh")
async def refresh_token(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Issues new access + refresh tokens using a valid refresh token.
    The old refresh token is immediately invalidated (one-time use only).
    """
    # Verify JWT signature and expiry
    payload = verify_refresh_token(body.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid or expired refresh token"}
        )

    # Check token exists in DB and hasn't been used
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == body.refresh_token,
            RefreshToken.is_used == False
        )
    )
    token_record = result.scalar_one_or_none()

    if not token_record:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Refresh token already used"}
        )

    # Invalidate the old token immediately
    token_record.is_used = True
    await db.commit()

    # Fetch the user
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "User not found or inactive"}
        )

    # Issue brand new token pair
    new_access_token = create_access_token(user.id, user.username, user.role)
    new_refresh_token = create_refresh_token(user.id)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(RefreshToken(
        id=generate_uuid7(),
        token=new_refresh_token,
        user_id=user.id,
        expires_at=get_token_expiry(REFRESH_TOKEN_EXPIRE_MINUTES).replace(tzinfo=None),
        is_used=False,
        created_at=now,
    ))
    await db.commit()

    return {
        "status": "success",
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
    }


# ─── POST /auth/logout ────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Invalidates the refresh token server-side.
    Client should also delete their locally stored tokens after this.
    Always returns 200 even if token not found (safe logout).
    """
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == body.refresh_token)
    )
    token_record = result.scalar_one_or_none()

    if token_record:
        token_record.is_used = True
        await db.commit()

    return JSONResponse(
        status_code=200,
        content={"status": "success", "message": "Logged out successfully"}
    )


# ─── GET /auth/me ─────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the currently authenticated user's profile.
    Used by CLI 'insighta whoami' command and web portal account page.
    Requires a valid Bearer token in Authorization header.
    """
    return {
        "status": "success",
        "data": UserResponse.model_validate(current_user).model_dump(mode="json")
    }