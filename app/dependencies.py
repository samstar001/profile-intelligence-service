# dependencies.py — FastAPI Dependencies
#
# This file provides reusable dependency functions that FastAPI
# injects into route handlers automatically.
#
# Key change from Stage 2:
# get_current_user now reads token from EITHER:
#   - Authorization: Bearer <token> header (CLI)
#   - access_token HTTP-only cookie (Web portal)

from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models import User
from app.auth import verify_access_token


# ─── Get Current User ─────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Extracts and validates the auth token from the request.

    Checks two places in this order:
    1. Authorization: Bearer <token> header  ← used by CLI
    2. access_token HTTP-only cookie         ← used by web portal

    Returns the User object if token is valid.
    Raises 403 if no token found at all.
    Raises 401 if token is invalid or expired.
    Raises 403 if user account is disabled.

    Usage in any route:
        async def my_endpoint(
            current_user: User = Depends(get_current_user)
        ):
    """

    token = None

    # ── Try Authorization header first (CLI uses this) ─────────────────────
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        # "Bearer eyJhbGci..." → split on space, take second part → "eyJhbGci..."

    # ── Fall back to HTTP-only cookie (web portal uses this) ───────────────
    if not token:
        token = request.cookies.get("access_token")
        # Browser automatically sends cookies with every request
        # JavaScript cannot read httponly cookies (security feature)

    # ── No token found at all ──────────────────────────────────────────────
    if not token:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "message": "Not authenticated"}
        )

    # ── Verify the JWT signature and expiry ────────────────────────────────
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid or expired token"}
        )

    # ── Look up user in database ───────────────────────────────────────────
    user_id = payload.get("sub")
    # "sub" = subject = the user's ID stored inside the JWT

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "User not found"}
        )

    # ── Check account is active ────────────────────────────────────────────
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "message": "Account is disabled"}
        )

    return user


# ─── Role-Based Access Control ────────────────────────────────────────────────

def require_role(*roles: str):
    """
    Factory function that returns a dependency requiring specific roles.

    Examples:
        Depends(require_role("admin"))            # admin only
        Depends(require_role("admin", "analyst")) # either role

    Usage:
        async def create_profile(
            current_user: User = Depends(require_role("admin"))
        ):
    """
    async def role_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "status": "error",
                    "message": f"Access denied. Required role: {' or '.join(roles)}"
                }
            )
        return current_user
    return role_checker


# ─── Convenience Shortcuts ────────────────────────────────────────────────────

require_admin = require_role("admin")
# Use as: current_user: User = Depends(require_admin)
# Only allows users with role = "admin"

require_any_role = require_role("admin", "analyst")
# Use as: current_user: User = Depends(require_any_role)
# Allows both admin and analyst roles