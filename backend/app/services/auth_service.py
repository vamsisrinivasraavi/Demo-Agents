"""
Authentication service.

Handles:
- User registration (with duplicate email check)
- Login (email + password → JWT token pair)
- Token refresh (refresh token → new access token)
- Admin-only: can create admin accounts

All password operations use bcrypt. Tokens are stateless JWTs.
"""

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.core.security import (
    TokenPair,
    UserRole,
    create_token_pair,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import UserDocument
from app.repositories.user_repo import UserRepository
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = get_logger(__name__)


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    async def register(
        self,
        request: RegisterRequest,
        created_by_role: UserRole | None = None,
    ) -> AuthResponse:
        """
        Register a new user.

        Rules:
        - Only admins can create admin accounts (via /register/admin)
        - EXCEPTION: if zero admins exist, the first admin can self-register
          via the public /register endpoint (bootstrap mode)
        - Duplicate emails are rejected
        - Password is hashed before storage
        """
        # Admin creation guard — with first-admin bootstrap
        if request.role == UserRole.ADMIN and created_by_role != UserRole.ADMIN:
            # Check if ANY admin exists in the system
            admin_exists = await self._user_repo.find_one_by_role(UserRole.ADMIN)
            if admin_exists:
                raise AuthenticationError(
                    detail="Only admins can create admin accounts. "
                    "Use POST /api/auth/register/admin with an admin JWT."
                )
            # No admins exist → allow bootstrap
            logger.info("auth.bootstrap_admin", email=request.email)

        # Check duplicate email
        if await self._user_repo.email_exists(request.email):
            raise ConflictError(detail=f"Email '{request.email}' is already registered")

        # Build user document
        user_doc = UserDocument(
            email=request.email,
            hashed_password=hash_password(request.password),
            display_name=request.display_name or request.email.split("@")[0],
            role=request.role,
        )

        user_id = await self._user_repo.create_user(user_doc.to_mongo())
        await self._user_repo.update_last_login(user_id)

        logger.info("auth.registered", user_id=user_id, role=request.role)

        # Generate tokens
        tokens = create_token_pair(user_id, request.role)

        return AuthResponse(
            tokens=TokenResponse(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_in=tokens.expires_in,
            ),
            user=UserResponse(
                id=user_id,
                email=request.email,
                display_name=user_doc.display_name,
                role=request.role,
                is_active=True,
                created_at=user_doc.created_at,
            ),
        )

    async def login(self, request: LoginRequest) -> AuthResponse:
        """
        Authenticate user with email + password.
        Returns JWT token pair + user profile.
        """
        user = await self._user_repo.find_by_email(request.email)
        if user is None:
            raise AuthenticationError(detail="Invalid email or password")

        if not user.get("is_active", True):
            raise AuthenticationError(detail="Account is deactivated")

        if not verify_password(request.password, user["hashed_password"]):
            raise AuthenticationError(detail="Invalid email or password")

        user_id = user["_id"]
        role = UserRole(user["role"])

        await self._user_repo.update_last_login(user_id)

        tokens = create_token_pair(user_id, role)

        logger.info("auth.login", user_id=user_id, role=role)

        return AuthResponse(
            tokens=TokenResponse(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_in=tokens.expires_in,
            ),
            user=UserResponse(
                id=user_id,
                email=user["email"],
                display_name=user.get("display_name", ""),
                role=role,
                is_active=user.get("is_active", True),
                created_at=user["created_at"],
                last_login_at=user.get("last_login_at"),
            ),
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Exchange a valid refresh token for a new access token.
        The refresh token itself is NOT rotated (stateless model).
        """
        payload = decode_refresh_token(refresh_token)
        if payload is None:
            raise AuthenticationError(detail="Invalid or expired refresh token")

        # Verify user still exists and is active
        user = await self._user_repo.find_by_id(payload.sub)
        if user is None or not user.get("is_active", True):
            raise AuthenticationError(detail="User no longer active")

        tokens = create_token_pair(payload.sub, payload.role)

        logger.info("auth.token_refreshed", user_id=payload.sub)

        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )

    async def get_user_profile(self, user_id: str) -> UserResponse:
        """Fetch user profile by ID."""
        user = await self._user_repo.find_by_id(user_id)
        if user is None:
            raise NotFoundError(detail="User not found")

        return UserResponse(
            id=user["_id"],
            email=user["email"],
            display_name=user.get("display_name", ""),
            role=UserRole(user["role"]),
            is_active=user.get("is_active", True),
            created_at=user["created_at"],
            last_login_at=user.get("last_login_at"),
        )