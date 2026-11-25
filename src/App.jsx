import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const newSessionId = () => "s-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).slice(2, 10));

function errorText(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Please try again in a moment.";
  if (status === 422) {
    const d = body?.detail;
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join("; ") : typeof d === "string" ? d : "invalid input";
    return `Your message could not be sent (${msg}). Messages must be 1–4000 characters.`;
  }
  return typeof body?.detail === "string" ? body.detail : `Something went wrong (HTTP ${status}).`;
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId); // a new session on every page load
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((data) => setHealth(data))
      .catch(() => setHealth({ status: "error" }));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  function startNewSession() {
    setSessionId(newSessionId());
    setMessages([]);
    setInput("");
  }

  async function send() {
    const text = input.trim();
    if (loading) return;
    if (!text) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const payload = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim();
      const res = await fetch(`${API}/chat`, { method: "POST", headers, body: JSON.stringify(payload) });
      let body = null;
      try { body = await res.json(); } catch { /* non-JSON body */ }
      if (res.ok && body?.reply) {
        setMessages((m) => [...m, { role: "assistant", content: body.reply, metadata: body.metadata }]);
      } else {
        setMessages((m) => [...m, { role: "error", content: errorText(res.status, body) }]);
      }
    } catch {
      setMessages((m) => [...m, { role: "error", content: "Cannot reach the server. Check your connection and try again." }]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="app">
      <header>
        <div className="title-row">
          <h1>Resilient LLM Chat</h1>
          {health?.status === "ok" ? (
            <span className="status-badge ok" title={`${health.keys_configured} keys configured, cache ${health.cache_enabled ? 'enabled' : 'disabled'}`}>
              ● Connected ({health.keys_configured} keys)
            </span>
          ) : health ? (
            <span className="status-badge err">● Server offline</span>
          ) : null}
        </div>
        <div className="session-bar">
          <span className="sid">session {sessionId}</span>
          <button type="button" className="btn-secondary btn-sm" onClick={startNewSession}>New Session</button>
        </div>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>System prompt
          <textarea data-testid="system-prompt-input" rows={2} value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)} placeholder="Optional: e.g. You are a pirate." />
        </label>
        <label>Failover test header <code>X-Simulate-Failure</code>
          <div className="preset-row">
            <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="e.g. key_1=429  or  *=429" />
            <div className="chips">
              <button type="button" className="btn-chip" onClick={() => setSimulate("key_1=429")}>key_1=429</button>
              <button type="button" className="btn-chip" onClick={() => setSimulate("key_1=500")}>key_1=500</button>
              <button type="button" className="btn-chip" onClick={() => setSimulate("*=429")}>*=429</button>
              {simulate && <button type="button" className="btn-chip clear" onClick={() => setSimulate("")}>Clear</button>}
            </div>
          </div>
        </label>
      </details>

      <main className="chat" aria-live="polite">
        {messages.length === 0 && <p className="empty">Say hello to start a conversation.</p>}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user"><div className="bubble">{m.content}</div></div>
          ) : m.role === "error" ? (
            <div key={i} className="msg"><div className="bubble error" role="alert">{m.content}</div></div>
          ) : (
            <div key={i} className="msg" data-testid="assistant-message">
              <div className="bubble">{m.content}</div>
              <div className="meta">
                <span data-testid="meta-source" className={m.metadata.resolution_source === "LLM_CACHE" ? "tag cache" : "tag live"}>{m.metadata.resolution_source}</span>
                <span data-testid="meta-model">{m.metadata.model}</span>
                <span data-testid="meta-latency">{m.metadata.latency_ms} ms</span>
                <span className="tok">in <b data-testid="meta-input-tokens">{m.metadata.input_tokens}</b></span>
                <span className="tok">out <b data-testid="meta-output-tokens">{m.metadata.output_tokens}</b></span>
                {m.metadata.key_id && <span className="dim">{m.metadata.key_id}{m.metadata.fallback_attempts > 0 ? ` · ${m.metadata.fallback_attempts} fallback` : ""}</span>}
              </div>
            </div>
          )
        )}
        {loading && <div className="msg"><div className="bubble typing">Thinking…</div></div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea data-testid="chat-input" rows={1} value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown} placeholder="Type a message…" aria-label="Message" />
        <button data-testid="send-button" onClick={send} disabled={loading}>Send</button>
      </footer>
    </div>
  );
}
