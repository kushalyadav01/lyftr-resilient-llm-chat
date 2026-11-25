import litellm


def chat(c, sid, msg, headers=None, **extra):
    return c.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(make_client):
    r = make_client().get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_contract_and_live(make_client):
    r = chat(make_client(), "s1", "hello")
    assert r.status_code == 200
    b = r.json()
    assert b["session_id"] == "s1" and b["reply"]
    m = b["metadata"]
    assert m["resolution_source"] == "LIVE_INFERENCE" and m["model"] == "gemini/test-model"
    assert isinstance(m["latency_ms"], int) and m["key_id"] == "key_1" and m["fallback_attempts"] == 0
    assert m["input_tokens"] > 0 and m["output_tokens"] > 0


def test_cache_hit_across_sessions_and_different_message_misses(make_client):
    c = make_client()
    a = chat(c, "s1", "What is the capital of France?").json()
    b = chat(c, "s2", "What is the capital of France?").json()
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    d = chat(c, "s3", "What is the capital of Spain?").json()
    assert d["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_depends_on_history(make_client):
    c = make_client()
    chat(c, "s1", "a")
    chat(c, "s1", "same")
    r = chat(c, "s2", "same").json()  # no history in s2 -> different message list
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_and_isolation(make_client):
    c = make_client()
    chat(c, "s1", "one")
    r = chat(c, "s1", "two").json()
    assert "echo(4)" in r["reply"]  # system + 2 history + new
    assert "echo(2)" in chat(c, "s2", "x").json()["reply"]
    h = c.get("/sessions/s1/messages").json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert "metadata" not in h["messages"][0] and "input_tokens" in h["messages"][1]["metadata"]
    assert all(m["role"] != "system" for m in h["messages"])


def test_system_prompt_persists_for_session(make_client, provider):
    c = make_client()
    seen = []
    orig = provider.real
    provider.real = lambda **kw: (seen.append(kw["messages"][0]["content"]), orig(**kw))[1]
    chat(c, "s1", "hi", system_prompt="Be a pirate")
    chat(c, "s1", "again")
    assert seen == ["Be a pirate", "Be a pirate"]


def test_failover_simulated(make_client):
    c = make_client()
    r = chat(c, "s1", "q1", {"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1
    r = chat(c, "s1", "q2", {"X-Simulate-Failure": "key_1=500"})
    assert r.json()["metadata"]["key_id"] == "key_2"
    r = chat(c, "s1", "q3", {"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert r.status_code == 503


def test_all_fail_503_not_stored(make_client):
    c = make_client()
    r = chat(c, "sx", "q", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert c.get("/sessions/sx/messages").status_code == 404


def test_simulation_bypasses_cache_read(make_client):
    c = make_client()
    chat(c, "s1", "cached?")
    assert chat(c, "s2", "cached?").json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert chat(c, "s3", "cached?", {"X-Simulate-Failure": "*=429"}).status_code == 503


def test_simulation_disabled_ignores_header(make_client):
    r = chat(make_client(sim=False), "s1", "q", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200


def test_real_provider_errors_fail_over(make_client, provider):
    provider.failing["k1"] = litellm.RateLimitError("quota", "gemini", "m")
    r = chat(make_client(), "s1", "q")
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"
    provider.failing["k2"] = litellm.InternalServerError("boom", "gemini", "m")
    assert chat(make_client(), "s2", "q2").status_code == 503


def test_validation_422(make_client):
    c = make_client()
    assert chat(c, "s", "   ").status_code == 422
    assert chat(c, "s", "x" * 4001).status_code == 422
    assert c.post("/chat", json={"message": "hi"}).status_code == 422
    assert c.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    assert c.post("/chat", content="{bad", headers={"content-type": "application/json"}).status_code == 422
    assert chat(c, "s" * 129, "hi").status_code == 422
    assert "detail" in c.post("/chat", json={}).json()
    assert c.get("/sessions/s/messages").status_code == 404  # failed requests not stored


def test_unknown_session_404(make_client):
    r = make_client().get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


def test_cors(make_client):
    r = make_client().options("/chat", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "x-simulate-failure,content-type"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_system_prompt_empty_does_not_clear(make_client, provider):
    c = make_client()
    seen = []
    orig = provider.real
    provider.real = lambda **kw: (seen.append(kw["messages"][0]["content"]), orig(**kw))[1]
    chat(c, "s_sp", "hello", system_prompt="You are a wizard")
    chat(c, "s_sp", "again", system_prompt="")
    assert seen == ["You are a wizard", "You are a wizard"]


def test_simulation_case_insensitive(make_client):
    c = make_client()
    r = chat(c, "s_case", "msg", {"X-Simulate-Failure": "KEY_1=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1


def test_health_db_failure(make_client, monkeypatch):
    client = make_client()
    monkeypatch.setattr(client.app.state.db, "ping", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "error"

