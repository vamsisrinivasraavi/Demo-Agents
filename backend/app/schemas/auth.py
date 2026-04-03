"""
Auth request/response schemas.

Separation from models:
- Models = what's stored in MongoDB
- Schemas = what the API accepts/returns (may omit sensitive fields, reshape data)
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.security import UserRole


# ──────────────────────────────────────────────
# Requests
# ──────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field("", max_length=100)
    role: UserRole = UserRole.USER  # Only admins can create admin accounts


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ──────────────────────────────────────────────
# Responses
# ──────────────────────────────────────────────


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    """Safe user representation — never exposes password hash."""

    id: str
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class AuthResponse(BaseModel):
    """Combined login response: tokens + user profile."""

    tokens: TokenResponse
    user: UserResponse