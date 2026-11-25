"""SQLite storage. Schema is created on startup."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path(database_url: str) -> str:
    # sqlite:////data/app.db -> /data/app.db ; sqlite:///rel.db -> rel.db
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must start with sqlite:///")
    return database_url[len(prefix):]


class Database:
    def __init__(self, database_url: str):
        self.path = db_path(database_url)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def ping(self) -> bool:
        try:
            with self.connect() as c:
                c.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def get_system_prompt(self, session_id: str):
        with self.connect() as c:
            r = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return r["system_prompt"] if r else None

    def history(self, session_id: str, limit: int):
        """Last `limit` messages, oldest first (role/content only)."""
        with self.connect() as c:
            rows = c.execute(
                "SELECT role, content FROM (SELECT id, role, content FROM messages WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_exchange(self, session_id, system_prompt, user_msg, reply, metadata):
        """Persist user+assistant atomically, only after a successful LLM call."""
        now = _now()
        with self.connect() as c:
            c.execute(
                "INSERT INTO sessions(session_id, system_prompt, created_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=COALESCE(excluded.system_prompt, sessions.system_prompt)",
                (session_id, system_prompt, now),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "user", user_msg, None, now),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "assistant", reply, json.dumps(metadata), _now()),
            )

    def messages(self, session_id: str):
        with self.connect() as c:
            rows = c.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,)
            ).fetchall()
        out = []
        for r in rows:
            m = {"role": r["role"], "content": r["content"]}
            if r["role"] == "assistant" and r["metadata"]:
                m["metadata"] = json.loads(r["metadata"])
            out.append(m)
        return out
