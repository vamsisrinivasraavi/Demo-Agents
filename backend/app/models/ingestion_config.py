"""
Ingestion configuration document model.

Each record represents one SQL Server database that has been (or is being)
ingested into Qdrant.  Credentials are stored with the password encrypted
at the application layer before persistence.

The SQL connection string is reconstructed at query time by the
LlamaIndex engine builder in dependencies.py.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SQLConnectionConfig(BaseModel):
    """SQL Server connection parameters (stored per ingestion)."""

    host: str
    port: int = 1433
    database: str
    username: str
    encrypted_password: str  # Fernet-encrypted, never plaintext
    driver: str = "ODBC Driver 18 for SQL Server"
    trust_server_certificate: bool = True  # dev convenience; disable in prod

    def to_connection_string(self, decrypted_password: str) -> str:
        """Build a SQLAlchemy-compatible MSSQL connection string."""
        trust = "yes" if self.trust_server_certificate else "no"
        return (
            f"mssql+pyodbc://{self.username}:{decrypted_password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?driver={self.driver.replace(' ', '+')}"
            f"&TrustServerCertificate={trust}"
        )


class SchemaStats(BaseModel):
    """Summary stats captured after successful ingestion."""

    tables_count: int = 0
    columns_count: int = 0
    foreign_keys_count: int = 0
    indexes_count: int = 0
    views_count: int = 0


class IngestionConfigDocument(BaseModel):
    """
    MongoDB document for an ingestion configuration.

    Lifecycle:
    1. Admin submits SQL credentials → status=PENDING
    2. Ingestion service extracts schema → status=RUNNING
    3. Embeddings stored in Qdrant → status=COMPLETED / FAILED
    """

    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""

    # SQL Server connection
    sql_connection: SQLConnectionConfig

    # Qdrant target
    qdrant_collection: str = Field(..., min_length=1, max_length=100)

    # Embedding configuration
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # LlamaIndex settings
    chunk_strategy: str = "table_level"  # table_level | column_level | hybrid
    sql_top_k: int = 5

    # Ingestion state
    status: IngestionStatus = IngestionStatus.PENDING
    schema_stats: SchemaStats = Field(default_factory=SchemaStats)
    error_message: Optional[str] = None

    # Audit
    created_by: str = ""  # user_id
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=False, exclude={"id"})
        data["updated_at"] = _utc_now()
        return data