"""
Tests for /api/auth/* endpoints.

Covers:
- Registration (success, duplicate email, validation)
- Login (success, wrong password, nonexistent user)
- Token refresh (success, invalid token)
- Profile retrieval (authenticated, unauthenticated)
"""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    USER_EMAIL,
    USER_PASSWORD,
    auth_header,
)


# ══════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient):
    """Register a new user account."""
    resp = await client.post("/api/auth/register", json={
        "email": "new_user@test.com",
        "password": "secure_password_123",
        "display_name": "New User",
        "role": "user",
    })
    assert resp.status_code == 201

    data = resp.json()
    assert "tokens" in data
    assert "user" in data
    assert data["tokens"]["token_type"] == "bearer"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]
    assert data["tokens"]["expires_in"] > 0
    assert data["user"]["email"] == "new_user@test.com"
    assert data["user"]["role"] == "user"
    assert data["user"]["is_active"] is True


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Registering with an existing email should fail."""
    payload = {
        "email": "dupe@test.com",
        "password": "password_123",
        "role": "user",
    }
    resp1 = await client.post("/api/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/auth/register", json=payload)
    assert resp2.status_code == 409
    assert "already registered" in resp2.json()["error"]["message"]


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    """Password shorter than 8 chars should be rejected."""
    resp = await client.post("/api/auth/register", json={
        "email": "short@test.com",
        "password": "123",
        "role": "user",
    })
    assert resp.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Invalid email format should be rejected."""
    resp = await client.post("/api/auth/register", json={
        "email": "not-an-email",
        "password": "password_123",
        "role": "user",
    })
    assert resp.status_code == 422


# ══════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Login with valid credentials."""
    # Register first
    await client.post("/api/auth/register", json={
        "email": "login_test@test.com",
        "password": "password_123",
        "role": "user",
    })

    resp = await client.post("/api/auth/login", json={
        "email": "login_test@test.com",
        "password": "password_123",
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["tokens"]["access_token"]
    assert data["user"]["email"] == "login_test@test.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Login with wrong password should fail."""
    await client.post("/api/auth/register", json={
        "email": "wrong_pw@test.com",
        "password": "correct_password",
        "role": "user",
    })

    resp = await client.post("/api/auth/login", json={
        "email": "wrong_pw@test.com",
        "password": "wrong_password",
    })
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Login with unregistered email should fail."""
    resp = await client.post("/api/auth/login", json={
        "email": "ghost@test.com",
        "password": "password_123",
    })
    assert resp.status_code == 401


# ══════════════════════════════════════════════
# TOKEN REFRESH
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient):
    """Exchange valid refresh token for new token pair."""
    reg_resp = await client.post("/api/auth/register", json={
        "email": "refresh@test.com",
        "password": "password_123",
        "role": "user",
    })
    refresh_token = reg_resp.json()["tokens"]["refresh_token"]

    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    assert resp.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient):
    """Invalid refresh token should be rejected."""
    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": "invalid.jwt.token",
    })
    assert resp.status_code == 401


# ══════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_profile_authenticated(client: AsyncClient):
    """Authenticated user can fetch their profile."""
    reg = await client.post("/api/auth/register", json={
        "email": "profile@test.com",
        "password": "password_123",
        "display_name": "Profile User",
        "role": "user",
    })
    token = reg.json()["tokens"]["access_token"]

    resp = await client.get("/api/auth/me", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "profile@test.com"
    assert resp.json()["display_name"] == "Profile User"


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client: AsyncClient):
    """Unauthenticated request should be rejected."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_profile_invalid_token(client: AsyncClient):
    """Invalid JWT should be rejected."""
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401