"""
Seed the first admin user.

Run once during initial setup:
    python -m app.seed_admin

Or with custom credentials:
    python -m app.seed_admin --email admin@company.com --password MySecurePass123

This bypasses the API auth check entirely — it writes directly to MongoDB.
Only use for initial bootstrapping.
"""

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.security import hash_password, UserRole, create_token_pair


async def seed_admin(email: str, password: str, display_name: str) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient

    settings = get_settings()

    # Connect to MongoDB
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    # Check if admin already exists
    existing = await db.users.find_one({"email": email.lower()})
    if existing:
        return

    # Check if ANY admin exists
    any_admin = await db.users.find_one({"role": "admin"})
    if any_admin:
        return

    # Create admin user
    from datetime import datetime, timezone

    user_doc = {
        "email": email.lower().strip(),
        "hashed_password": hash_password(password),
        "display_name": display_name,
        "role": UserRole.ADMIN,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    # Generate tokens for immediate use
    tokens = create_token_pair(user_id, UserRole.ADMIN)

    print()
    print("═" * 50)
    print("  ✓ Admin user created successfully")
    print("═" * 50)
    print(f"  Email:    {email}")
    print(f"  User ID:  {user_id}")
    print(f"  Role:     admin")
    print()
    print("  Access Token (use in Authorization header):")
    print(f"  Bearer {tokens.access_token}")
    print()
    print("  You can also login via POST /api/auth/login")
    print("═" * 50)

    # Ensure email index exists
    await db.users.create_index("email", unique=True)

    client.close()