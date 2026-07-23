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
from mediaos.api.auth_routes import router as auth_router
from mediaos.api.health import router as health_router
from mediaos.api.phase_one import router as phase_one_router
from mediaos.api.phase_six import router as phase_six_router
from mediaos.api.phase_three import router as phase_three_router
from mediaos.api.phase_two import router as phase_two_router
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
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    allow_credentials=True,
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(phase_zero_router)
app.include_router(phase_one_router)
app.include_router(phase_two_router)
app.include_router(phase_three_router)
app.include_router(phase_six_router)


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    status_code = {
        "AUTHENTICATION_REQUIRED": 401,
        "INVALID_CREDENTIALS": 401,
        "FORBIDDEN": 403,
        "CSRF_VALIDATION_FAILED": 403,
        "TENANT_BOUNDARY_VIOLATION": 403,
        "JOB_NOT_FOUND": 404,
        "STORED_FILE_NOT_FOUND": 404,
        "UPLOAD_VALIDATION_FAILED": 422,
        "CHECKLIST_INCOMPLETE": 422,
        "PROVIDER_VALIDATION_FAILED": 422,
        "CALLBACK_VALIDATION_FAILED": 422,
        "PROVIDER_NOT_FOUND": 404,
        "EXECUTION_NOT_FOUND": 404,
        "MEDIA_NOT_FOUND": 404,
        "MEDIA_RIGHTS_FAILED": 422,
        "MEDIA_DELETION_BLOCKED": 422,
        "CALLBACK_REPLAY": 409,
    }.get(exc.code, 409)
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
