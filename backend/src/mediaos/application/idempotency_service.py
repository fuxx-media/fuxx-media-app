"""PostgreSQL-serialized idempotency records for externally visible writes."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import IdempotencyConflictError
from mediaos.domain.models import IdempotencyRecord


def canonical_request_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyResult:
    response_status: int
    response_body: dict[str, Any]


async def acquire_idempotency(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    request_hash: str,
) -> IdempotencyResult | None:
    if not key or len(key) > 200:
        raise IdempotencyConflictError("A valid Idempotency-Key header is required")
    lock_key = f"{tenant_id}:{scope}:{key}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
    )
    record = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
    )
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise IdempotencyConflictError("Idempotency key was already used with a different request")
    return IdempotencyResult(record.response_status, record.response_body)


def record_idempotency(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
        )
    )
