"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mediaos import APP_NAME, APP_VERSION
from mediaos.api.health import router as health_router
from mediaos.database import close_engine
from mediaos.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield
    await close_engine()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(health_router)

