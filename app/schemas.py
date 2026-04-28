from pydantic import BaseModel, field_serializer
from datetime import datetime
from typing import Optional, List


# ─── Profile Schemas (Stage 1 & 2 — unchanged) ────────────────────────────────

class ProfileCreate(BaseModel):
    name: Optional[str] = None


class ProfileData(BaseModel):
    id: str
    name: str
    gender: str
    gender_probability: float
    sample_size: Optional[int] = None
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    model_config = {"from_attributes": True}


class ProfileListItem(BaseModel):
    id: str
    name: str
    gender: str
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    gender_probability: float
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    model_config = {"from_attributes": True}


# ─── Pagination Links Schema (NEW in Stage 3) ─────────────────────────────────

class PaginationLinks(BaseModel):
    self: str
    # URL of the current page

    next: Optional[str] = None
    # URL of the next page — None if on the last page

    prev: Optional[str] = None
    # URL of the previous page — None if on the first page


class PaginatedProfileResponse(BaseModel):
    status: str
    page: int
    limit: int
    total: int
    total_pages: int
    # NEW: total number of pages = ceil(total / limit)
    links: PaginationLinks
    # NEW: navigation links for the client
    data: List[ProfileListItem]


# ─── User Schemas (NEW in Stage 3) ────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    github_id: str
    username: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    @field_serializer("last_login_at")
    def serialize_last_login(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    model_config = {"from_attributes": True}


# ─── Token Schemas (NEW in Stage 3) ───────────────────────────────────────────

class TokenResponse(BaseModel):
    status: str
    access_token: str
    refresh_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str