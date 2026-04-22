from sqlalchemy import Column, String, Float, Integer, DateTime
from app.database import Base


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    gender = Column(String, nullable=False)
    gender_probability = Column(Float, nullable=False)
    age = Column(Integer, nullable=False)
    age_group = Column(String, nullable=False)
    country_id = Column(String(2), nullable=False)
    country_name = Column(String, nullable=False)        # ← NEW FIELD
    country_probability = Column(Float, nullable=False)
    sample_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)