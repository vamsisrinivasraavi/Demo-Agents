"""
Workflow repository — manages the workflows collection.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.base import BaseRepository


class WorkflowRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "workflows")

    async def create_workflow(self, workflow_data: dict) -> str:
        """Create a new workflow."""
        return await self.insert_one(workflow_data)

    async def find_by_user(
        self,
        user_id: str,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List workflows created by a user."""
        query: dict = {"created_by": user_id}
        if active_only:
            query["is_active"] = True
        return await self.find_many(
            query, skip=skip, limit=limit, sort=[("created_at", -1)]
        )

    async def count_by_user(self, user_id: str, active_only: bool = True) -> int:
        query: dict = {"created_by": user_id}
        if active_only:
            query["is_active"] = True
        return await self.count(query)

    async def find_active_workflows(
        self,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List all active workflows (for user-facing listing)."""
        return await self.find_many(
            {"is_active": True},
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)],
        )

    async def count_active(self) -> int:
        return await self.count({"is_active": True})

    async def partial_update(self, workflow_id: str, updates: dict) -> bool:
        """
        Apply a partial update — only provided fields are overwritten.
        Nested dicts (agents, model_settings, feature_flags) are replaced
        at the top level of each key, not deep-merged.
        """
        # Filter out None values so only explicitly set fields are updated
        clean = {k: v for k, v in updates.items() if v is not None}
        if not clean:
            return False
        return await self.update_one(workflow_id, clean)

    async def find_by_ingestion_config(self, config_id: str) -> list[dict]:
        """Find all workflows tied to a specific ingestion config."""
        return await self.find_many({"ingestion_config_id": config_id})