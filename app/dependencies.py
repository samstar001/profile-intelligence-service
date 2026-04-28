from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models import User
from app.auth import verify_access_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid or expired token"}
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "User not found"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "message": "Account is disabled"}
        )

    return user


def require_role(*roles: str):
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


require_admin = require_role("admin")
require_any_role = require_role("admin", "analyst")


async def require_api_version(
    x_api_version: Optional[str] = Header(default=None)
):
    if x_api_version is None or x_api_version.strip() != "1":
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "API version header required"
            }
        )