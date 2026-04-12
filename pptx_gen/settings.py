"""Runtime settings for the Auto-PPT API.

Centralizes env-backed configuration so deployment knobs are discoverable
from a single module rather than scattered across handlers. Intentionally
dependency-free (no pydantic-settings) to keep cold-start light.

Environment variables (all optional; sensible dev defaults when absent):

- AUTOPPT_CORS_ALLOWED_ORIGINS   Comma-separated list of allowed browser origins.
                                  Default: http://localhost:5173,http://127.0.0.1:5173
                                  Use "*" *only* when AUTOPPT_CORS_ALLOW_CREDENTIALS
                                  is false (browsers reject the combination).
- AUTOPPT_CORS_ALLOW_CREDENTIALS True/false. Default: true.
- AUTOPPT_MAX_UPLOAD_MB          Max request body size for /api/ingest in MB.
                                  Default: 50.
- AUTOPPT_LOG_LEVEL              Python logging level name. Default: INFO.
- AUTOPPT_LOG_JSON               "true" to emit structured JSON log records
                                  (request_id, path, duration_ms, status). Default: true.
- AUTOPPT_STORE_BACKEND          "memory" (default) or "sqlite".
- AUTOPPT_STORE_PATH             File path for SQLite DB when backend is "sqlite".
                                  Default: ./data/autoppt.db (relative to cwd).
- AUTOPPT_VECTOR_STORE_BACKEND   "disk" (default) or "memory" for Chroma.
- AUTOPPT_VECTOR_STORE_PATH      Directory for persistent Chroma collections when backend is "disk".
                                  Default: ./data/chroma (relative to cwd).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


_DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_origins(name: str) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(_DEFAULT_DEV_ORIGINS)
    items = [piece.strip() for piece in raw.split(",")]
    return [piece for piece in items if piece]


@dataclass(frozen=True, slots=True)
class Settings:
    cors_allowed_origins: list[str] = field(default_factory=lambda: list(_DEFAULT_DEV_ORIGINS))
    cors_allow_credentials: bool = True
    max_upload_bytes: int = 50 * 1024 * 1024
    log_level: str = "INFO"
    log_json: bool = True
    store_backend: str = "memory"
    store_path: str = "data/autoppt.db"
    vector_store_backend: str = "disk"
    vector_store_path: str = "data/chroma"

    @property
    def cors_safe_allow_credentials(self) -> bool:
        """Browsers reject Access-Control-Allow-Origin: * with credentials.
        Silently downgrade to False in that unsafe combination so the CORS
        preflight still works instead of failing opaquely at runtime.
        """
        if "*" in self.cors_allowed_origins and self.cors_allow_credentials:
            return False
        return self.cors_allow_credentials


def load_settings() -> Settings:
    return Settings(
        cors_allowed_origins=_env_origins("AUTOPPT_CORS_ALLOWED_ORIGINS"),
        cors_allow_credentials=_env_bool("AUTOPPT_CORS_ALLOW_CREDENTIALS", True),
        max_upload_bytes=_env_int("AUTOPPT_MAX_UPLOAD_MB", 50) * 1024 * 1024,
        log_level=os.environ.get("AUTOPPT_LOG_LEVEL", "INFO").upper(),
        log_json=_env_bool("AUTOPPT_LOG_JSON", True),
        store_backend=os.environ.get("AUTOPPT_STORE_BACKEND", "memory").strip().lower(),
        store_path=os.environ.get("AUTOPPT_STORE_PATH", "data/autoppt.db").strip(),
        vector_store_backend=os.environ.get("AUTOPPT_VECTOR_STORE_BACKEND", "disk").strip().lower(),
        vector_store_path=os.environ.get("AUTOPPT_VECTOR_STORE_PATH", "data/chroma").strip(),
    )


SETTINGS: Settings = load_settings()
