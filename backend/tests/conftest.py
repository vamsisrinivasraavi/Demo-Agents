"""
Test fixtures and shared utilities.

Strategy:
- Override FastAPI dependencies with mocks at the app level
- Use an in-memory MongoDB mock (mongomock via MongoMockClient)
- Mock Redis and Qdrant with lightweight fakes
- Pre-seed test users (admin + regular) with known credentials
- Generate valid JWT tokens for authenticated requests
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.core.security import UserRole, create_token_pair, hash_password


# ──────────────────────────────────────────────
# Test Settings Override
# ──────────────────────────────────────────────


def _get_test_settings() -> Settings:
    """Override settings for testing."""
    return Settings(
        APP_NAME="Schema Assistant Tests",
        DEBUG=True,
        ENVIRONMENT="testing",
        JWT_SECRET_KEY="test-secret-key-for-jwt-signing-only",
        MONGO_URI="mongodb://localhost:27017",
        MONGO_DB_NAME="schema_assistant_test",
        REDIS_URL="redis://localhost:6379/15",
        QDRANT_HOST="localhost",
        QDRANT_PORT=6333,
        OPENAI_API_KEY="sk-test-fake-key",
        LOG_LEVEL="WARNING",
    )


# ──────────────────────────────────────────────
# In-Memory MongoDB Mock
# ──────────────────────────────────────────────


class FakeCollection:
    """Minimal async MongoDB collection mock with in-memory storage."""

    def __init__(self):
        self._docs: dict[str, dict] = {}
        self._counter = 0

    async def insert_one(self, doc: dict):
        from bson import ObjectId

        oid = ObjectId()
        doc["_id"] = oid
        self._docs[str(oid)] = doc
        return MagicMock(inserted_id=oid)

    async def find_one(self, query: dict) -> Optional[dict]:
        from bson import ObjectId

        if "_id" in query:
            oid = query["_id"]
            key = str(oid) if isinstance(oid, ObjectId) else str(oid)
            doc = self._docs.get(key)
            return dict(doc) if doc else None

        # Simple field matching
        for doc in self._docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict = None, projection: dict = None):
        """Returns a chainable cursor mock."""
        query = query or {}
        results = []
        for doc in self._docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                d = dict(doc)
                if projection:
                    # Simple projection (include only specified fields + _id)
                    filtered = {"_id": d["_id"]}
                    for k, v in projection.items():
                        if v and k in d:
                            filtered[k] = d[k]
                    d = filtered
                results.append(d)
        return FakeCursor(results)

    async def update_one(self, query: dict, update: dict):
        from bson import ObjectId

        oid = query.get("_id")
        if oid is None:
            return MagicMock(modified_count=0)

        key = str(oid) if isinstance(oid, ObjectId) else str(oid)
        doc = self._docs.get(key)
        if doc is None:
            return MagicMock(modified_count=0)

        if "$set" in update:
            doc.update(update["$set"])
        if "$push" in update:
            for field, value in update["$push"].items():
                if "$each" in value if isinstance(value, dict) else False:
                    doc.setdefault(field, []).extend(value["$each"])
                else:
                    doc.setdefault(field, []).append(value)
        if "$inc" in update:
            for field, value in update["$inc"].items():
                doc[field] = doc.get(field, 0) + value

        return MagicMock(modified_count=1)

    async def delete_one(self, query: dict):
        from bson import ObjectId

        oid = query.get("_id")
        if oid is None:
            return MagicMock(deleted_count=0)

        key = str(oid) if isinstance(oid, ObjectId) else str(oid)
        if key in self._docs:
            del self._docs[key]
            return MagicMock(deleted_count=1)
        return MagicMock(deleted_count=0)

    async def count_documents(self, query: dict) -> int:
        if not query:
            return len(self._docs)
        count = 0
        for doc in self._docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                count += 1
        return count

    async def create_index(self, *args, **kwargs):
        pass


class FakeCursor:
    """Chainable cursor mock for find() queries."""

    def __init__(self, results: list[dict]):
        self._results = results
        self._skip = 0
        self._limit = 100

    def sort(self, *args, **kwargs):
        return self

    def skip(self, n: int):
        self._skip = n
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    async def to_list(self, length: int = 100) -> list[dict]:
        sliced = self._results[self._skip: self._skip + self._limit]
        return sliced[:length]


class FakeDatabase:
    """In-memory MongoDB database mock."""

    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def __getattr__(self, name: str) -> FakeCollection:
        return self[name]


# ──────────────────────────────────────────────
# Fake Redis
# ──────────────────────────────────────────────


class FakeRedis:
    """Minimal async Redis mock."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def ping(self):
        return True

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def aclose(self):
        pass

    async def scan_iter(self, match: str = "*", count: int = 100):
        import fnmatch
        for key in list(self._store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key


# ──────────────────────────────────────────────
# Fake Qdrant
# ──────────────────────────────────────────────


class FakeQdrant:
    """Minimal async Qdrant client mock."""

    def __init__(self):
        self._collections: dict[str, list] = {}

    async def collection_exists(self, name: str) -> bool:
        return name in self._collections

    async def create_collection(self, collection_name: str, **kwargs):
        self._collections[collection_name] = []

    async def delete_collection(self, name: str):
        self._collections.pop(name, None)

    async def get_collection(self, name: str):
        if name not in self._collections:
            raise Exception("Not found")
        return MagicMock(
            vectors_count=len(self._collections[name]),
            points_count=len(self._collections[name]),
            status=MagicMock(value="green"),
        )

    async def close(self):
        pass


# ──────────────────────────────────────────────
# Fake VectorRepository
# ──────────────────────────────────────────────


class FakeVectorRepo:
    """Mock VectorRepository that skips LlamaIndex entirely."""

    def __init__(self):
        self._qdrant = FakeQdrant()

    async def ensure_collection(self, collection_name: str, vector_size: int = None):
        await self._qdrant.create_collection(collection_name)
        return True

    async def delete_collection(self, collection_name: str):
        await self._qdrant.delete_collection(collection_name)
        return True

    async def get_collection_info(self, collection_name: str):
        return {"name": collection_name, "vectors_count": 10, "points_count": 10, "status": "green"}

    async def ingest_sql_schema(self, sql_connection_string, collection_name, **kwargs):
        return {
            "tables_count": 15,
            "columns_count": 120,
            "foreign_keys_count": 8,
            "indexes_count": 22,
            "views_count": 3,
            "table_names": ["orders", "customers", "products"],
        }

    async def build_query_engine(self, sql_connection_string, collection_name, **kwargs):
        return MagicMock()

    async def execute_query(self, query_engine, query: str):
        return {
            "response": f"Based on the database schema, here is the answer to: {query}",
            "sql_query": "SELECT * FROM orders WHERE status = 'active'",
            "source_tables": ["orders", "customers"],
            "metadata": {},
        }

    def close_sync_client(self):
        pass


# ──────────────────────────────────────────────
# Test Data
# ──────────────────────────────────────────────

ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "admin_password_123"
USER_EMAIL = "user@test.com"
USER_PASSWORD = "user_password_123"


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def fake_db() -> FakeDatabase:
    """Fresh in-memory MongoDB for each test."""
    return FakeDatabase()


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest_asyncio.fixture
async def fake_vector_repo() -> FakeVectorRepo:
    return FakeVectorRepo()


@pytest_asyncio.fixture
async def fake_cache_repo(fake_redis):
    from app.repositories.cache_repo import CacheRepository
    repo = CacheRepository(fake_redis, _get_test_settings())
    # Force hash-based fallback (skip LangCache init)
    repo._initialized = True
    repo._lang_cache = None
    return repo


@pytest_asyncio.fixture
async def client(
    fake_db: FakeDatabase,
    fake_redis: FakeRedis,
    fake_vector_repo: FakeVectorRepo,
    fake_cache_repo,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Build a test AsyncClient with all dependencies mocked.
    """
    from app.core.config import get_settings
    from app.core.dependencies import (
        get_cache_repo,
        get_mongo_db,
        get_qdrant,
        get_redis,
        get_vector_repo,
    )
    from app.main import create_app

    # Override settings
    app = create_app()

    app.dependency_overrides[get_settings] = _get_test_settings
    app.dependency_overrides[get_mongo_db] = lambda: fake_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_qdrant] = lambda: FakeQdrant()
    app.dependency_overrides[get_vector_repo] = lambda: fake_vector_repo
    app.dependency_overrides[get_cache_repo] = lambda: fake_cache_repo

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ──────────────────────────────────────────────
# Auth Helper Fixtures
# ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient) -> str:
    """Register an admin and return the access token."""
    resp = await client.post("/api/auth/register", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
        "display_name": "Test Admin",
        "role": "admin",
    })
    if resp.status_code == 201:
        return resp.json()["tokens"]["access_token"]
    # Already exists — login
    resp = await client.post("/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    return resp.json()["tokens"]["access_token"]


@pytest_asyncio.fixture
async def user_token(client: AsyncClient) -> str:
    """Register a regular user and return the access token."""
    resp = await client.post("/api/auth/register", json={
        "email": USER_EMAIL,
        "password": USER_PASSWORD,
        "display_name": "Test User",
        "role": "user",
    })
    if resp.status_code == 201:
        return resp.json()["tokens"]["access_token"]
    resp = await client.post("/api/auth/login", json={
        "email": USER_EMAIL,
        "password": USER_PASSWORD,
    })
    return resp.json()["tokens"]["access_token"]


def auth_header(token: str) -> dict[str, str]:
    """Build Authorization header."""
    return {"Authorization": f"Bearer {token}"}