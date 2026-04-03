"""
Base repository providing common async MongoDB operations.

All repositories inherit from this. Keeps CRUD boilerplate DRY
while allowing each repo to add domain-specific queries.
"""

from datetime import datetime, timezone
from typing import Any, Optional, TypeVar

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class BaseRepository:
    """
    Async MongoDB repository base class.

    Convention:
    - All public methods are async
    - ObjectId ↔ str conversion happens at this layer
    - Domain models are dicts at this layer (conversion in service)
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str):
        self._db = db
        self._collection = db[collection_name]
        self._collection_name = collection_name

    async def insert_one(self, document: dict[str, Any]) -> str:
        """Insert a document and return its string ID."""
        document["created_at"] = document.get("created_at", datetime.now(timezone.utc))
        document["updated_at"] = datetime.now(timezone.utc)
        result = await self._collection.insert_one(document)
        doc_id = str(result.inserted_id)
        logger.debug(
            "repo.insert",
            collection=self._collection_name,
            id=doc_id,
        )
        return doc_id

    async def find_by_id(self, doc_id: str) -> Optional[dict[str, Any]]:
        """Find a document by its ObjectId string."""
        if not ObjectId.is_valid(doc_id):
            return None
        doc = await self._collection.find_one({"_id": ObjectId(doc_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def find_one(self, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Find a single document matching a query."""
        doc = await self._collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def find_many(
        self,
        query: dict[str, Any],
        skip: int = 0,
        limit: int = 50,
        sort: Optional[list[tuple[str, int]]] = None,
    ) -> list[dict[str, Any]]:
        """Find multiple documents with pagination and optional sorting."""
        cursor = self._collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs

    async def count(self, query: dict[str, Any]) -> int:
        """Count documents matching a query."""
        return await self._collection.count_documents(query)

    async def update_one(
        self,
        doc_id: str,
        update: dict[str, Any],
    ) -> bool:
        """Update a document by ID. Returns True if modified."""
        if not ObjectId.is_valid(doc_id):
            return False
        update["updated_at"] = datetime.now(timezone.utc)
        result = await self._collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": update},
        )
        return result.modified_count > 0

    async def update_one_raw(
        self,
        doc_id: str,
        update_ops: dict[str, Any],
    ) -> bool:
        """
        Update with raw MongoDB operators ($push, $inc, etc.).
        The caller provides the full update expression.
        """
        if not ObjectId.is_valid(doc_id):
            return False
        # Inject updated_at into $set if present, else create $set
        if "$set" in update_ops:
            update_ops["$set"]["updated_at"] = datetime.now(timezone.utc)
        else:
            update_ops["$set"] = {"updated_at": datetime.now(timezone.utc)}
        result = await self._collection.update_one(
            {"_id": ObjectId(doc_id)},
            update_ops,
        )
        return result.modified_count > 0

    async def delete_one(self, doc_id: str) -> bool:
        """Delete a document by ID. Returns True if deleted."""
        if not ObjectId.is_valid(doc_id):
            return False
        result = await self._collection.delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count > 0