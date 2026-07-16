"""Phase 0.1 liveness and readiness routes."""

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from mediaos import APP_NAME, APP_PHASE, APP_VERSION
from mediaos.config import get_settings
from mediaos.database import database_ready

router = APIRouter(prefix="/api/v1", tags=["system"])


async def object_storage_ready() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(get_settings().minio_health_url)
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return False
    return True


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready() -> dict[str, object] | JSONResponse:
    postgres = await database_ready()
    minio = await object_storage_ready()
    payload: dict[str, object] = {
        "status": "ready" if postgres and minio else "not_ready",
        "dependencies": {"postgres": postgres, "minio": minio},
    }
    if not postgres or not minio:
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/version")
async def version() -> dict[str, str]:
    return {"name": APP_NAME, "version": APP_VERSION, "phase": APP_PHASE}

