"""
Application configuration using Pydantic Settings.
All values are loaded from environment variables or .env file.
Grouped by service domain for clarity.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration. Every external service, secret, and tunable
    lives here — never scattered across modules.

    Pydantic Settings reads from env vars (case-insensitive) and .env file.
    Prefixed groups (MONGO_, REDIS_, etc.) keep the .env readable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ──────────────────────────────────────────────
    # Application
    # ──────────────────────────────────────────────
    APP_NAME: str = "Agent Demo Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"  # development | staging | production
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ──────────────────────────────────────────────
    # JWT / Auth
    # ──────────────────────────────────────────────
    JWT_SECRET_KEY: str = Field("", description="HMAC secret for JWT signing", env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")

    # ──────────────────────────────────────────────
    # MongoDB
    # ──────────────────────────────────────────────
    MONGO_URI: str = Field("", env="MONGO_URI")
    MONGO_DB_NAME: str = Field("", env="MONGO_DB_NAME")
    MONGO_MAX_POOL_SIZE: int = Field(50, env="MONGO_MAX_POOL_SIZE")
    MONGO_MIN_POOL_SIZE: int = Field(10, env="MONGO_MIN_POOL_SIZE")

    # ──────────────────────────────────────────────
    # Redis
    # ──────────────────────────────────────────────
    REDIS_URL: str = Field("", env="REDIS_URL")
    REDIS_MAX_CONNECTIONS: int = Field(20, env="REDIS_MAX_CONNECTIONS")
    REDIS_DEFAULT_TTL: int = Field(3600, env="REDIS_DEFAULT_TTL")  # seconds

    # ──────────────────────────────────────────────
    # LangCache
    # ──────────────────────────────────────────────
    LANG_CACHE_SERVICE_URL: Optional[str] = Field("https://aws-us-east-1.langcache.redis.io", env="LANG_CACHE_SERVICE_URL")  # If set, use LangCache service instead of Redis
    LANG_CACHE_ID: Optional[str] = Field("", env="LANG_CACHE_ID")
    LANG_CACHE_API_KEY: Optional[str] = Field("", env="LANG_CACHE_API_KEY")


    # ──────────────────────────────────────────────
    # Qdrant
    # ──────────────────────────────────────────────
    QDRANT_URI: str = Field("", env="QDRANT_URI")
    QDRANT_HOST: str = Field("localhost", env="QDRANT_HOST")
    QDRANT_PORT: int = Field(6333, env="QDRANT_PORT")
    QDRANT_API_KEY: Optional[str] = Field("", env="QDRANT_API_KEY")
    QDRANT_GRPC_PORT: int = Field(6334, env="QDRANT_GRPC_PORT")
    QDRANT_PREFER_GRPC: bool = Field(True, env="QDRANT_PREFER_GRPC")

    # ──────────────────────────────────────────────
    # OpenAI
    # ──────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key for embeddings + LLM", env="OPENAI_API_KEY")
    OPENAI_EMBEDDING_MODEL: str = Field("text-embedding-3-small", env="OPENAI_EMBEDDING_MODEL")
    OPENAI_EMBEDDING_DIMENSIONS: int = Field(1536, env="OPENAI_EMBEDDING_DIMENSIONS")
    OPENAI_LLM_MODEL: str = Field("gpt-4o", env="OPENAI_LLM_MODEL")
    OPENAI_LLM_TEMPERATURE: float = Field(0.2, env="OPENAI_LLM_TEMPERATURE")
    OPENAI_LLM_MAX_TOKENS: int = Field(1024, env="OPENAI_LLM_MAX_TOKENS")

    # ──────────────────────────────────────────────
    # SQL Server (default; overridden per-ingestion)
    # ──────────────────────────────────────────────
    SQL_DRIVER: str = Field("ODBC Driver 18 for SQL Server", env="SQL_DRIVER")

    # ──────────────────────────────────────────────
    # LlamaIndex
    # ──────────────────────────────────────────────
    LLAMA_INDEX_CHUNK_SIZE: int = Field(1024, env="LLAMA_INDEX_CHUNK_SIZE")
    LLAMA_INDEX_CHUNK_OVERLAP: int = Field(128, env="LLAMA_INDEX_CHUNK_OVERLAP")
    LLAMA_INDEX_SQL_TOP_K: int = Field(5, env="LLAMA_INDEX_SQL_TOP_K")  # tables to consider per query

    # ──────────────────────────────────────────────
    # MCP Tool Servers (web search + extensible)
    # ──────────────────────────────────────────────
    TAVILY_API_KEY: Optional[str] = Field("", env="TAVILY_API_KEY")       # Tavily MCP server
    BRAVE_SEARCH_API_KEY: Optional[str] = Field("", env="BRAVE_SEARCH_API_KEY")  # Brave Search MCP server
    MCP_TOOL_TIMEOUT: int = 30                  # seconds per MCP tool call

    # ──────────────────────────────────────────────
    # Rate Limiting
    # ──────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper


@lru_cache()
def get_settings() -> Settings:
    """
    Singleton settings instance — cached so env is read once.
    Call this via FastAPI's Depends() or import directly.
    """
    return Settings()