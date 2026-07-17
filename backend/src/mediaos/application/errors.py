"""Stable application errors exposed through the API envelope."""

from typing import Any


class ApplicationError(Exception):
    code = "APPLICATION_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class JobNotFoundError(ApplicationError):
    code = "JOB_NOT_FOUND"


class VersionConflictError(ApplicationError):
    code = "VERSION_CONFLICT"


class InvalidStateTransitionError(ApplicationError):
    code = "INVALID_STATE_TRANSITION"


class BudgetLimitExceededError(ApplicationError):
    code = "BUDGET_LIMIT_EXCEEDED"


class StatePrerequisiteError(ApplicationError):
    code = "STATE_PREREQUISITE_FAILED"


class AuthenticationError(ApplicationError):
    code = "AUTHENTICATION_REQUIRED"


class InvalidCredentialsError(ApplicationError):
    code = "INVALID_CREDENTIALS"


class AuthorizationError(ApplicationError):
    code = "FORBIDDEN"


class CsrfError(ApplicationError):
    code = "CSRF_VALIDATION_FAILED"


class TenantBoundaryError(ApplicationError):
    code = "TENANT_BOUNDARY_VIOLATION"


class IdempotencyConflictError(ApplicationError):
    code = "IDEMPOTENCY_CONFLICT"


class UploadValidationError(ApplicationError):
    code = "UPLOAD_VALIDATION_FAILED"


class StoredFileNotFoundError(ApplicationError):
    code = "STORED_FILE_NOT_FOUND"


class ClaimConflictError(ApplicationError):
    code = "CLAIM_CONFLICT"


class ApprovalConflictError(ApplicationError):
    code = "APPROVAL_CONFLICT"


class ChecklistIncompleteError(ApplicationError):
    code = "CHECKLIST_INCOMPLETE"


class ProviderValidationError(ApplicationError):
    code = "PROVIDER_VALIDATION_FAILED"


class ProviderNotFoundError(ApplicationError):
    code = "PROVIDER_NOT_FOUND"


class ExecutionNotFoundError(ApplicationError):
    code = "EXECUTION_NOT_FOUND"


class CallbackValidationError(ApplicationError):
    code = "CALLBACK_VALIDATION_FAILED"


class CallbackReplayError(ApplicationError):
    code = "CALLBACK_REPLAY"
