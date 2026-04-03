"""
Security utilities: JWT management, password hashing, role enforcement.

Design choices:
- bcrypt for password hashing (industry standard, resistant to GPU attacks)
- Separate access + refresh tokens with distinct expiry
- Role claim embedded in JWT payload for stateless RBAC
- Token blacklisting can be added via Redis if needed
"""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


# ──────────────────────────────────────────────
# Token Schema
# ──────────────────────────────────────────────


class TokenPayload(BaseModel):
    """Decoded JWT payload structure."""

    sub: str  # user_id
    role: UserRole
    exp: datetime
    token_type: str = "access"  # access | refresh


class TokenPair(BaseModel):
    """Issued token pair returned on login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry


# ──────────────────────────────────────────────
# Password Hashing
# ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (12 rounds)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ──────────────────────────────────────────────
# JWT Creation
# ──────────────────────────────────────────────


def create_access_token(user_id: str, role: UserRole) -> str:
    """Create a short-lived access token with user ID and role."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "token_type": "access",
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, role: UserRole) -> str:
    """Create a long-lived refresh token."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "token_type": "refresh",
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_token_pair(user_id: str, role: UserRole) -> TokenPair:
    """Generate both access and refresh tokens."""
    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(user_id, role),
        refresh_token=create_refresh_token(user_id, role),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ──────────────────────────────────────────────
# JWT Decoding / Verification
# ──────────────────────────────────────────────


def decode_token(token: str) -> Optional[TokenPayload]:
    """
    Decode and validate a JWT token.
    Returns TokenPayload on success, None on failure.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return TokenPayload(**payload)
    except JWTError:
        return None


def decode_access_token(token: str) -> Optional[TokenPayload]:
    """Decode a token and verify it's an access token."""
    payload = decode_token(token)
    if payload is None or payload.token_type != "access":
        return None
    return payload


def decode_refresh_token(token: str) -> Optional[TokenPayload]:
    """Decode a token and verify it's a refresh token."""
    payload = decode_token(token)
    if payload is None or payload.token_type != "refresh":
        return None
    return payload