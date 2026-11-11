import { useEffect, useRef, useState } from "react";
import { api, localToday } from "../api.js";
import TaskList from "../components/TaskList.jsx";

const SUGGESTIONS = [
  "What's due this week?",
  "Add a task to submit the monthly report by Friday",
  "Mark the report task as done and add a task to start the next one",
  "Give me a quick summary of my open tasks",
];
const ADMIN_SUGGESTIONS = ["List all users", "Assign a high priority task 'Review Q4 budget' to demo@taskpilot.app due next Monday"];

export default function Chat({ user }) {
  const storageKey = `taskpilot.chat.${user.id}`;
  const [messages, setMessages] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey)) || [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const endRef = useRef(null);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages.slice(-50)));
    } catch { /* storage blocked: history lasts until reload */ }
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      // Send recent text-only history so follow-ups like "mark it done" have context.
      const history = next.filter((m) => !m.error).slice(-10).map(({ role, content }) => ({ role, content: content.slice(0, 4000) }));
      while (history[0]?.role === "assistant") history.shift();
      const res = await api("/chat", { method: "POST", body: { messages: history, today: localToday() } });
      setMessages((m) => [...m, { role: "assistant", content: res.reply, toolCalls: res.tool_calls, pending: res.pending_deletes }]);
      if (res.tool_calls.length) setRefreshKey((k) => k + 1);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: e.message, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  const resolve = (index, resolved) => setMessages((ms) => ms.map((m, i) => (i === index ? { ...m, resolved } : m)));

  return (
    <div className="chat-layout">
      <section className="card chat">
        <div className="messages">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>Hi {user.name.split(" ")[0]} 👋</h2>
              <p className="muted">Tell me what to add, change or check, and I'll update your task list. Try:</p>
              <div className="suggestions">
                {[...SUGGESTIONS, ...(user.role === "admin" ? ADMIN_SUGGESTIONS : [])].map((s) => (
                  <button key={s} onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}${m.error ? " error-msg" : ""}`}>
              <div className="bubble">{m.content}</div>
              {m.toolCalls?.length > 0 && <ToolCalls calls={m.toolCalls} />}
              {m.pending?.length > 0 && (
                <ConfirmDelete tasks={m.pending} resolved={m.resolved} onResolve={(r) => { resolve(i, r); setRefreshKey((k) => k + 1); }} />
              )}
            </div>
          ))}
          {busy && (
            <div className="msg assistant">
              <div className="bubble typing"><span /><span /><span /></div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. Add 'call the bank' for tomorrow, high priority"
            maxLength={4000}
            aria-label="Message the assistant"
          />
          <button className="primary" disabled={busy || !input.trim()}>Send</button>
        </form>
        {messages.length > 0 && (
          <button className="link small clear" onClick={() => setMessages([])} disabled={busy}>Clear conversation</button>
        )}
      </section>
      <aside className="card side">
        <h3>Your tasks</h3>
        <TaskList refreshKey={refreshKey} />
      </aside>
    </div>
  );
}

function ToolCalls({ calls }) {
  return (
    <details className="tools">
      <summary>
        {calls.map((c, i) => (
          <span key={i} className={`chip ${c.ok ? "" : "failed"}`}>{c.ok ? "✓" : "✕"} {c.tool}</span>
        ))}
      </summary>
      {calls.map((c, i) => (
        <div key={i} className="toolcall">
          <code>{c.tool}({JSON.stringify(c.args)})</code>
          <pre>{JSON.stringify(c.result, null, 2)}</pre>
        </div>
      ))}
    </details>
  );
}

function ConfirmDelete({ tasks, resolved, onResolve }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (resolved) return <div className="confirm resolved">{resolved === "deleted" ? "🗑 Deleted." : "Kept. Nothing was deleted."}</div>;

  async function confirm() {
    setBusy(true);
    try {
      await Promise.all(tasks.map((t) => api(`/tasks/${t.id}`, { method: "DELETE" })));
      onResolve("deleted");
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  return (
    <div className="confirm">
      <div>Delete {tasks.length === 1 ? "this task" : `these ${tasks.length} tasks`}?</div>
      <ul>{tasks.map((t) => <li key={t.id}>#{t.id} {t.title}</li>)}</ul>
      {error && <div className="error">{error}</div>}
      <div className="row">
        <button className="danger" disabled={busy} onClick={confirm}>Confirm delete</button>
        <button className="ghost" disabled={busy} onClick={() => onResolve("cancelled")}>Cancel</button>
      </div>
    </div>
  );
}
