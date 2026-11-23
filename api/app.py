"""Set up logging before importing anything else"""

import sentry_sdk

from api.constants import (
    CORS_ALLOWED_ORIGINS,
    DEPLOYMENT_MODE,
    ENABLE_TELEMETRY,
    SENTRY_DSN,
)
from api.logging_config import ENVIRONMENT, setup_logging

# Set up logging and get the listener for cleanup
setup_logging()


if SENTRY_DSN and (
    DEPLOYMENT_MODE != "oss" or (DEPLOYMENT_MODE == "oss" and ENABLE_TELEMETRY)
):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        environment=ENVIRONMENT,
    )
    print(f"Sentry initialized in environment: {ENVIRONMENT}")


from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.constants import REDIS_URL
from api.errors.mps import MPS_UNAVAILABLE_PUBLIC_MESSAGE, MPSUnavailableError
from api.mcp_server import mcp
from api.routes.main import router as main_router
from api.services.pipecat.prompt_cache import close_prompt_cache
from api.services.pipecat.recording_audio_cache import handle_recording_cache_sync
from api.services.pipecat.tracing_config import (
    handle_langfuse_sync,
    load_all_org_langfuse_credentials,
)
from api.services.pipecat.tts_cache.runtime import close_speech_cache
from api.services.saas.limits import PlanLimitExceeded
from api.services.worker_sync.manager import (
    WorkerSyncManager,
    set_worker_sync_manager,
)
from api.services.worker_sync.protocol import WorkerSyncEventType
from api.tasks.arq import get_arq_redis

API_PREFIX = "/api/v1"

mcp_app = mcp.http_app(path="/", stateless_http=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.lifespan(app):
        # warmup arq pool
        await get_arq_redis()

        # Enterprise operator mode: refuse insecure defaults, seed plans.
        from api.services.saas.startup import run_saas_startup_checks

        await run_saas_startup_checks()

        # Object store: SeaweedFS bucket on first start, files left on MinIO.
        from api.services.storage import startup_checks as storage_startup_checks

        await storage_startup_checks()

        # Pre-register all org-specific Langfuse exporters so they're ready
        # before any pipeline runs, without per-call DB lookups.
        await load_all_org_langfuse_credentials()

        # Start cross-worker sync manager so config changes propagate to all workers
        sync_manager = WorkerSyncManager(REDIS_URL)
        sync_manager.register(
            WorkerSyncEventType.LANGFUSE_CREDENTIALS, handle_langfuse_sync
        )
        sync_manager.register(
            WorkerSyncEventType.RECORDINGS, handle_recording_cache_sync
        )
        await sync_manager.start()
        set_worker_sync_manager(sync_manager)

        from api.services.observability import loop_exceptions, loop_lag, metrics
        from api.services.observability.call_events import (
            delivery as call_event_delivery,
        )

        call_event_delivery.start()

        # Event-loop lag gauge — per-pod saturation signal read off
        # /health/active-calls during autoscaling load tests.
        metrics.start()
        loop_lag.start()
        # Routes exceptions that escape tasks and timer callbacks; demotes one
        # known aioice teardown race and leaves everything else at ERROR.
        loop_exceptions.install()

        try:
            yield  # Run app
        finally:
            logger.info("Starting graceful shutdown...")
            from api.services.workflow.text_chat_stream import (
                finish_streaming_text_chat_turns,
            )

            await finish_streaming_text_chat_turns()
            await call_event_delivery.shutdown()
            try:
                await sync_manager.stop()
            finally:
                try:
                    try:
                        await close_speech_cache()
                    finally:
                        await close_prompt_cache()
                finally:
                    await loop_lag.stop()
                    metrics.stop()


app = FastAPI(
    title="NIMBORA API",
    description="API for the NIMBORA app",
    version="1.0.0",
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
    servers=[
        {"url": "https://app.nimbora.example", "description": "Production"},
        {"url": "http://localhost:8000", "description": "Local development"},
    ],
)


@app.exception_handler(MPSUnavailableError)
async def handle_mps_unavailable_error(
    _request: Request,
    _exc: MPSUnavailableError,
) -> JSONResponse:
    """Tell callers this is a NIMBORA outage, not invalid customer config."""

    return JSONResponse(
        status_code=503,
        content={"detail": MPS_UNAVAILABLE_PUBLIC_MESSAGE},
    )


@app.exception_handler(PlanLimitExceeded)
async def handle_plan_limit_exceeded(
    _request: Request,
    exc: PlanLimitExceeded,
) -> JSONResponse:
    """A SaaS plan limit (agents, seats...) blocks the requested creation."""

    return JSONResponse(
        status_code=402,
        content={"detail": str(exc), "error_code": "plan_limit_exceeded"},
    )


# Configure CORS.
# OSS is typically deployed with UI and API behind a single reverse proxy
# (same-origin, so CORS does not apply). Keep it permissive without
# credentials — wildcard + credentials is rejected by browsers and unsafe.
# SaaS deployments must set CORS_ALLOWED_ORIGINS to an explicit allowlist.
if DEPLOYMENT_MODE == "oss":
    cors_origins: list[str] = ["*"]
    cors_allow_credentials = False
else:
    if not CORS_ALLOWED_ORIGINS:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must be set to an explicit origin allowlist "
            "when DEPLOYMENT_MODE != 'oss'"
        )
    if "*" in CORS_ALLOWED_ORIGINS:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS cannot contain '*' with credentialed requests"
        )
    # NIMBORA Softphone (desktop and mobile apps) calls the API from the
    # webview's own origin, authenticated by its device token (no cookies).
    cors_origins = list(CORS_ALLOWED_ORIGINS) + [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]
    cors_allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Workflow-Run-Id"],
)


def _add_public_embed_cors_middleware() -> None:
    from api.routes.public_embed import PublicEmbedCORSMiddleware

    app.add_middleware(PublicEmbedCORSMiddleware, api_prefix=API_PREFIX)


_add_public_embed_cors_middleware()

api_router = APIRouter()

# include subrouters here
api_router.include_router(main_router)

# main router with api prefix
app.include_router(api_router, prefix=API_PREFIX)

# Mount the MCP server — agents reach it at /api/v1/mcp over Streamable HTTP,
# authenticating with the same X-API-Key header used by the REST API.
# Mounted under /api/v1 so existing reverse-proxy rules (nginx etc.) route it
# without any extra configuration.
app.mount(f"{API_PREFIX}/mcp", mcp_app)
