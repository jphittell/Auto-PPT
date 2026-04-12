"""Runtime settings for the Auto-PPT API.

Centralizes env-backed configuration so deployment knobs are discoverable
from a single module rather than scattered across handlers. Intentionally
dependency-free (no pydantic-settings) to keep cold-start light.

Environment variables (all optional; sensible dev defaults when absent):

- AUTOPPT_API_KEY                Static bearer token required on all non-health endpoints.
                                  Omit (or leave unset) to disable auth entirely for local dev.
                                  Use a randomly generated 32-byte hex value in production:
                                    python -c "import secrets; print(secrets.token_hex(32))"
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
- AUTOPPT_WARM_EMBEDDER_ON_STARTUP
                                 True/false. Default: true.
                                 When true, preload the sentence-transformer model during API startup
                                 so the first upload does not pay the cold-start cost.
- AUTOPPT_TRUSTED_PROXY_IPS      Comma-separated list of reverse-proxy IP addresses whose
                                  X-Forwarded-For header is trusted for rate-limiting.
                                  Default: empty (X-Forwarded-For is never trusted).
                                  Example: 10.0.0.1,10.0.0.2
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

_settings_log = logging.getLogger("pptx_gen.settings")


_DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, min_val: int | None = None) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    stripped = raw.strip()
    try:
        value = int(stripped)
    except ValueError:
        _settings_log.warning(
            "settings_env_int_invalid: %s=%r is not an integer — using default %d",
            name, stripped, default,
        )
        return default
    if min_val is not None and value < min_val:
        _settings_log.warning(
            "settings_env_int_out_of_range: %s=%d is below minimum %d — using default %d",
            name, value, min_val, default,
        )
        return default
    return value


def _env_proxy_ips(name: str) -> frozenset[str]:
    raw = os.environ.get(name)
    if not raw:
        return frozenset()
    return frozenset(piece.strip() for piece in raw.split(",") if piece.strip())


def _env_origins(name: str) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(_DEFAULT_DEV_ORIGINS)
    items = [piece.strip() for piece in raw.split(",")]
    return [piece for piece in items if piece]


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str | None = None          # None → auth disabled (localhost dev mode)
    cors_allowed_origins: list[str] = field(default_factory=lambda: list(_DEFAULT_DEV_ORIGINS))
    cors_allow_credentials: bool = True
    max_upload_bytes: int = 50 * 1024 * 1024
    log_level: str = "INFO"
    log_json: bool = True
    store_backend: str = "memory"
    store_path: str = "data/autoppt.db"
    vector_store_backend: str = "disk"
    vector_store_path: str = "data/chroma"
    warm_embedder_on_startup: bool = True
    trusted_proxy_ips: frozenset[str] = field(default_factory=frozenset)  # IPs allowed to set X-Forwarded-For

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
        api_key=os.environ.get("AUTOPPT_API_KEY") or None,
        cors_allowed_origins=_env_origins("AUTOPPT_CORS_ALLOWED_ORIGINS"),
        cors_allow_credentials=_env_bool("AUTOPPT_CORS_ALLOW_CREDENTIALS", True),
        max_upload_bytes=_env_int("AUTOPPT_MAX_UPLOAD_MB", 50, min_val=1) * 1024 * 1024,
        log_level=os.environ.get("AUTOPPT_LOG_LEVEL", "INFO").upper(),
        log_json=_env_bool("AUTOPPT_LOG_JSON", True),
        store_backend=os.environ.get("AUTOPPT_STORE_BACKEND", "memory").strip().lower(),
        store_path=os.environ.get("AUTOPPT_STORE_PATH", "data/autoppt.db").strip(),
        vector_store_backend=os.environ.get("AUTOPPT_VECTOR_STORE_BACKEND", "disk").strip().lower(),
        vector_store_path=os.environ.get("AUTOPPT_VECTOR_STORE_PATH", "data/chroma").strip(),
        warm_embedder_on_startup=_env_bool("AUTOPPT_WARM_EMBEDDER_ON_STARTUP", True),
        trusted_proxy_ips=_env_proxy_ips("AUTOPPT_TRUSTED_PROXY_IPS"),
    )


SETTINGS: Settings = load_settings()
