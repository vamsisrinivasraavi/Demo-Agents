"""
Vector store repository — LlamaIndex-first design.

ALL ingestion and retrieval goes through LlamaIndex.
Raw Qdrant client is used ONLY for collection lifecycle management
(create, delete, info). Everything else is LlamaIndex's domain.

Ingestion flow (LlamaIndex):
    SQL Server → SQLAlchemy inspect → SQLTableSchema objects
    → SQLTableNodeMapping → ObjectIndex(VectorStoreIndex + QdrantVectorStore)
    → LlamaIndex auto-generates embeddings + stores in Qdrant

Retrieval flow (LlamaIndex):
    User query → ObjectIndex.as_retriever() finds relevant tables
    → SQLTableRetrieverQueryEngine generates SQL → executes against live DB
    → Returns natural language response with SQL + results

Why LlamaIndex end-to-end:
- Consistent embedding format between ingest and retrieval
- ObjectIndex handles table-to-node mapping automatically
- SQLTableRetrieverQueryEngine does NL→SQL→execute→NL in one call
- No manual embedding generation or Qdrant point construction needed
"""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from app.core.config import Settings, get_settings
from app.core.exceptions import VectorStoreError
from app.core.logging import get_logger, log_duration

logger = get_logger(__name__)

# Bounded thread pool for sync LlamaIndex + SQLAlchemy operations
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llamaindex")


