"""Observability: structured JSON logging + a request-logging middleware.

structlog renders one JSON line per request (method, path, status, latency, request id) to
stdout — friendly to `docker compose logs` and any log shipper. No secrets are logged.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    _configured = True


log = structlog.get_logger("anvil")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        dur_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            "request",
            rid=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=dur_ms,
        )
        response.headers["x-request-id"] = rid
        return response
