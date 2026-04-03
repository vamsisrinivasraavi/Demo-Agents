"""
Workflow service.

Manages workflow CRUD and validates references
(ingestion config must exist and be COMPLETED).
"""

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.models.ingestion_config import IngestionStatus
from app.models.workflow import (
    AgentConfig,
    AgentType,
    FeatureFlags,
    ModelSettings,
    RetrievalAgentConfig,
    WebSearchAgentConfig,
    GuardrailAgentConfig,
)
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.schemas.workflow import (
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowResponse,
)

logger = get_logger(__name__)


class WorkflowService:
    def __init__(
        self,
        workflow_repo: WorkflowRepository,
        config_repo: IngestionConfigRepository,
    ):
        self._workflow_repo = workflow_repo
        self._config_repo = config_repo

    async def create_workflow(
        self,
        request: CreateWorkflowRequest,
        user_id: str,
    ) -> WorkflowResponse:
        """Create a new workflow. Validates that the ingestion config exists and is completed."""
        # Validate ingestion config
        config = await self._config_repo.find_by_id(request.ingestion_config_id)
        if config is None:
            raise NotFoundError(
                detail=f"Ingestion config '{request.ingestion_config_id}' not found"
            )
        if config.get("status") != IngestionStatus.COMPLETED:
            raise BadRequestError(
                detail=f"Ingestion config must be COMPLETED, current status: {config.get('status')}"
            )

        # Validate agent pipeline has at least retrieval agent
        agent_types = [a.type for a in request.agents]
        if AgentType.RETRIEVAL not in agent_types:
            raise BadRequestError(detail="Workflow must include a retrieval agent")

        # Build workflow document
        workflow_data = {
            "name": request.name,
            "description": request.description,
            "ingestion_config_id": request.ingestion_config_id,
            "agents": [a.model_dump() for a in request.agents],
            "model_settings": request.model_settings.model_dump(),
            "feature_flags": request.feature_flags.model_dump(),
            "is_active": True,
            "created_by": user_id,
        }

        workflow_id = await self._workflow_repo.create_workflow(workflow_data)
        logger.info("workflow.created", workflow_id=workflow_id, name=request.name)

        return await self.get_workflow(workflow_id)

    async def get_workflow(self, workflow_id: str) -> WorkflowResponse:
        """Fetch a single workflow by ID."""
        doc = await self._workflow_repo.find_by_id(workflow_id)
        if doc is None:
            raise NotFoundError(detail=f"Workflow '{workflow_id}' not found")
        return self._to_response(doc)

    async def update_workflow(
        self,
        workflow_id: str,
        request: UpdateWorkflowRequest,
    ) -> WorkflowResponse:
        """Partial update of a workflow."""
        existing = await self._workflow_repo.find_by_id(workflow_id)
        if existing is None:
            raise NotFoundError(detail=f"Workflow '{workflow_id}' not found")

        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.description is not None:
            updates["description"] = request.description
        if request.agents is not None:
            updates["agents"] = [a.model_dump() for a in request.agents]
        if request.model_settings is not None:
            updates["model_settings"] = request.model_settings.model_dump()
        if request.feature_flags is not None:
            updates["feature_flags"] = request.feature_flags.model_dump()
        if request.is_active is not None:
            updates["is_active"] = request.is_active

        await self._workflow_repo.partial_update(workflow_id, updates)
        logger.info("workflow.updated", workflow_id=workflow_id)

        return await self.get_workflow(workflow_id)

    async def list_workflows_for_admin(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowListResponse:
        """List workflows created by an admin."""
        skip = (page - 1) * page_size
        docs = await self._workflow_repo.find_by_user(
            user_id, active_only=False, skip=skip, limit=page_size
        )
        total = await self._workflow_repo.count_by_user(user_id, active_only=False)

        return WorkflowListResponse(
            items=[self._to_list_item(d) for d in docs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_active_workflows(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowListResponse:
        """List all active workflows (for users)."""
        skip = (page - 1) * page_size
        docs = await self._workflow_repo.find_active_workflows(skip=skip, limit=page_size)
        total = await self._workflow_repo.count_active()

        return WorkflowListResponse(
            items=[self._to_list_item(d) for d in docs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Soft-delete a workflow by deactivating it."""
        existing = await self._workflow_repo.find_by_id(workflow_id)
        if existing is None:
            raise NotFoundError(detail=f"Workflow '{workflow_id}' not found")

        return await self._workflow_repo.partial_update(
            workflow_id, {"is_active": False}
        )

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _to_response(doc: dict) -> WorkflowResponse:
        agents = [AgentConfig(**a) for a in doc.get("agents", [])]
        return WorkflowResponse(
            id=doc["_id"],
            name=doc["name"],
            description=doc.get("description", ""),
            ingestion_config_id=doc["ingestion_config_id"],
            agents=agents,
            model_settings=ModelSettings(**doc.get("model_settings", {})),
            feature_flags=FeatureFlags(**doc.get("feature_flags", {})),
            is_active=doc.get("is_active", True),
            created_by=doc.get("created_by", ""),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def _to_list_item(doc: dict) -> WorkflowListItem:
        flags = doc.get("feature_flags", {})
        return WorkflowListItem(
            id=doc["_id"],
            name=doc["name"],
            description=doc.get("description", ""),
            ingestion_config_id=doc.get("ingestion_config_id", ""),
            is_active=doc.get("is_active", True),
            agent_count=len(doc.get("agents", [])),
            cache_enabled=flags.get("enable_cache", False),
            created_at=doc["created_at"],
        )