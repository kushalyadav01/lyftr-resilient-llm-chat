# Resilient LLM Chatbot — Key Failover & Response Caching

React + FastAPI + LiteLLM + SQLite. Multi-turn AI chat application with automatic key failover across rate-limited or exhausted keys, per-request token tracking, and response caching.

## 1. Live URLs

| Service | URL |
|---|---|
| Frontend | `<ADD-FRONTEND-URL>` |
| Backend API | `<ADD-BACKEND-URL>` (Endpoints: `/health`, `/chat`, `/sessions/{id}/messages`) |
| Demo Video | `<ADD-VIDEO-URL>` |

## 2. Run locally: with Docker and without

### With Docker
Both frontend and backend start with a single command:
```bash
cp .env.example .env      # Add 2+ real keys in LLM_API_KEYS
make up                   # Starts backend (:8000) and frontend (:3000)
make down                 # Stops containers
```
SQLite database resides in the named Docker volume `appdata` mounted at `/data/app.db`, ensuring session history persists across container restarts.

### Without Docker

**Backend (FastAPI)**:
```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt

export LLM_API_KEYS="key_1_secret,key_2_secret"
export DATABASE_URL="sqlite:///./app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
export ENABLE_FAILURE_SIMULATION="true"

uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

**Frontend (React + Vite)**:
```bash
cd frontend
npm install
VITE_API_BASE_URL="http://localhost:8000" npm run dev
```

**Run Test Suite**:
```bash
make test
```
Runs the 17 backend tests covering the health check, full chat contract, caching hits/misses, multi-turn state isolation, system prompt persistence, provider failover, 503 error handling, 422 input validation, 404 session handling, and CORS.

## 3. Design decisions: key fallback, caching, SQLite session storage

- **Key fallback & High Availability**: `LLM_API_KEYS` provides an ordered key pool (`key_1`, `key_2`, ...). Each incoming request attempts inference using the primary key. If any transient error, rate-limit (HTTP 429), quota exhaustion, 5xx server error, or network timeout occurs, LiteLLM gateway automatically fails over to the next configured key. `num_retries=0` is configured on individual calls because key-hopping acts as our explicit retry strategy. `fallback_attempts` tracks the count of failed keys before success. If all keys are exhausted, the backend cleanly returns `503 {"detail": "all providers unavailable"}` without crashing or polluting history. API keys are strictly redacted: only `key_id` is exposed to clients.
- **Caching**: Leverages LiteLLM's cache (`litellm.cache`, configured in-memory or on persistent disk via `CACHE_TYPE=disk`). The cache key is computed from the model plus the exact ordered message list (system prompt + history + new message). API keys are excluded from the cache hash, enabling cache hits regardless of which key generated the original response. Cache hits report `resolution_source: "LLM_CACHE"`, `key_id: null`, `fallback_attempts: 0`, and the stored token usage with near-instant response latency (< 15 ms).
- **SQLite Session Storage**: Session history is stored purely in SQLite without requiring external services like Redis or Postgres. The `messages` table adheres strictly to the required schema (`id`, `session_id`, `role`, `content`, `metadata`, `created_at`). Server timestamps use ISO-8601 UTC. An atomic transaction saves both the user message and assistant reply only upon a successful inference, guaranteeing that failed or aborted requests never corrupt history. A dedicated `sessions` table persists session-level system prompts across turns.
- **Failover Simulation Hook**: To test resilience deterministically without exhausting real API quotas, `POST /chat` supports the `X-Simulate-Failure` header when `ENABLE_FAILURE_SIMULATION=true` (e.g. `key_1=429`, `key_1=500`, `*=429`). The gateway injects the simulated status code for the target key so that real fallback mechanics and error paths execute. When simulation is active, cache *reads* are bypassed (`no-cache: True`) so failover behavior is verified on demand.
- **Error Handling & API Contract**: All endpoints strictly return JSON with a `detail` field. Request validations return 422, exhausted providers return 503, missing sessions return 404, and unhandled errors return `500 {"detail": "internal server error"}`. Stack traces and raw HTML are never exposed.

## 4. Verification: how to see failover, cache hits and per-message token usage

```bash
B="http://localhost:8000"   # or your deployed backend URL

# 1. Health check: verify keys configured and cache status
curl -s $B/health

# 2. Live inference: first call generates LIVE_INFERENCE
curl -s $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"test-s1","message":"What is the capital of France?"}'

# 3. Response caching: same message in a new session yields LLM_CACHE with identical reply & key_id=null
curl -s $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"test-s2","message":"What is the capital of France?"}'

# 4. Failover: simulate key_1 returning 429; key_2 automatically answers with fallback_attempts=1
curl -s $B/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"test-s3","message":"Explain quantum computing in one sentence."}'

# 5. Total outage resilience: simulate all keys failing (*=429); returns clean 503 and leaves history clean
curl -s -i $B/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"test-s4","message":"Should not be stored"}'

curl -s -i $B/sessions/test-s4/messages   # Returns 404 session not found

# 6. Session history verification: check persisted multi-turn messages
curl -s $B/sessions/test-s1/messages
```

In the UI:
- Every assistant bubble displays the `LIVE_INFERENCE` or `LLM_CACHE` tag, model name, server latency in ms, prompt input tokens, completion output tokens, and the serving `key_id`.
- The collapsible **Session settings** panel includes preset buttons (`key_1=429`, `key_1=500`, `*=429`, `Clear`) to trigger failover simulations with a single click.

## 5. Setup Used: your editor and AI tools

- **AI Tools**: Antigravity with Gemini 3.8 Flash for architectural auditing, endpoint verification, test development, and contract validation.
- **Runtime & Editors**: Python 3.12/3.14 with `uv` package manager, Node 22 with Vite, SQLite 3, VS Code.
- **Testing & Verification**: Pytest, FastAPI TestClient, curl HTTP verification.

## 6. Bonus features (if any): what you added beyond the requirements and why

1. **One-Click Simulation Chips in UI**: Preset buttons for `key_1=429`, `key_1=500`, `*=429`, and `Clear` inside the UI settings drawer so evaluators and testers can demonstrate failover without manual typing or curl scripts.
2. **Real-Time Health & Key Status Badge**: The UI header automatically queries `/health` on startup and displays live backend connection status and the count of loaded API keys.
3. **Session Reset Button**: A "New Session" button in the UI header enables rapid testing of fresh sessions and cache verification directly in the browser.
4. **Persistent Disk Cache Option**: Configurable `CACHE_TYPE=disk` with `CACHE_DIR=/data/llm_cache` allows cached LLM responses to survive container restarts alongside the SQLite database volume.
5. **Multi-stage Production Dockerfiles**: Optimized small-footprint images using alpine/slim bases, non-root system users (`app` uid 10001), and a native Docker container `HEALTHCHECK`.

