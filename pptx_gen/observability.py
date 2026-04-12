"""Logging + request-id middleware for the Auto-PPT API.

Keeps log lines machine-parseable so they can be grepped or shipped to a log
aggregator without custom parsers. Every request gets a stable request_id
(from the incoming X-Request-ID header if present, otherwise generated)
which is echoed back on the response and included in the access log.
"""

from __future__ import annotations

import contextvars
import hmac
import json
import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from pptx_gen.settings import SETTINGS


REQUEST_ID_HEADER = "X-Request-ID"
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "autoppt_request_id", default=None
)
_STANDARD_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def current_request_id() -> str | None:
    return _request_id_var.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or current_request_id()
        if rid:
            payload["request_id"] = rid
        for key in ("path", "method", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure the root logger once per process.

    Safe to call multiple times; subsequent calls reconfigure handlers
    rather than stacking them.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if SETTINGS.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(SETTINGS.log_level)


_AUTH_HEADER = "Authorization"
_API_KEY_HEADER = "X-API-Key"
_HEALTH_PATH = "/api/health"


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Enforce AUTOPPT_API_KEY on all endpoints except /api/health.

    Accepts the key in either of:
      Authorization: Bearer <key>
      X-API-Key: <key>

    When SETTINGS.api_key is None the middleware is a no-op — local dev
    servers can run without setting any key.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if SETTINGS.api_key is None:
            return await call_next(request)
        if request.url.path == _HEALTH_PATH:
            return await call_next(request)

        provided: str | None = None
        auth_header = request.headers.get(_AUTH_HEADER, "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
        if not provided:
            provided = request.headers.get(_API_KEY_HEADER, "").strip() or None

        if not provided or not hmac.compare_digest(provided, SETTINGS.api_key):
            request_id = current_request_id() or uuid4().hex[:16]
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "unauthorized",
                        "message": "Missing or invalid API key.",
                        "request_id": request_id,
                    }
                },
                headers={REQUEST_ID_HEADER: request_id},
            )

        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign a request_id to every request and log a single access line."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._logger = logging.getLogger("pptx_gen.access")

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid4().hex[:16]
        token = _request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            _request_id_var.reset(token)
