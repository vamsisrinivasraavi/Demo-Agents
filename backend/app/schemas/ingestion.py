"""
Ingestion request/response schemas.

The request accepts raw SQL credentials (password in plaintext over HTTPS),
which the service layer encrypts before storing in MongoDB.
The response never exposes the password.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.ingestion_config import IngestionStatus, SchemaStats


# ──────────────────────────────────────────────
# Requests
# ──────────────────────────────────────────────


class SQLConnectionRequest(BaseModel):
    """SQL Server connection details submitted by admin."""

    host: str = Field(..., examples=["localhost", "192.168.1.100"])
    port: int = Field(1433, ge=1, le=65535)
    database: str = Field(..., examples=["AdventureWorks"])
    username: str
    password: str = Field(..., min_length=1, description="Plaintext — encrypted before storage")
    driver: str = "ODBC Driver 18 for SQL Server"
    trust_server_certificate: bool = True


class CreateIngestionRequest(BaseModel):
    """Full ingestion config submitted by admin."""

    name: str = Field(..., min_length=1, max_length=200, examples=["Production ERP Schema"])
    description: str = ""

    # SQL connection
    sql_connection: SQLConnectionRequest

    # Qdrant target
    qdrant_collection: str = Field(
        ..., min_length=1, max_length=100,
        examples=["erp_schema_v1"],
        description="Qdrant collection name (created if doesn't exist)"
    )

    # Embedding config
    embedding_model: str = Field("text-embedding-3-small", examples=["text-embedding-3-small"])
    embedding_dimensions: int = Field(1536, examples=[1536, 3072])

    # LlamaIndex settings
    chunk_strategy: str = Field(
        "table_level",
        description="How to chunk schema: table_level | column_level | hybrid"
    )
    sql_top_k: int = Field(10, ge=1, le=20, description="Tables to retrieve per query")


class TestConnectionRequest(BaseModel):
    """Lightweight request to test SQL connectivity before full ingestion."""

    host: str
    port: int = 1433
    database: str
    username: str
    password: str
    driver: str = "ODBC Driver 18 for SQL Server"
    trust_server_certificate: bool = True


# ──────────────────────────────────────────────
# Responses
# ──────────────────────────────────────────────


class SQLConnectionResponse(BaseModel):
    """Sanitized SQL connection info — password is NEVER returned."""

    host: str
    port: int
    database: str
    username: str
    driver: str


class IngestionConfigResponse(BaseModel):
    """Ingestion config returned to the client."""

    id: str
    name: str
    description: str
    sql_connection: SQLConnectionResponse
    qdrant_collection: str
    embedding_model: str
    embedding_dimensions: int
    chunk_strategy: str
    sql_top_k: int
    status: IngestionStatus
    schema_stats: SchemaStats
    error_message: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class IngestionListResponse(BaseModel):
    """Paginated list of ingestion configs."""

    items: list[IngestionConfigResponse]
    total: int
    page: int
    page_size: int


class TestConnectionResponse(BaseModel):
    """Result of a SQL connectivity test."""

    success: bool
    message: str
    tables_found: int = 0
    sample_tables: list[str] = Field(default_factory=list, description="First 10 table names")