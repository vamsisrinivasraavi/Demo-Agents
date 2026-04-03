"""
Tests for /api/user/* endpoints.

Covers:
- List active workflows (user view)
- Chat: send message, new session, continue session
- Sessions: list, get full conversation
- Auth enforcement
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


# ──────────────────────────────────────────────
# Helper: Seed a workflow for chat testing
# ──────────────────────────────────────────────


async def _seed_workflow(client: AsyncClient, admin_token: str) -> str:
    """Create an ingestion config + workflow, return workflow_id."""
    # Create ingestion config
    ing_resp = await client.post(
        "/api/admin/ingestion",
        headers=auth_header(admin_token),
        json={
            "name": "Chat Test DB",
            "sql_connection": {
                "host": "localhost", "port": 1433,
                "database": "ChatDB", "username": "sa", "password": "pw",
            },
            "qdrant_collection": "chat_test_collection",
        },
    )
    config_id = ing_resp.json()["id"]

    # Create workflow
    wf_resp = await client.post(
        "/api/admin/workflows",
        headers=auth_header(admin_token),
        json={
            "name": "Chat Test Workflow",
            "ingestion_config_id": config_id,
            "agents": [
                {"type": "retrieval", "enabled": True, "config": {"top_k": 3}},
                {
                    "type": "web_search",
                    "enabled": True,
                    "config": {"trigger_on_low_confidence": True, "confidence_threshold": 0.6},
                },
                {"type": "guardrail", "enabled": True, "config": {}},
            ],
            "feature_flags": {"enable_cache": True, "cache_ttl_seconds": 600},
        },
    )
    return wf_resp.json()["id"]


# ══════════════════════════════════════════════
# WORKFLOW LISTING (User View)
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_active_workflows(
    client: AsyncClient, admin_token: str, user_token: str
):
    """User can list active workflows."""
    await _seed_workflow(client, admin_token)

    resp = await client.get(
        "/api/user/workflows",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "items" in data
    assert data["total"] >= 1
    assert data["items"][0]["is_active"] is True


@pytest.mark.asyncio
async def test_list_workflows_requires_auth(client: AsyncClient):
    """Unauthenticated request should be rejected."""
    resp = await client.get("/api/user/workflows")
    assert resp.status_code == 401


# ══════════════════════════════════════════════
# CHAT: SEND MESSAGE
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chat_new_session(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Send a message without session_id → creates new session."""
    wf_id = await _seed_workflow(client, admin_token)

    resp = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "What tables reference the Orders table?"},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "session_id" in data
    assert data["workflow_id"] == wf_id
    assert data["message"]["role"] == "assistant"
    assert len(data["message"]["content"]) > 0
    assert data["message_count"] == 2  # user + assistant


@pytest.mark.asyncio
async def test_chat_response_metadata(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Chat response should include rich metadata."""
    wf_id = await _seed_workflow(client, admin_token)

    resp = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "Show me the schema for the customers table"},
    )
    data = resp.json()
    msg = data["message"]

    # Metadata fields should be present
    assert "confidence_score" in msg
    assert "latency_ms" in msg
    assert "sql_query" in msg
    assert "tables_referenced" in msg
    assert isinstance(msg["agent_trace"], list)


@pytest.mark.asyncio
async def test_chat_continue_session(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Send a follow-up message to an existing session."""
    wf_id = await _seed_workflow(client, admin_token)

    # First message — creates session
    resp1 = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "What tables exist?"},
    )
    session_id = resp1.json()["session_id"]
    assert resp1.json()["message_count"] == 2

    # Follow-up message — continues session
    resp2 = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={
            "message": "Tell me more about the orders table",
            "session_id": session_id,
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["session_id"] == session_id
    assert resp2.json()["message_count"] == 4  # 2 pairs now


@pytest.mark.asyncio
async def test_chat_invalid_workflow(client: AsyncClient, user_token: str):
    """Chat with non-existent workflow should fail."""
    resp = await client.post(
        "/api/user/workflows/000000000000000000000000/chat",
        headers=auth_header(user_token),
        json={"message": "Hello"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient):
    """Unauthenticated chat should be rejected."""
    resp = await client.post(
        "/api/user/workflows/some_id/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_empty_message(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Empty message should be rejected by Pydantic validation."""
    wf_id = await _seed_workflow(client, admin_token)

    resp = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": ""},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════
# SESSIONS: LIST & GET
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_sessions(
    client: AsyncClient, admin_token: str, user_token: str
):
    """List user's chat sessions."""
    wf_id = await _seed_workflow(client, admin_token)

    # Create a session by chatting
    await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "Session list test"},
    )

    resp = await client.get(
        "/api/user/sessions",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "items" in data
    assert data["total"] >= 1
    assert "workflow_id" in data["items"][0]
    assert "message_count" in data["items"][0]


@pytest.mark.asyncio
async def test_list_sessions_filter_by_workflow(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Filter sessions by workflow_id."""
    wf_id = await _seed_workflow(client, admin_token)

    await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "Filter test"},
    )

    resp = await client.get(
        f"/api/user/sessions?workflow_id={wf_id}",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["workflow_id"] == wf_id


@pytest.mark.asyncio
async def test_get_session_detail(
    client: AsyncClient, admin_token: str, user_token: str
):
    """Load full session with all messages."""
    wf_id = await _seed_workflow(client, admin_token)

    chat_resp = await client.post(
        f"/api/user/workflows/{wf_id}/chat",
        headers=auth_header(user_token),
        json={"message": "Detail test query"},
    )
    session_id = chat_resp.json()["session_id"]

    resp = await client.get(
        f"/api/user/sessions/{session_id}",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["id"] == session_id
    assert len(data["messages"]) == 2  # user + assistant
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Detail test query"
    assert data["messages"][1]["role"] == "assistant"
    assert len(data["messages"][1]["content"]) > 0


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient, user_token: str):
    """Non-existent session should return 404."""
    resp = await client.get(
        "/api/user/sessions/000000000000000000000000",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Health endpoint should return 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"