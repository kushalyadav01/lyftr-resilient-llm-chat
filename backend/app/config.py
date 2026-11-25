"""All configuration comes from environment variables."""
import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_keys: tuple
    database_url: str
    allowed_origins: tuple
    enable_failure_simulation: bool
    model: str
    default_system_prompt: str
    cache_type: str  # "local" (in-memory) or "disk"
    cache_dir: str
    request_timeout: float
    max_history_messages: int


def load_settings() -> Settings:
    keys = tuple(k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip())
    origins = tuple(o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip())
    return Settings(
        api_keys=keys,
        database_url=os.getenv("DATABASE_URL", "sqlite:////data/app.db"),
        allowed_origins=origins,
        enable_failure_simulation=_bool("ENABLE_FAILURE_SIMULATION", False),
        model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"),
        default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."),
        cache_type=os.getenv("CACHE_TYPE", "local").strip().lower(),
        cache_dir=os.getenv("CACHE_DIR", "/data/llm_cache"),
        request_timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "50")),
    )
