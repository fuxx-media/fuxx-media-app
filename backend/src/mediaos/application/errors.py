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
