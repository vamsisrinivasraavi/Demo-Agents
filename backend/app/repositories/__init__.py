"""
Data access layer — all external storage interactions go through here.

Repositories are injected into services via FastAPI's Depends() system.
Each repository owns one data store / collection.
"""

from app.repositories.base import BaseRepository
from app.repositories.user_repo import UserRepository
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.repositories.chat_repo import ChatRepository
from app.repositories.cache_repo import CacheRepository
from app.repositories.vector_repo import VectorRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "IngestionConfigRepository",
    "WorkflowRepository",
    "ChatRepository",
    "CacheRepository",
    "VectorRepository",
]