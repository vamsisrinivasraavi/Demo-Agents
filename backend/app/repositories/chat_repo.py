"""
Chat session repository.

Messages are embedded in the session document using MongoDB's $push
operator for atomic appends. This avoids race conditions in concurrent
multi-turn conversations.
"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "chat_sessions")

    async def create_session(self, session_data: dict) -> str:
        """Create a new chat session."""
        session_data.setdefault("messages", [])
        session_data.setdefault("message_count", 0)
        return await self.insert_one(session_data)

    async def append_message(self, session_id: str, message: dict) -> bool:
        """
        Atomically append a message to the session's messages array
        and increment the message counter.

        Uses $push + $inc for atomicity — safe under concurrency.
        """
        return await self.update_one_raw(
            session_id,
            {
                "$push": {"messages": message},
                "$inc": {"message_count": 1},
            },
        )

    async def append_messages(self, session_id: str, messages: list[dict]) -> bool:
        """Append multiple messages at once (user + assistant pair)."""
        return await self.update_one_raw(
            session_id,
            {
                "$push": {"messages": {"$each": messages}},
                "$inc": {"message_count": len(messages)},
            },
        )

    async def find_user_sessions(
        self,
        user_id: str,
        workflow_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """
        List sessions for a user, optionally filtered by workflow.
        Returns lightweight projections (no full message arrays).
        """
        query: dict = {"user_id": user_id}
        if workflow_id:
            query["workflow_id"] = workflow_id

        # Project: exclude the full messages array for listing
        cursor = (
            self._collection.find(
                query,
                {
                    "_id": 1,
                    "workflow_id": 1,
                    "title": 1,
                    "message_count": 1,
                    "is_active": 1,
                    "created_at": 1,
                    "updated_at": 1,
                },
            )
            .sort("updated_at", -1)
            .skip(skip)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs

    async def count_user_sessions(
        self, user_id: str, workflow_id: Optional[str] = None
    ) -> int:
        query: dict = {"user_id": user_id}
        if workflow_id:
            query["workflow_id"] = workflow_id
        return await self.count(query)

    async def get_session_with_messages(self, session_id: str) -> Optional[dict]:
        """Load full session including all messages."""
        return await self.find_by_id(session_id)

    async def get_recent_messages(
        self, session_id: str, limit: int = 20
    ) -> Optional[list[dict]]:
        """
        Fetch only the last N messages from a session.
        Uses $slice projection for efficiency on large conversations.
        """
        from bson import ObjectId as BsonObjectId

        if not BsonObjectId.is_valid(session_id):
            return None

        doc = await self._collection.find_one(
            {"_id": BsonObjectId(session_id)},
            {"messages": {"$slice": -limit}},
        )
        if doc is None:
            return None
        return doc.get("messages", [])

    async def update_title(self, session_id: str, title: str) -> bool:
        """Update session title (auto-generated from first message)."""
        return await self.update_one(session_id, {"title": title})

    async def deactivate_session(self, session_id: str) -> bool:
        """Soft-close a session."""
        return await self.update_one(session_id, {"is_active": False})