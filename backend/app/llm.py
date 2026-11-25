"""LiteLLM gateway: key pool with automatic failover + built-in response cache."""
import logging
import time
from dataclasses import dataclass

import litellm
from litellm import Cache

from .config import Settings

log = logging.getLogger("llm")
litellm.suppress_debug_info = True
litellm.set_verbose = False

SIMULATED_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    metadata: dict


def parse_simulation(header: str | None) -> dict:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Invalid pairs are ignored."""
    out = {}
    if not header:
        return out
    for part in header.split(","):
        if "=" not in part:
            continue
        k, v = (x.strip() for x in part.split("=", 1))
        if k and v.isdigit() and int(v) in SIMULATED_STATUSES:
            out[k.lower()] = int(v)
    return out


def _simulated_error(status: int, model: str):
    kw = dict(message=f"simulated provider status {status}", llm_provider=model.split("/")[0], model=model)
    if status == 429:
        return litellm.RateLimitError(**kw)
    if status == 500:
        return litellm.InternalServerError(**kw)
    if status == 502:
        return litellm.BadGatewayError(**kw) if hasattr(litellm, "BadGatewayError") else litellm.InternalServerError(**kw)
    return litellm.ServiceUnavailableError(**kw)


class LLMGateway:
    def __init__(self, settings: Settings):
        self.s = settings
        self.key_ids = [f"key_{i + 1}" for i in range(len(settings.api_keys))]
        if settings.cache_type == "disk":
            litellm.cache = Cache(type="disk", disk_cache_dir=settings.cache_dir)
        else:
            litellm.cache = Cache(type="local")
        self.cache_enabled = litellm.cache is not None

    def complete(self, messages: list, simulate: dict | None = None) -> LLMResult:
        simulate = simulate or {}
        start = time.perf_counter()
        # When failures are simulated, skip cache *reads* so the failover path is really exercised.
        cache_ctl = {"no-cache": True} if simulate else {}
        attempts = 0
        for key_id, key in zip(self.key_ids, self.s.api_keys):
            try:
                status = simulate.get(key_id, simulate.get("*"))
                if status:
                    raise _simulated_error(status, self.s.model)
                resp = litellm.completion(
                    model=self.s.model,
                    messages=messages,
                    api_key=key,
                    caching=True,
                    cache=cache_ctl,
                    timeout=self.s.request_timeout,
                    num_retries=0,  # failover to the next key is our retry strategy
                )
                reply = (resp.choices[0].message.content or "").strip()
                if not reply:
                    raise ValueError("empty completion")
            except Exception as e:  # 429 / quota / 5xx / auth / timeout -> next key
                attempts += 1
                log.warning("%s failed (%s: %s)", key_id, type(e).__name__, str(e)[:200])
                continue
            hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
            usage = getattr(resp, "usage", None)
            return LLMResult(
                reply=reply,
                metadata={
                    "resolution_source": "LLM_CACHE" if hit else "LIVE_INFERENCE",
                    "model": self.s.model,
                    "latency_ms": max(0, int((time.perf_counter() - start) * 1000)),
                    "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
                    "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
                    "key_id": None if hit else key_id,
                    "fallback_attempts": 0 if hit else attempts,
                },
            )
        raise AllProvidersUnavailable()
