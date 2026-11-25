import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeProvider:
    """Wraps real litellm.completion (so the real cache runs) but mocks the provider."""

    def __init__(self, real):
        self.real = real
        self.calls = []  # api keys that reached the "provider"
        self.failing = {}  # key -> exception

    def __call__(self, **kw):
        key = kw["api_key"]
        self.calls.append(key)
        if key in self.failing:
            raise self.failing[key]
        last = kw["messages"][-1]["content"]
        n_turns = len(kw["messages"])
        return self.real(**{**kw, "mock_response": f"echo({n_turns}): {last}"})


@pytest.fixture
def provider(monkeypatch):
    p = FakeProvider(litellm.completion)
    monkeypatch.setattr(litellm, "completion", p)
    return p


@pytest.fixture
def make_client(tmp_path, provider):
    def _make(sim=True, keys=("k1", "k2")):
        s = Settings(
            api_keys=tuple(keys), database_url=f"sqlite:///{tmp_path}/t.db", allowed_origins=("http://localhost:3000",),
            enable_failure_simulation=sim, model="gemini/test-model", default_system_prompt="sys",
            cache_type="local", cache_dir=str(tmp_path / "c"), request_timeout=5, max_history_messages=50,
        )
        return TestClient(create_app(s), raise_server_exceptions=False)
    return _make
