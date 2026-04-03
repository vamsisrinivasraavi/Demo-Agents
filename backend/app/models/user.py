"""
User document model.

Stored in MongoDB 'users' collection.
Handles both admin and regular user accounts.
Password is always stored as a bcrypt hash — never plaintext.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.security import UserRole


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserDocument(BaseModel):
    """
    MongoDB document schema for users.

    _id is managed by MongoDB (ObjectId).  We store it as `id` (str)
    after insertion for convenience in the app layer.
    """

    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId as string")
    email: EmailStr
    hashed_password: str
    display_name: str = ""
    role: UserRole = UserRole.USER
    is_active: bool = True

    # Audit
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_login_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_mongo(self) -> dict:
        """Convert to MongoDB-insertable dict, excluding None id."""
        data = self.model_dump(by_alias=False, exclude={"id"})
        data["updated_at"] = _utc_now()
        return data