import logging
import os
from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from .config import Settings, load_settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMGateway, parse_simulation

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("app")


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] = None


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()
    app = FastAPI(title="LLM Chatbot with Key Failover and Caching")
    db = Database(s.database_url)
    db.init()
    gateway = LLMGateway(s)
    app.state.db, app.state.gateway, app.state.settings = db, gateway, s

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errs})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/health")
    def health():
        if not db.ping():
            return JSONResponse(status_code=503, content={"status": "error", "detail": "database unreachable"})
        return {"status": "ok", "keys_configured": len(s.api_keys), "cache_enabled": gateway.cache_enabled}

    @app.post("/chat")
    def chat(
        body: ChatRequest,
        x_simulate_failure: Annotated[Optional[str], Header()] = None,
    ):
        sid = body.session_id
        system_prompt = body.system_prompt or db.get_system_prompt(sid) or s.default_system_prompt
        history = db.history(sid, s.max_history_messages)
        messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": body.message}]
        simulate = parse_simulation(x_simulate_failure) if s.enable_failure_simulation else {}
        try:
            result = gateway.complete(messages, simulate)
        except AllProvidersUnavailable:
            raise HTTPException(status_code=503, detail="all providers unavailable")
        # Persist only after success, so failed requests never enter history.
        sys_to_save = body.system_prompt if (body.system_prompt and body.system_prompt.strip()) else None
        db.save_exchange(sid, sys_to_save, body.message, result.reply, result.metadata)
        return {"session_id": sid, "reply": result.reply, "metadata": result.metadata}

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str):
        msgs = db.messages(session_id)
        if not msgs:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": msgs}

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