class VectorRepository:
    """
    LlamaIndex-powered vector store repository.

    Uses QdrantVectorStore as the LlamaIndex storage backend.
    Sync LlamaIndex operations are wrapped with run_in_executor.
    """

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        settings: Optional[Settings] = None,
    ):
        self._async_client = qdrant_client
        self._settings = settings or get_settings()

        # LlamaIndex requires a SYNC Qdrant client — built lazily
        self._sync_client: Optional[QdrantClient] = None

    def _get_sync_client(self) -> QdrantClient:
        """Lazy-init a sync QdrantClient for LlamaIndex."""
        if self._sync_client is None:
            if self._settings.QDRANT_URI:
                self._sync_client = QdrantClient(
                    url=self._settings.QDRANT_URI,
                    api_key=self._settings.QDRANT_API_KEY,
                    prefer_grpc=False,
                    check_compatibility=False,
                )
            else:
                self._sync_client = QdrantClient(
                    host=self._settings.QDRANT_HOST,
                    port=self._settings.QDRANT_PORT,
                    api_key=self._settings.QDRANT_API_KEY,
                    grpc_port=self._settings.QDRANT_GRPC_PORT,
                    prefer_grpc=self._settings.QDRANT_PREFER_GRPC,
                )
        return self._sync_client

    # ──────────────────────────────────────────────
    # Collection Lifecycle (raw Qdrant — async)
    # ──────────────────────────────────────────────

    async def ensure_collection(
        self,
        collection_name: str,
        vector_size: Optional[int] = None,
    ) -> bool:
        """Create collection if it doesn't exist. Returns True if created."""
        try:
            exists = await self._async_client.collection_exists(collection_name)
            if exists:
                logger.info("qdrant.collection_exists", collection=collection_name)
                return False

            size = vector_size or self._settings.OPENAI_EMBEDDING_DIMENSIONS
            await self._async_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )
            logger.info("qdrant.collection_created", collection=collection_name, size=size)
            return True
        except Exception as e:
            raise VectorStoreError(
                detail=f"Failed to ensure collection '{collection_name}': {e}",
                context={"collection": collection_name},
            )

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection and all its vectors."""
        try:
            await self._async_client.delete_collection(collection_name)
            logger.info("qdrant.collection_deleted", collection=collection_name)
            return True
        except Exception as e:
            logger.error("qdrant.delete_failed", collection=collection_name, error=str(e))
            return False

    async def get_collection_info(self, collection_name: str) -> Optional[dict]:
        """Get collection metadata."""
        try:
            info = await self._async_client.get_collection(collection_name)
            return {
                "name": collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
            }
        except Exception:
            return None

    async def count_points(self, collection_name: str) -> int:
        info = await self.get_collection_info(collection_name)
        return info["points_count"] if info else 0

    # ──────────────────────────────────────────────
    # Schema Ingestion (LlamaIndex → Qdrant)
    # ──────────────────────────────────────────────

    @log_duration("llamaindex.ingest_schema")
    async def ingest_sql_schema(
        self,
        sql_connection_string: str,
        collection_name: str,
        embedding_model: Optional[str] = None,
        chunk_strategy: str = "table_level",
    ) -> dict[str, Any]:
        """
        Full schema ingestion pipeline via LlamaIndex.

        Steps (all sync, run in thread pool):
        1. Connect to SQL Server via SQLAlchemy
        2. Inspect schema: tables, columns, FKs, PKs, indexes
        3. Build SQLTableSchema objects with rich context strings
        4. Create SQLTableNodeMapping → ObjectIndex
        5. ObjectIndex uses QdrantVectorStore → auto-embeds + stores

        Args:
            sql_connection_string: SQLAlchemy-format MSSQL connection string
            collection_name: Qdrant collection to store vectors in
            embedding_model: OpenAI embedding model override
            chunk_strategy: "table_level" | "column_level" | "hybrid"

        Returns:
            dict with schema_stats (tables, columns, FKs, etc.)
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            self._sync_ingest_schema,
            sql_connection_string,
            collection_name,
            embedding_model,
            chunk_strategy,
        )
        return result

    def _sync_ingest_schema(
        self,
        sql_connection_string: str,
        collection_name: str,
        embedding_model: Optional[str],
        chunk_strategy: str,
    ) -> dict[str, Any]:
        """
        Synchronous ingestion — runs in thread pool.
        This is where all the LlamaIndex + SQLAlchemy work happens.
        """
        from llama_index.core import SQLDatabase, StorageContext, VectorStoreIndex
        from llama_index.core.objects import (
            ObjectIndex,
            SQLTableNodeMapping,
            SQLTableSchema,
        )
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from sqlalchemy import create_engine, inspect

        settings = self._settings
        sync_client = self._get_sync_client()

        # ── Step 1: Connect + Inspect ──
        engine = create_engine(sql_connection_string)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        logger.info(
            "ingest.schema_inspected",
            tables=len(table_names),
            database=engine.url.database,
        )

        # ── Step 2: Build SQLDatabase (schema only, no data) ──
        sql_database = SQLDatabase(
            engine,
            include_tables=table_names,
            sample_rows_in_table_info=2,  # Schema only — critical for large DBs
        )

        # ── Step 3: Build rich SQLTableSchema objects ──
        table_schemas = []
        total_columns = 0
        total_fks = 0
        total_indexes = 0

        for table_name in table_names:
            columns = inspector.get_columns(table_name)
            fks = inspector.get_foreign_keys(table_name)
            pk = inspector.get_pk_constraint(table_name)
            indexes = inspector.get_indexes(table_name)
            # Safe unique handling
            try:
                unique_constraints = inspector.get_unique_constraints(table_name)
            except:
                unique_constraints = []

            unique_indexes = [idx for idx in indexes if idx.get("unique")]
            unique_constraints += unique_indexes

            total_columns += len(columns)
            total_fks += len(fks)
            total_indexes += len(indexes)

            # Build context string based on chunk strategy
            context = self._build_table_context(
                table_name=table_name,
                columns=columns,
                foreign_keys=fks,
                primary_key=pk,
                indexes=indexes,
                unique_constraints=unique_constraints,
                strategy=chunk_strategy,
            )

            table_schemas.append(
                SQLTableSchema(table_name=table_name, context_str=context)
            )

        logger.info(
            "ingest.schemas_built",
            tables=len(table_schemas),
            columns=total_columns,
            foreign_keys=total_fks,
        )

        # ── Step 4: Create LlamaIndex components ──
        embed_model = OpenAIEmbedding(
            model_name=embedding_model or settings.OPENAI_EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
        )

        # QdrantVectorStore as LlamaIndex storage backend
        vector_store = QdrantVectorStore(
            client=sync_client,
            collection_name=collection_name,
        )

        # ── Step 5: Build ObjectIndex → auto-embeds + stores in Qdrant ──
        table_node_mapping = SQLTableNodeMapping(sql_database)

        # This is where the magic happens:
        # ObjectIndex.from_objects() generates embeddings for each
        # SQLTableSchema.context_str and stores them in Qdrant
        # via the VectorStoreIndex backed by QdrantVectorStore
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store,
        )

        _object_index = ObjectIndex.from_objects(
            table_schemas,
            table_node_mapping,
            VectorStoreIndex,
            embed_model=embed_model,
            storage_context=storage_context,
        )

        logger.info(
            "ingest.complete",
            collection=collection_name,
            tables=len(table_schemas),
        )

        # ── Return stats ──
        return {
            "tables_count": len(table_names),
            "columns_count": total_columns,
            "foreign_keys_count": total_fks,
            "indexes_count": total_indexes,
            "views_count": len(inspector.get_view_names()),
            "table_names": table_names,
        }

    def _build_table_context(
        self,
        table_name: str,
        columns: list[dict],
        foreign_keys: list[dict],
        primary_key: Optional[dict],
        indexes: list[dict],
        unique_constraints: list[dict],
        strategy: str = "table_level",
    ) -> str:
        """
        Build a rich semantic description of a table for embedding.

        This context string is what LlamaIndex embeds and searches against.
        The richer and more descriptive it is, the better table discovery works.
        """
        parts = [f"Table: {table_name}"]

        # Columns with types and nullability
        col_details = []
        for col in columns:
            nullable = "nullable" if col.get("nullable", True) else "NOT NULL"
            default = f", default={col['default']}" if col.get("default") else ""
            col_details.append(
                f"  - {col['name']} ({str(col['type'])}), {nullable}{default}"
            )
        parts.append(f"Columns ({len(columns)}):")
        parts.extend(col_details)

        # Primary key
        pk_cols = primary_key.get("constrained_columns", []) if primary_key else []
        if pk_cols:
            parts.append(f"Primary key: ({', '.join(pk_cols)})")

        # Foreign keys with full relationship description
        if foreign_keys:
            fk_lines = []
            for fk in foreign_keys:
                referred = fk.get("referred_table", "?")
                local_cols = fk.get("constrained_columns", [])
                remote_cols = fk.get("referred_columns", [])
                fk_lines.append(
                    f"  - {', '.join(local_cols)} → {referred}({', '.join(remote_cols)})"
                )
            parts.append(f"Foreign keys ({len(foreign_keys)}):")
            parts.extend(fk_lines)
            # Add relationship narrative for better semantic matching
            for fk in foreign_keys:
                referred = fk.get("referred_table", "?")
                parts.append(
                    f"  Relationship: {table_name} references {referred} "
                    f"(many-to-one from {table_name} to {referred})"
                )

        # Indexes
        if indexes:
            idx_lines = []
            for idx in indexes:
                unique_str = "UNIQUE " if idx.get("unique") else ""
                cols = ", ".join(idx.get("column_names", []))
                idx_lines.append(f"  - {unique_str}INDEX on ({cols})")
            parts.append(f"Indexes ({len(indexes)}):")
            parts.extend(idx_lines)

        # Unique constraints
        if unique_constraints:
            for uc in unique_constraints:
                cols = ", ".join(uc.get("column_names", []))
                parts.append(f"  UNIQUE constraint on ({cols})")

        # Column-level strategy: add individual column descriptions
        if strategy in ("column_level", "hybrid"):
            parts.append("Column descriptions:")
            for col in columns:
                parts.append(
                    f"  The column '{col['name']}' in table '{table_name}' "
                    f"has type {str(col['type'])} and is "
                    f"{'optional' if col.get('nullable', True) else 'required'}."
                )

        return "\n".join(parts)

    # ──────────────────────────────────────────────
    # Query Engine Builder (LlamaIndex retrieval)
    # ──────────────────────────────────────────────

    @log_duration("llamaindex.build_query_engine")
    async def build_query_engine(
        self,
        sql_connection_string: str,
        collection_name: str,
        top_k: int = 5,
        llm_model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ):
        """
        Build a LlamaIndex SQLTableRetrieverQueryEngine.

        This connects:
        - QdrantVectorStore (for table discovery via embedding similarity)
        - SQLDatabase (for live SQL execution against the real DB)
        - LLM (for NL→SQL generation and response synthesis)

        The engine is NOT a singleton — different workflows may point to
        different databases. Engines can be cached in-memory by the
        service layer if needed.

        Returns:
            SQLTableRetrieverQueryEngine ready to accept queries
        """
        loop = asyncio.get_running_loop()
        engine = await loop.run_in_executor(
            _executor,
            self._sync_build_query_engine,
            sql_connection_string,
            collection_name,
            top_k,
            llm_model,
            temperature,
            max_tokens,
        )
        return engine

    def _sync_build_query_engine(
        self,
        sql_connection_string: str,
        collection_name: str,
        top_k: int,
        llm_model: Optional[str],
        temperature: float,
        max_tokens: int,
    ):
        """
        Synchronous engine build — runs in thread pool.

        Flow:
        1. Connect to same SQL Server used during ingestion
        2. Load QdrantVectorStore pointing to the ingested collection
        3. Rebuild ObjectIndex from the stored vectors
        4. Wrap in SQLTableRetrieverQueryEngine with LLM
        """
        from llama_index.core import SQLDatabase, VectorStoreIndex
        from llama_index.core.indices.struct_store.sql_query import (
            SQLTableRetrieverQueryEngine,
        )
        from llama_index.core.objects import (
            ObjectIndex,
            SQLTableNodeMapping,
            SQLTableSchema,
        )
        from llama_index.core.prompts import PromptTemplate
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.openai import OpenAI
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from sqlalchemy import create_engine, inspect

        settings = self._settings
        sync_client = self._get_sync_client()

        # ── Step 1: Reconnect to the same SQL Server ──
        engine = create_engine(sql_connection_string)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        sql_database = SQLDatabase(
            engine,
            include_tables=table_names,
            sample_rows_in_table_info=0,
        )

        # ── Step 2: Load QdrantVectorStore with existing vectors ──
        vector_store = QdrantVectorStore(
            client=sync_client,
            collection_name=collection_name,
        )

        embed_model = OpenAIEmbedding(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
        )

        # ── Step 3: Rebuild ObjectIndex from stored vectors ──
        #
        # We need the same SQLTableSchema objects + mapping to
        # reconstruct the ObjectIndex. The vectors are already in
        # Qdrant from ingestion — we just reconnect the mapping.
        table_node_mapping = SQLTableNodeMapping(sql_database)

        table_schemas = []
        for table_name in table_names:
            columns = inspector.get_columns(table_name)
            fks = inspector.get_foreign_keys(table_name)
            pk = inspector.get_pk_constraint(table_name)

            col_desc = ", ".join(f"{c['name']} ({str(c['type'])})" for c in columns)
            fk_desc = "; ".join(
                f"FK {fk['constrained_columns']} → "
                f"{fk['referred_table']}.{fk['referred_columns']}"
                for fk in fks if fk.get("referred_table")
            )

            context = (
                f"Table '{table_name}' columns: {col_desc}. "
                f"PK: {pk.get('constrained_columns', []) if pk else []}. "
                f"Foreign keys: {fk_desc or 'None'}."
            )
            table_schemas.append(
                SQLTableSchema(table_name=table_name, context_str=context)
            )

        # Rebuild index from existing Qdrant vectors
        vector_index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )

        object_index = ObjectIndex(
            index=vector_index,
            object_node_mapping=table_node_mapping,
        )

        # ── Step 4: Build the query engine ──
        llm = OpenAI(
            model=llm_model or settings.OPENAI_LLM_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.OPENAI_API_KEY,
        )

        instructions = """
            When generating SQL queries, strictly follow these rules:

            1. NEVER use columns with data types like `text`, `ntext`, or `image` in:
            - GROUP BY
            - ORDER BY
            - DISTINCT

            2. If such columns are needed in the final output:
            - First perform aggregation WITHOUT those columns
            - Then JOIN back to retrieve them

            3. Prefer using Common Table Expressions (CTEs) for aggregation.

            4. Ensure SQL Server compatible syntax.

            5. Generate ONLY SQL. No explanation.

            6. And Most importantly: ALWAYS use the table and column names exactly as they appear in the schema. Do NOT attempt to rename or alias them.

            7. If user ask an question that is not answerable with the given tables or not related to the schema, say "I don't know" instead of making up an answer and do not generate any SQL.
        """

        text_to_sql_prompt = PromptTemplate(
        """
        You are an expert SQL developer working with Microsoft SQL Server.

        {instructions}

        Schema:
        {schema}

        User Query:
        {query_str}

        Generate ONLY the SQL query.
        """
        ).partial_format(instructions=instructions)

        query_engine = SQLTableRetrieverQueryEngine(
            sql_database=sql_database,
            table_retriever=object_index.as_retriever(
                similarity_top_k=top_k,
            ),
            llm=llm,
            text_to_sql_prompt=text_to_sql_prompt,
            return_raw=True,
            response_mode="tree_summarize",
            verbose=True,
        )

        logger.info(
            "llamaindex.engine_built",
            collection=collection_name,
            tables=len(table_names),
            top_k=top_k,
            model=llm_model or settings.OPENAI_LLM_MODEL,
        )

        return query_engine

    # ──────────────────────────────────────────────
    # Query Execution Helper
    # ──────────────────────────────────────────────

    @log_duration("llamaindex.query")
    async def execute_query(
        self,
        query_engine,
        query: str,
    ) -> dict[str, Any]:
        """
        Execute a natural language query against a built engine.

        Runs the full LlamaIndex pipeline:
        query → table retrieval → SQL generation → SQL execution → response

        Returns:
            dict with 'response', 'sql_query', 'source_tables', 'metadata'
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            self._sync_execute_query,
            query_engine,
            query,
        )
        return result
    
    def _extract_tables(self, sql):
        return set(re.findall(r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, re.IGNORECASE))

    def _extract_columns(self, sql):
        # captures alias.column (e.g., p.name, pt.project_id)
        return set(re.findall(r'([a-zA-Z_]+\.[a-zA-Z_]+)', sql))

    def _sync_execute_query(
        self,
        query_engine,
        query: str,
    ) -> dict[str, Any]:
        """Synchronous query execution — runs in thread pool."""
        try:
            response = query_engine.query(query)

            # Extract SQL and metadata from the response
            sql_query = None
            sql_result_preview = None

            # LlamaIndex stores the generated SQL in metadata
            if hasattr(response, "metadata"):
                sql_query = response.metadata.get("sql_query", None)
                # Also try 'result' key for raw SQL result
                if not sql_query:
                    sql_query = response.metadata.get("query", None)
            
            # LlamaIndex may also include a preview of the SQL execution result in metadata
            if hasattr(response, "metadata"):
                sql_result_preview = str(response.metadata.get("result", None))
            
            # Extract source tables from source nodes
            tables = []
            columns = []
            output_columns = []

            if hasattr(response, "source_nodes"):
                for node in response.source_nodes:
                    metadata = node.metadata
                    
                    sql_query = metadata.get("sql_query", "")
                    col_keys = metadata.get("col_keys", [])

                    # Tables
                    tables.extend(self._extract_tables(sql_query))

                    # Columns used in query
                    columns.extend(self._extract_columns(sql_query))

                    # Output columns
                    output_columns.extend(col_keys)

            result_text = str(response)

            logger.info(
                "llamaindex.query_executed",
                sql_query=sql_query[:200] if sql_query else None,
                source_tables=tables,
                used_columns=columns,
                output_columns=output_columns,
                response_length=len(result_text),
            )

            return {
                "response": result_text,
                "sql_query": sql_query,
                "source_tables": tables,
                "used_columns": columns,
                "output_columns": output_columns,
                "sql_result_preview": sql_result_preview,
                "metadata": response.metadata if hasattr(response, "metadata") else {},
            }

        except Exception as e:
            logger.error("llamaindex.query_failed", error=str(e), query=query[:200])
            raise VectorStoreError(
                detail=f"Query execution failed: {e}",
                context={"query": query[:200]},
            )

    # ──────────────────────────────────────────────
    # Cleanup
    # ──────────────────────────────────────────────

    def close_sync_client(self):
        """Close the sync Qdrant client (call during shutdown)."""
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None