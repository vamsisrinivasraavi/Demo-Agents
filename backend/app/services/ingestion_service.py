"""
Ingestion service.

Orchestrates the full schema ingestion pipeline:
1. Validate and test SQL connection
2. Create ingestion config in MongoDB (PENDING)
3. Delegate to VectorRepository.ingest_sql_schema() for:
   - Schema extraction via SQLAlchemy
   - SQLTableSchema construction
   - ObjectIndex building with QdrantVectorStore
   - Auto-embedding + storage in Qdrant
4. Update config status (COMPLETED / FAILED)

All LlamaIndex operations are encapsulated in VectorRepository.
This service handles lifecycle, validation, and error recovery.
"""

import asyncio
from typing import Optional

from urllib.parse import quote_plus

from app.core.encryption import decrypt_value, encrypt_value
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    SQLConnectionError,
)
from app.core.logging import get_logger, log_duration
from app.models.ingestion_config import IngestionStatus, SQLConnectionConfig
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.vector_repo import VectorRepository
from app.schemas.ingestion import (
    CreateIngestionRequest,
    IngestionConfigResponse,
    IngestionListResponse,
    SQLConnectionResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        config_repo: IngestionConfigRepository,
        vector_repo: VectorRepository,
    ):
        self._config_repo = config_repo
        self._vector_repo = vector_repo

    # ──────────────────────────────────────────────
    # Connection Testing
    # ──────────────────────────────────────────────

    async def test_connection(
        self, request: TestConnectionRequest
    ) -> TestConnectionResponse:
        """
        Test SQL Server connectivity before committing to a full ingestion.
        Runs a lightweight schema inspection in a thread pool.
        """
        try:
            conn_string = self._build_connection_string(
                host=request.host,
                port=request.port,
                database=request.database,
                username=request.username,
                password=request.password,
                driver=request.driver,
                trust_cert=request.trust_server_certificate,
            )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._sync_test_connection, conn_string
            )
            return result

        except Exception as e:
            logger.error("ingestion.test_failed", error=str(e))
            return TestConnectionResponse(
                success=False,
                message=f"Connection failed: {str(e)}",
            )

    @staticmethod
    def _sync_test_connection(conn_string: str) -> TestConnectionResponse:
        """Sync connection test — runs in thread pool."""
        from sqlalchemy import create_engine, inspect

        engine = create_engine(conn_string, connect_args={"timeout": 10})
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        engine.dispose()

        return TestConnectionResponse(
            success=True,
            message=f"Connected successfully. Found {len(tables)} tables.",
            tables_found=len(tables),
            sample_tables=tables[:10],
        )

    # ──────────────────────────────────────────────
    # Schema Ingestion
    # ──────────────────────────────────────────────

    @log_duration("ingestion.full_pipeline")
    async def ingest_schema(
        self,
        request: CreateIngestionRequest,
        user_id: str,
    ) -> IngestionConfigResponse:
        """
        Full ingestion pipeline:
        1. Encrypt password + save config (PENDING)
        2. Ensure Qdrant collection exists
        3. Run LlamaIndex ingestion via VectorRepository
        4. Update config with stats (COMPLETED) or error (FAILED)
        """
        # Step 1: Save config with encrypted password
        encrypted_pw = encrypt_value(request.sql_connection.password)

        config_data = {
            "name": request.name,
            "description": request.description,
            "sql_connection": {
                "host": request.sql_connection.host,
                "port": request.sql_connection.port,
                "database": request.sql_connection.database,
                "username": request.sql_connection.username,
                "encrypted_password": encrypted_pw,
                "driver": request.sql_connection.driver,
                "trust_server_certificate": request.sql_connection.trust_server_certificate,
            },
            "qdrant_collection": request.qdrant_collection,
            "embedding_model": request.embedding_model,
            "embedding_dimensions": request.embedding_dimensions,
            "chunk_strategy": request.chunk_strategy,
            "sql_top_k": request.sql_top_k,
            "created_by": user_id,
        }

        config_id = await self._config_repo.create_config(config_data)
        logger.info("ingestion.config_created", config_id=config_id)

        # Step 2: Run ingestion (async — but could be background task)
        try:
            await self._config_repo.set_running(config_id)

            # Ensure Qdrant collection
            await self._vector_repo.ensure_collection(
                collection_name=request.qdrant_collection,
                vector_size=request.embedding_dimensions,
            )

            # Build connection string
            conn_string = self._build_connection_string(
                host=request.sql_connection.host,
                port=request.sql_connection.port,
                database=request.sql_connection.database,
                username=request.sql_connection.username,
                password=request.sql_connection.password,  # plaintext for SQLAlchemy
                driver=request.sql_connection.driver,
                trust_cert=request.sql_connection.trust_server_certificate,
            )

            # Step 3: Delegate to VectorRepository (LlamaIndex does everything)
            stats = await self._vector_repo.ingest_sql_schema(
                sql_connection_string=conn_string,
                collection_name=request.qdrant_collection,
                embedding_model=request.embedding_model,
                chunk_strategy=request.chunk_strategy,
            )

            # Step 4: Mark completed
            await self._config_repo.set_completed(config_id, stats)

            logger.info(
                "ingestion.completed",
                config_id=config_id,
                tables=stats.get("tables_count", 0),
            )

        except Exception as e:
            error_msg = f"Ingestion failed: {str(e)}"
            await self._config_repo.set_failed(config_id, error_msg)
            logger.error("ingestion.failed", config_id=config_id, error=str(e))
            raise SQLConnectionError(detail=error_msg)

        # Return the final config state
        return await self.get_config(config_id)

    # ──────────────────────────────────────────────
    # Config CRUD
    # ──────────────────────────────────────────────

    async def get_config(self, config_id: str) -> IngestionConfigResponse:
        """Fetch a single ingestion config."""
        doc = await self._config_repo.find_by_id(config_id)
        if doc is None:
            raise NotFoundError(detail=f"Ingestion config '{config_id}' not found")
        return self._to_response(doc)

    async def list_configs(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> IngestionListResponse:
        """List ingestion configs for a user."""
        skip = (page - 1) * page_size
        docs = await self._config_repo.find_by_user(user_id, skip=skip, limit=page_size)
        total = await self._config_repo.count_by_user(user_id)

        return IngestionListResponse(
            items=[self._to_response(d) for d in docs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def delete_config(self, config_id: str) -> bool:
        """Delete config and its Qdrant collection."""
        doc = await self._config_repo.find_by_id(config_id)
        if doc is None:
            raise NotFoundError(detail=f"Ingestion config '{config_id}' not found")

        # Clean up Qdrant collection
        collection = doc.get("qdrant_collection")
        if collection:
            await self._vector_repo.delete_collection(collection)

        return await self._config_repo.delete_one(config_id)

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _build_connection_string(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        driver: str = "ODBC Driver 18 for SQL Server",
        trust_cert: bool = True,
    ) -> str:
        """Build SQLAlchemy MSSQL connection string."""
        trust = "yes" if trust_cert else "no"
        username = quote_plus(username)
        password = quote_plus(password)

        return (
            f"mssql+pyodbc://{username}:{password}"
            f"@{host}/{database}"
            f"?driver={driver.replace(' ', '+')}"
            f"&TrustServerCertificate={trust}"
        )

    @staticmethod
    def _to_response(doc: dict) -> IngestionConfigResponse:
        """Convert MongoDB document to API response (strips password)."""
        sql_conn = doc.get("sql_connection", {})
        stats = doc.get("schema_stats", {})

        return IngestionConfigResponse(
            id=doc["_id"],
            name=doc["name"],
            description=doc.get("description", ""),
            sql_connection=SQLConnectionResponse(
                host=sql_conn.get("host", ""),
                port=sql_conn.get("port", 1433),
                database=sql_conn.get("database", ""),
                username=sql_conn.get("username", ""),
                driver=sql_conn.get("driver", ""),
            ),
            qdrant_collection=doc.get("qdrant_collection", ""),
            embedding_model=doc.get("embedding_model", ""),
            embedding_dimensions=doc.get("embedding_dimensions", 1536),
            chunk_strategy=doc.get("chunk_strategy", "table_level"),
            sql_top_k=doc.get("sql_top_k", 5),
            status=IngestionStatus(doc.get("status", "pending")),
            schema_stats=stats,
            error_message=doc.get("error_message"),
            created_by=doc.get("created_by", ""),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )