"""
Agent 1: Retrieval Agent.

Core agent — always runs first in the pipeline.

Flow:
1. Load ingestion config to get SQL connection string + Qdrant collection
2. Build LlamaIndex SQLTableRetrieverQueryEngine via VectorRepository
3. Execute user query → table discovery → SQL generation → live execution → NL response
4. Write results (response, SQL, tables, confidence) into AgentContext

The confidence score is derived from the relevance of retrieved tables.
If confidence is below the threshold, the web search agent is triggered.
"""

from typing import Optional

from urllib.parse import quote_plus

from app.core.encryption import decrypt_value
from app.core.logging import get_logger
from app.models.workflow import AgentType, RetrievalAgentConfig
from app.repositories.vector_repo import VectorRepository
from app.services.agents.base import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
)

logger = get_logger(__name__)

# In-memory cache of built query engines (keyed by config_id)
# Avoids rebuilding the engine on every single query
_engine_cache: dict[str, object] = {}


class RetrievalAgent(BaseAgent):
    """
    Vector retrieval + SQL generation agent powered by LlamaIndex.

    Uses SQLTableRetrieverQueryEngine under the hood:
    - Embeds user query
    - Finds top-k relevant tables via Qdrant similarity search
    - Generates SQL from the matched table schemas
    - Executes SQL against the live database
    - Synthesizes a natural language response
    """

    agent_type = AgentType.RETRIEVAL

    def __init__(self, vector_repo: VectorRepository):
        self._vector_repo = vector_repo

    async def should_run(self, context: AgentContext) -> bool:
        """Retrieval agent always runs — it's the primary agent."""
        return True

    async def _execute(self, context: AgentContext) -> AgentResult:
        """
        Execute the LlamaIndex retrieval pipeline.
        """
        # Parse agent-specific config from workflow
        agent_configs = context.workflow_config.get("agents", [])
        retrieval_cfg = RetrievalAgentConfig()
        for ac in agent_configs:
            if ac.get("type") == AgentType.RETRIEVAL:
                retrieval_cfg = RetrievalAgentConfig(**ac.get("config", {}))
                break

        ingestion = context.ingestion_config
        collection_name = ingestion.get("qdrant_collection", "")
        config_id = str(ingestion.get("_id", ""))

        # Build connection string from ingestion config
        sql_conn = ingestion.get("sql_connection", {})
        decrypted_pw = decrypt_value(sql_conn.get("encrypted_password", ""))

        trust = "yes" if sql_conn.get("trust_server_certificate", True) else "no"
        driver = sql_conn.get("driver", "ODBC Driver 18 for SQL Server")

        username = quote_plus(sql_conn["username"])
        decrypted_pw_quoted = quote_plus(decrypted_pw)

        conn_string = (
            f"mssql+pyodbc://{username}:{decrypted_pw_quoted}"
            f"@{sql_conn['host']}/{sql_conn['database']}"
            f"?driver={driver.replace(' ', '+')}"
            f"&TrustServerCertificate={trust}"
        )

        # Get or build the query engine
        model_settings = context.workflow_config.get("model_settings", {})
        query_engine = await self._get_or_build_engine(
            config_id=config_id,
            conn_string=conn_string,
            collection_name=collection_name,
            top_k=retrieval_cfg.top_k,
            llm_model=model_settings.get("model"),
            temperature=model_settings.get("temperature", 0.2),
            max_tokens=model_settings.get("max_tokens", 1024),
        )

        # Execute the query via LlamaIndex
        result = await self._vector_repo.execute_query(query_engine, context.query)

        response_text = result.get("response", "")
        sql_query = result.get("sql_query")
        source_tables = result.get("source_tables", [])
        used_columns = result.get("used_columns", [])
        output_columns = result.get("output_columns", [])
        sql_result_preview = result.get("sql_result_preview", None)

        # Estimate confidence based on whether we got a meaningful response
        confidence = self._estimate_confidence(response_text, sql_query, source_tables, used_columns, output_columns, sql_result_preview)
        print(f"Estimated confidence: {confidence}")

        # Write results into context for downstream agents
        context.retrieval_response = response_text
        context.retrieval_confidence = confidence
        context.retrieval_sql_query = sql_query
        context.retrieval_tables = list(source_tables)
        context.retrieval_used_columns = list(used_columns)
        context.retrieval_output_columns = list(output_columns)
        context.retrieval_sql_result_preview = sql_result_preview

        logger.info(
            "agent.retrieval.completed",
            confidence=confidence,
            tables=source_tables,
            has_sql=sql_query is not None,
        )

        return AgentResult(
            agent_type=self.agent_type,
            status=AgentStatus.SUCCESS,
            response=response_text,
            confidence=confidence,
            metadata={
                "sql_query": sql_query,
                "source_tables": source_tables,
                "used_columns": used_columns,
                "output_columns": output_columns,
                "sql_result_preview": sql_result_preview,
                "top_k": retrieval_cfg.top_k,
            },
        )

    async def _get_or_build_engine(
        self,
        config_id: str,
        conn_string: str,
        collection_name: str,
        top_k: int,
        llm_model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ):
        """
        Get a cached query engine or build a new one.

        Engines are cached by config_id because building them involves
        connecting to SQL Server + loading Qdrant vectors, which is expensive.
        """
        cache_key = f"{config_id}:{top_k}:{llm_model}"

        if cache_key not in _engine_cache:
            logger.info("agent.retrieval.building_engine", config_id=config_id)
            engine = await self._vector_repo.build_query_engine(
                sql_connection_string=conn_string,
                collection_name=collection_name,
                top_k=top_k,
                llm_model=llm_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _engine_cache[cache_key] = engine

        return _engine_cache[cache_key]

    @staticmethod
    def _estimate_confidence(
        response: str,
        sql_query: Optional[str],
        tables: list[str],
        used_columns: list[str],
        output_columns: list[str],
        sql_result_preview: Optional[str],
    ) -> float:
        """
        Heuristic confidence score based on response quality signals.

        - Has SQL + tables found + substantial response → high confidence
        - No SQL generated → medium confidence (schema-only answer)
        - Empty or error response → low confidence
        """
        if not response or len(response.strip()) < 20:
            return 0.2

        score = 0.5  # Base score for having a response

        if sql_query and len(sql_query.strip()) > 10:
            score += 0.25  # SQL was generated

        if tables:
            score += min(0.15, len(tables) * 0.05)  # Tables were found
        
        if used_columns:
            score += min(0.1, len(used_columns) * 0.03)  # Columns were identified
        
        if output_columns:
            score += min(0.1, len(output_columns) * 0.03)  # Output columns identified

        if len(response) > 100:
            score += 0.1  # Substantial response
        
        if not sql_result_preview or sql_result_preview == "[]" or sql_result_preview == "None":
            print("No SQL result preview available, reducing confidence.")
            return 0.3

        return min(score, 1.0)


def clear_engine_cache(config_id: Optional[str] = None):
    """
    Clear cached query engines.
    Call after re-ingestion or config changes.
    """
    global _engine_cache
    if config_id:
        keys_to_remove = [k for k in _engine_cache if k.startswith(config_id)]
        for k in keys_to_remove:
            del _engine_cache[k]
    else:
        _engine_cache.clear()