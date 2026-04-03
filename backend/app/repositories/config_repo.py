"""
Ingestion config repository — manages the ingestion_configs collection.
Handles status lifecycle: PENDING → RUNNING → COMPLETED / FAILED.
"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.ingestion_config import IngestionStatus
from app.repositories.base import BaseRepository


class IngestionConfigRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "ingestion_configs")

    async def create_config(self, config_data: dict) -> str:
        """Create a new ingestion config in PENDING state."""
        config_data["status"] = IngestionStatus.PENDING
        return await self.insert_one(config_data)

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List all configs created by a specific user."""
        return await self.find_many(
            {"created_by": user_id},
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)],
        )

    async def count_by_user(self, user_id: str) -> int:
        """Count configs for a user."""
        return await self.count({"created_by": user_id})

    async def set_status(
        self,
        config_id: str,
        status: IngestionStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """Transition the ingestion status."""
        update: dict = {"status": status}
        if error_message is not None:
            update["error_message"] = error_message
        return await self.update_one(config_id, update)

    async def set_running(self, config_id: str) -> bool:
        return await self.set_status(config_id, IngestionStatus.RUNNING)

    async def set_completed(self, config_id: str, schema_stats: dict) -> bool:
        """Mark completed and store schema statistics."""
        update = {
            "status": IngestionStatus.COMPLETED,
            "schema_stats": schema_stats,
            "error_message": None,
        }
        return await self.update_one(config_id, update)

    async def set_failed(self, config_id: str, error: str) -> bool:
        return await self.set_status(config_id, IngestionStatus.FAILED, error)

    async def find_by_collection_name(self, collection_name: str) -> Optional[dict]:
        """Find config by its Qdrant collection name."""
        return await self.find_one({"qdrant_collection": collection_name})