"""
Admin router — schema ingestion, workflow management, agent configuration.

All endpoints require admin role (enforced via require_role dependency).
Services are constructed per-request with full DI chain:
    Router → Service → Repository → MongoDB/Qdrant/Redis
"""

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import (
    get_cache_repo,
    get_current_user,
    get_mongo_db,
    get_vector_repo,
    require_role,
)
from app.core.security import TokenPayload, UserRole
from app.repositories.cache_repo import CacheRepository
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.vector_repo import VectorRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.schemas.ingestion import (
    CreateIngestionRequest,
    IngestionConfigResponse,
    IngestionListResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.schemas.workflow import (
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowListResponse,
    WorkflowResponse,
)
from app.services.ingestion_service import IngestionService
from app.services.workflow_service import WorkflowService

router = APIRouter()


# ──────────────────────────────────────────────
# Dependencies: build services per request
# ──────────────────────────────────────────────


async def _get_ingestion_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    vector_repo: VectorRepository = Depends(get_vector_repo),
) -> IngestionService:
    return IngestionService(
        config_repo=IngestionConfigRepository(db),
        vector_repo=vector_repo,
    )


async def _get_workflow_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
) -> WorkflowService:
    return WorkflowService(
        workflow_repo=WorkflowRepository(db),
        config_repo=IngestionConfigRepository(db),
    )


# ══════════════════════════════════════════════
# INGESTION ENDPOINTS
# ══════════════════════════════════════════════


@router.post(
    "/ingestion/test-connection",
    response_model=TestConnectionResponse,
    summary="Test SQL Server connectivity",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def test_sql_connection(
    request: TestConnectionRequest,
    ingestion_service: IngestionService = Depends(_get_ingestion_service),
):
    """
    Lightweight connectivity check before committing to full ingestion.
    Returns table count and sample table names on success.
    """
    return await ingestion_service.test_connection(request)


@router.post(
    "/ingestion",
    response_model=IngestionConfigResponse,
    status_code=201,
    summary="Ingest SQL schema into Qdrant",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def ingest_schema(
    request: CreateIngestionRequest,
    current_user: TokenPayload = Depends(get_current_user),
    ingestion_service: IngestionService = Depends(_get_ingestion_service),
):
    """
    Full schema ingestion pipeline:
    1. Connect to SQL Server
    2. Extract schema (tables, columns, FKs, indexes)
    3. Build LlamaIndex ObjectIndex with QdrantVectorStore
    4. Auto-embed + store in Qdrant

    Returns the ingestion config with status and schema stats.
    """
    return await ingestion_service.ingest_schema(request, user_id=current_user.sub)


@router.get(
    "/ingestion",
    response_model=IngestionListResponse,
    summary="List ingestion configs",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def list_ingestion_configs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenPayload = Depends(get_current_user),
    ingestion_service: IngestionService = Depends(_get_ingestion_service),
):
    """List all ingestion configs created by the current admin."""
    return await ingestion_service.list_configs(
        user_id=current_user.sub, page=page, page_size=page_size
    )


@router.get(
    "/ingestion/{config_id}",
    response_model=IngestionConfigResponse,
    summary="Get ingestion config details",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def get_ingestion_config(
    config_id: str,
    ingestion_service: IngestionService = Depends(_get_ingestion_service),
):
    """Fetch a single ingestion config with status and schema stats."""
    return await ingestion_service.get_config(config_id)


@router.delete(
    "/ingestion/{config_id}",
    summary="Delete ingestion config and Qdrant collection",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_ingestion_config(
    config_id: str,
    ingestion_service: IngestionService = Depends(_get_ingestion_service),
):
    """Delete an ingestion config and its associated Qdrant collection."""
    await ingestion_service.delete_config(config_id)
    return {"status": "deleted", "config_id": config_id}


# ══════════════════════════════════════════════
# WORKFLOW ENDPOINTS
# ══════════════════════════════════════════════


@router.post(
    "/workflows",
    response_model=WorkflowResponse,
    status_code=201,
    summary="Create a new workflow",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_workflow(
    request: CreateWorkflowRequest,
    current_user: TokenPayload = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """
    Create a workflow that defines the agent pipeline:
    - Select an ingestion config (must be COMPLETED)
    - Configure agents (retrieval, web search, guardrail)
    - Set model parameters (model, temperature, max_tokens)
    - Toggle feature flags (cache, streaming, history)
    """
    return await workflow_service.create_workflow(request, user_id=current_user.sub)


@router.get(
    "/workflows",
    response_model=WorkflowListResponse,
    summary="List admin's workflows",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def list_admin_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenPayload = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """List all workflows created by the current admin (including inactive)."""
    return await workflow_service.list_workflows_for_admin(
        user_id=current_user.sub, page=page, page_size=page_size
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Get workflow details",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def get_workflow(
    workflow_id: str,
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """Fetch full workflow config including agent pipeline and flags."""
    return await workflow_service.get_workflow(workflow_id)


@router.patch(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Update a workflow",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """
    Partial update of a workflow.
    Only provided fields are updated — omitted fields remain unchanged.
    """
    return await workflow_service.update_workflow(workflow_id, request)


@router.delete(
    "/workflows/{workflow_id}",
    summary="Deactivate a workflow",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_workflow(
    workflow_id: str,
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """Soft-delete a workflow by deactivating it. Users can no longer see it."""
    await workflow_service.delete_workflow(workflow_id)
    return {"status": "deactivated", "workflow_id": workflow_id}


# ══════════════════════════════════════════════
# CACHE MANAGEMENT
# ══════════════════════════════════════════════


@router.delete(
    "/workflows/{workflow_id}/cache",
    summary="Invalidate all cache entries for a workflow",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def invalidate_workflow_cache(
    workflow_id: str,
    cache_repo: CacheRepository = Depends(get_cache_repo),
):
    """Clear all cached responses for a workflow. Use after re-ingestion."""
    deleted = await cache_repo.invalidate_workflow(workflow_id)
    return {"status": "invalidated", "workflow_id": workflow_id, "entries_cleared": deleted}