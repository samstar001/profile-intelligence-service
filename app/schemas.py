from pydantic import BaseModel, field_serializer
from datetime import datetime
from typing import Optional, List


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


class PaginatedProfileResponse(BaseModel):
    status: str
    page: int
    limit: int
    total: int
    data: List[ProfileListItem]