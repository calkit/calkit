"""Main FastAPI application and entry point for the Calkit Cloud backend."""

import logging
import os
import time
from collections.abc import Awaitable, Callable

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from git.exc import GitCommandError
from pythonjsonlogger import jsonlogger
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.config import settings

# Prometheus multiprocess mode requires its data dir to exist *before*
# prometheus_client is imported (which the instrumentator import below
# triggers). Create it here so this holds even if the startup script
# didn't pre-create it.
_prom_dir = os.environ.get(
    "PROMETHEUS_MULTIPROC_DIR", os.environ.get("prometheus_multiproc_dir")
)
if _prom_dir:
    os.makedirs(_prom_dir, exist_ok=True)

from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402

# Configure JSON logging so Loki can parse structured log lines. force=True
# is required: other modules (e.g. app.core) are imported before this runs
# and may have already attached a default plain-text handler to the root
# logger, which would make this basicConfig a silent no-op and break every
# Loki `| json` query.
handler = logging.StreamHandler()
handler.setFormatter(
    jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
)
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


class _SkipMetricsAccessLog(logging.Filter):
    """Drop uvicorn access-log lines for Prometheus /metrics scrapes.

    log_requests already skips /metrics for the app's own structured log,
    but uvicorn's access logger emits a line for every scrape (~every
    scrape_interval per backend), which is pure noise in Loki.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access record args: (client, method, path, http_ver, code)
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            return "/metrics" not in str(args[2])
        return "/metrics" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SkipMetricsAccessLog())

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    if route.tags:
        return f"{route.tags[0]}-{route.name}"
    return route.name


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# The library's default buckets for the per-handler latency histogram stop at
# 1s, which silently pins every quantile in Grafana to 1s or less. Plenty of
# handlers here clone or fetch Git repos and legitimately run longer, so extend
# the buckets far enough to see the real tail.
LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120)

Instrumentator(
    # A hung request never records a duration (that only happens on
    # completion), so without this gauge a stuck endpoint is invisible in
    # Grafana. With it, a hang shows up live as a non-zero in-progress count
    # for that handler.
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app, latency_lowr_buckets=LATENCY_BUCKETS).expose(app)


# High-frequency endpoints that would otherwise dominate log volume (and
# cost) without adding diagnostic value.
_LOG_SKIP_PATHS = {"/metrics"}


@app.middleware("http")
async def log_requests(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path in _LOG_SKIP_PATHS:
        return response
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(GitCommandError)
async def git_command_error_handler(
    request: Request, exc: GitCommandError
) -> JSONResponse:
    logger.error("Git command error: %s", exc.stderr or str(exc))
    stderr = (exc.stderr or "").lower()
    if "403" in stderr or "permission" in stderr or "denied" in stderr:
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Git remote denied permission. Possible causes: "
                    "you do not have write access to this repository, "
                    "or the Calkit GitHub app has not been granted access "
                    "to it."
                )
            },
        )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "A Git operation failed; check server logs for details."
        },
    )


app.include_router(api_router, prefix=settings.API_V1_STR)
