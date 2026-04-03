"""
Tests for /api/admin/* endpoints.

Covers:
- Ingestion: test connection, create, list, get, delete
- Workflows: create, list, get, update, delete
- Role enforcement: user cannot access admin endpoints
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


# ══════════════════════════════════════════════
# ROLE ENFORCEMENT
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_admin_endpoint_requires_admin_role(
    client: AsyncClient, user_token: str
):
    """Regular user should be rejected from admin endpoints."""
    resp = await client.get(
        "/api/admin/ingestion",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 403
    assert "FORBIDDEN" in resp.json()["error"]["code"]


@pytest.mark.asyncio
async def test_admin_endpoint_requires_auth(client: AsyncClient):
    """Unauthenticated request should be rejected."""
    resp = await client.get("/api/admin/ingestion")
    assert resp.status_code == 401


# ══════════════════════════════════════════════
# INGESTION: TEST CONNECTION
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_test_connection(client: AsyncClient, admin_token: str):
    """Test SQL connection endpoint accepts valid payload."""
    resp = await client.post(
        "/api/admin/ingestion/test",
        headers=auth_header(admin_token),
        json={
            "host": "localhost",
            "port": 1433,
            "database": "TestDB",
            "username": "sa",
            "password": "test_password",
        },
    )
    # Will fail to connect (no real SQL Server) but should not 500
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert "message" in data


# ══════════════════════════════════════════════
# INGESTION: CRUD
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_ingestion(client: AsyncClient, admin_token: str):
    """Create a new ingestion config."""
    resp = await client.post(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
        json={
            "name": "Test Ingestion",
            "description": "Test schema",
            "sql_connection": {
                "host": "localhost",
                "port": 1433,
                "database": "TestDB",
                "username": "sa",
                "password": "test_password",
            },
            "qdrant_collection": "test_collection_v1",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
            "chunk_strategy": "table_level",
            "sql_top_k": 5,
        },
    )
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "Test Ingestion"
    assert data["qdrant_collection"] == "test_collection_v1"
    assert data["status"] in ("completed", "pending", "running")
    assert "id" in data

    # Password should NOT be in the response
    assert "password" not in str(data["sql_connection"])
    assert "encrypted_password" not in str(data["sql_connection"])


@pytest.mark.asyncio
async def test_list_ingestion_configs(client: AsyncClient, admin_token: str):
    """List ingestion configs for the admin."""
    # Create one first
    await client.post(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
        json={
            "name": "List Test",
            "sql_connection": {
                "host": "localhost", "port": 1433,
                "database": "DB", "username": "sa", "password": "pw",
            },
            "qdrant_collection": "list_test_v1",
        },
    )

    resp = await client.get(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
async def test_get_ingestion_config(client: AsyncClient, admin_token: str):
    """Fetch a specific ingestion config."""
    create_resp = await client.post(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
        json={
            "name": "Get Test",
            "sql_connection": {
                "host": "localhost", "port": 1433,
                "database": "DB", "username": "sa", "password": "pw",
            },
            "qdrant_collection": "get_test_v1",
        },
    )
    config_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/admin/ingestion/{config_id}",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == config_id
    assert resp.json()["name"] == "Get Test"


@pytest.mark.asyncio
async def test_get_ingestion_config_not_found(client: AsyncClient, admin_token: str):
    """Non-existent config should return 404."""
    resp = await client.get(
        "/api/admin/ingestion/000000000000000000000000",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_ingestion_config(client: AsyncClient, admin_token: str):
    """Delete an ingestion config and its Qdrant collection."""
    create_resp = await client.post(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
        json={
            "name": "Delete Test",
            "sql_connection": {
                "host": "localhost", "port": 1433,
                "database": "DB", "username": "sa", "password": "pw",
            },
            "qdrant_collection": "delete_test_v1",
        },
    )
    config_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/ingestion/{config_id}",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ══════════════════════════════════════════════
# WORKFLOWS: CRUD
# ══════════════════════════════════════════════


async def _create_ingestion_config(client: AsyncClient, token: str) -> str:
    """Helper: create an ingestion config and return its ID."""
    resp = await client.post(
        "/api/admin/ingestion",
        headers=auth_header(token),
        json={
            "name": "For Workflow",
            "sql_connection": {
                "host": "localhost", "port": 1433,
                "database": "DB", "username": "sa", "password": "pw",
            },
            "qdrant_collection": f"wf_test_{id(token)[-6:]}",
        },
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_workflow(client: AsyncClient, admin_token: str):
    """Create a workflow linked to an ingestion config."""
    config_id = await _create_ingestion_config(client, admin_token)

    resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Test Workflow",
            "description": "A test workflow",
            "ingestion_config_id": config_id,
            "agents": [
                {"type": "retrieval", "enabled": True, "config": {"top_k": 5}},
                {"type": "web_search", "enabled": True, "config": {}},
                {"type": "guardrail", "enabled": True, "config": {}},
            ],
            "model_settings": {
                "model": "gpt-4o",
                "temperature": 0.2,
                "max_tokens": 1024,
            },
            "feature_flags": {
                "enable_cache": True,
                "cache_ttl_seconds": 3600,
            },
        },
    )
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "Test Workflow"
    assert data["ingestion_config_id"] == config_id
    assert len(data["agents"]) == 3
    assert data["feature_flags"]["enable_cache"] is True
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_workflow_missing_retrieval(client: AsyncClient, admin_token: str):
    """Workflow without retrieval agent should be rejected."""
    config_id = await _create_ingestion_config(client, admin_token)

    resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Bad Workflow",
            "ingestion_config_id": config_id,
            "agents": [
                {"type": "web_search", "enabled": True},
            ],
        },
    )
    assert resp.status_code == 400
    assert "retrieval" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_create_workflow_invalid_config(client: AsyncClient, admin_token: str):
    """Workflow with non-existent ingestion config should be rejected."""
    resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Orphan Workflow",
            "ingestion_config_id": "000000000000000000000000",
            "agents": [{"type": "retrieval", "enabled": True}],
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_workflows(client: AsyncClient, admin_token: str):
    """List workflows for admin."""
    resp = await client.get(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_update_workflow(client: AsyncClient, admin_token: str):
    """Partial update of a workflow."""
    config_id = await _create_ingestion_config(client, admin_token)

    create_resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Update Me",
            "ingestion_config_id": config_id,
            "agents": [{"type": "retrieval", "enabled": True}],
        },
    )
    wf_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/admin/workflows/{wf_id}",
        headers=auth_header(admin_token),
        json={
            "name": "Updated Name",
            "feature_flags": {"enable_cache": False, "cache_ttl_seconds": 1800},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["feature_flags"]["enable_cache"] is False


@pytest.mark.asyncio
async def test_delete_workflow(client: AsyncClient, admin_token: str):
    """Soft-delete a workflow."""
    config_id = await _create_ingestion_config(client, admin_token)

    create_resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Delete Me",
            "ingestion_config_id": config_id,
            "agents": [{"type": "retrieval", "enabled": True}],
        },
    )
    wf_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/workflows/{wf_id}",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200