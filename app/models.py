from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean
from app.database import Base


# ─── Profile Table (unchanged from Stage 2) ───────────────────────────────────
class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    gender = Column(String, nullable=False)
    gender_probability = Column(Float, nullable=False)
    age = Column(Integer, nullable=False)
    age_group = Column(String, nullable=False)
    country_id = Column(String(2), nullable=False)
    country_name = Column(String, nullable=False)
    country_probability = Column(Float, nullable=False)
    sample_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)


# ─── User Table (NEW in Stage 3) ──────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    # UUID v7 — same format as profile IDs

    github_id = Column(String, unique=True, nullable=False, index=True)
    # GitHub's unique ID for this user
    # Used to find existing users on login (same person logging in again)

    username = Column(String, nullable=False)
    # GitHub username e.g. "samstar001"

    email = Column(String, nullable=True)
    # GitHub email — can be null if user has private email on GitHub

    avatar_url = Column(String, nullable=True)
    # URL to their GitHub profile picture

    role = Column(String, nullable=False, default="analyst")
    # "admin" — can create and delete profiles
    # "analyst" — read-only access (default for all new users)

    is_active = Column(Boolean, nullable=False, default=True)
    # If False — user is banned/disabled
    # All requests from inactive users return 403 Forbidden

    last_login_at = Column(DateTime, nullable=True)
    # Updated every time the user logs in successfully

    created_at = Column(DateTime, nullable=False)
    # When the user account was first created


# ─── Refresh Token Table (NEW in Stage 3) ─────────────────────────────────────
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, index=True)
    # UUID v7

    token = Column(String, unique=True, nullable=False, index=True)
    # The actual refresh token string (stored hashed ideally, stored plain here for simplicity)

    user_id = Column(String, nullable=False, index=True)
    # Which user this token belongs to

    expires_at = Column(DateTime, nullable=False)
    # When this token expires

    is_used = Column(Boolean, nullable=False, default=False)
    # True = token has been used (invalidated)
    # Each refresh token can only be used ONCE

    created_at = Column(DateTime, nullable=False)