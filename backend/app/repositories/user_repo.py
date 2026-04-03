"""
User repository — async MongoDB operations for the users collection.
"""

from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "users")

    async def find_by_email(self, email: str) -> Optional[dict]:
        """Lookup user by email (case-insensitive)."""
        return await self.find_one({"email": email.lower().strip()})

    async def create_user(self, user_data: dict) -> str:
        """Insert a new user. Email is lowercased before storage."""
        user_data["email"] = user_data["email"].lower().strip()
        return await self.insert_one(user_data)

    async def update_last_login(self, user_id: str) -> bool:
        """Stamp the last login time."""
        return await self.update_one(
            user_id,
            {"last_login_at": datetime.now(timezone.utc)},
        )

    async def deactivate_user(self, user_id: str) -> bool:
        """Soft-delete by setting is_active = False."""
        return await self.update_one(user_id, {"is_active": False})

    async def email_exists(self, email: str) -> bool:
        """Check if an email is already registered."""
        doc = await self.find_one({"email": email.lower().strip()})
        return doc is not None

    async def find_one_by_role(self, role: str) -> Optional[dict]:
        """Check if any user with the given role exists."""
        return await self.find_one({"role": role})