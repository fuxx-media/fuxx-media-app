"""Environment-backed secret resolution; databases retain references only."""

import os

from mediaos.domain.models import SecretReference


class SecretResolutionError(RuntimeError):
    pass


class EnvironmentSecretResolver:
    def resolve(self, reference: SecretReference) -> str:
        if not reference.active:
            raise SecretResolutionError("Secret reference is inactive")
        value = os.getenv(reference.environment_variable)
        if not value:
            raise SecretResolutionError(
                f"Secret reference {reference.name!r} is unavailable in the runtime environment"
            )
        return value
