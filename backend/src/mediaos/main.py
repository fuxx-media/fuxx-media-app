"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mediaos import APP_NAME, APP_VERSION
from mediaos.api.health import router as health_router
from mediaos.api.phase_zero import router as phase_zero_router
from mediaos.application.errors import ApplicationError
from mediaos.config import get_frontend_origins
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Actor-Id", "X-Actor-Type"],
)
app.include_router(health_router)
app.include_router(phase_zero_router)


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    status_code = 404 if exc.code == "JOB_NOT_FOUND" else 409
    return JSONResponse(
        status_code=status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "correlation_id": str(uuid4()),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "details": {},
            "correlation_id": str(uuid4()),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": {"errors": exc.errors()},
            "correlation_id": str(uuid4()),
        },
    )
