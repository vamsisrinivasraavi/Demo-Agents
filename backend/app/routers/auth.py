"""
Auth router — public endpoints for registration, login, token refresh.

All endpoints are unauthenticated except /me (requires valid JWT).
Services are constructed per-request via dependency injection.
"""

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import (
    get_current_user,
    get_mongo_db,
    require_role,
)
from app.core.security import TokenPayload, UserRole
from app.repositories.user_repo import UserRepository
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()


# ──────────────────────────────────────────────
# Dependency: build AuthService per request
# ──────────────────────────────────────────────


async def _get_auth_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
) -> AuthService:
    return AuthService(user_repo=UserRepository(db))


# ──────────────────────────────────────────────
# Public Endpoints
# ──────────────────────────────────────────────


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    summary="Register a new user account",
)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(_get_auth_service),
):
    """
    Create a new user account.
    Default role is 'user'. Only existing admins can create admin accounts.
    """
    return await auth_service.register(request, created_by_role=None)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login with email and password",
)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(_get_auth_service),
):
    """
    Authenticate and receive a JWT token pair.
    Returns access token (short-lived) + refresh token (long-lived).
    """
    return await auth_service.login(request)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    request: RefreshTokenRequest,
    auth_service: AuthService = Depends(_get_auth_service),
):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    return await auth_service.refresh_token(request.refresh_token)


# ──────────────────────────────────────────────
# Authenticated Endpoints
# ──────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_profile(
    current_user: TokenPayload = Depends(get_current_user),
    auth_service: AuthService = Depends(_get_auth_service),
):
    """Fetch the profile of the currently authenticated user."""
    return await auth_service.get_user_profile(current_user.sub)


# ──────────────────────────────────────────────
# Admin-only: Register admin accounts
# ──────────────────────────────────────────────


@router.post(
    "/register/admin",
    response_model=AuthResponse,
    status_code=201,
    summary="Register an admin account (admin only)",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def register_admin(
    request: RegisterRequest,
    current_user: TokenPayload = Depends(get_current_user),
    auth_service: AuthService = Depends(_get_auth_service),
):
    """Create a new admin account. Requires admin JWT."""
    request.role = UserRole.ADMIN
    return await auth_service.register(request, created_by_role=current_user.role)