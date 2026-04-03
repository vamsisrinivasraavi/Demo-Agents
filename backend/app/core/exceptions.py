"""
Custom exception hierarchy.

Each exception maps to a specific HTTP status code and is caught by
the global exception handler in main.py. This keeps routers clean —
services raise domain exceptions, the handler translates to HTTP.
"""

from typing import Any, Optional


class AppException(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    detail: str = "Internal server error"
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: Optional[str] = None,
        error_code: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ):
        self.detail = detail or self.__class__.detail
        self.error_code = error_code or self.__class__.error_code
        self.context = context or {}
        super().__init__(self.detail)


# ──────────────────────────────────────────────
# Auth Exceptions (401, 403)
# ──────────────────────────────────────────────


class AuthenticationError(AppException):
    status_code = 401
    detail = "Could not validate credentials"
    error_code = "AUTH_FAILED"


class InvalidTokenError(AppException):
    status_code = 401
    detail = "Invalid or expired token"
    error_code = "INVALID_TOKEN"


class InsufficientPermissionsError(AppException):
    status_code = 403
    detail = "You do not have permission to perform this action"
    error_code = "FORBIDDEN"


# ──────────────────────────────────────────────
# Resource Exceptions (404, 409)
# ──────────────────────────────────────────────


class NotFoundError(AppException):
    status_code = 404
    detail = "Resource not found"
    error_code = "NOT_FOUND"


class ConflictError(AppException):
    status_code = 409
    detail = "Resource already exists"
    error_code = "CONFLICT"


# ──────────────────────────────────────────────
# Validation / Input (400, 422)
# ──────────────────────────────────────────────


class ValidationError(AppException):
    status_code = 422
    detail = "Validation error"
    error_code = "VALIDATION_ERROR"


class BadRequestError(AppException):
    status_code = 400
    detail = "Bad request"
    error_code = "BAD_REQUEST"


# ──────────────────────────────────────────────
# External Service Exceptions (502, 503)
# ──────────────────────────────────────────────


class ExternalServiceError(AppException):
    """Raised when an external dependency (OpenAI, Qdrant, SQL) fails."""

    status_code = 502
    detail = "External service error"
    error_code = "EXTERNAL_ERROR"


class SQLConnectionError(ExternalServiceError):
    detail = "Failed to connect to SQL Server"
    error_code = "SQL_CONNECTION_ERROR"


class VectorStoreError(ExternalServiceError):
    detail = "Vector store operation failed"
    error_code = "VECTOR_STORE_ERROR"


class EmbeddingError(ExternalServiceError):
    detail = "Embedding generation failed"
    error_code = "EMBEDDING_ERROR"


class LLMError(ExternalServiceError):
    detail = "LLM inference failed"
    error_code = "LLM_ERROR"


class ServiceUnavailableError(AppException):
    status_code = 503
    detail = "Service temporarily unavailable"
    error_code = "SERVICE_UNAVAILABLE"


# ──────────────────────────────────────────────
# Agent / Workflow Exceptions
# ──────────────────────────────────────────────


class WorkflowExecutionError(AppException):
    status_code = 500
    detail = "Workflow execution failed"
    error_code = "WORKFLOW_ERROR"


class AgentError(AppException):
    status_code = 500
    detail = "Agent execution failed"
    error_code = "AGENT_ERROR"


class GuardrailViolationError(AppException):
    status_code = 400
    detail = "Response blocked by safety guardrails"
    error_code = "GUARDRAIL_VIOLATION"