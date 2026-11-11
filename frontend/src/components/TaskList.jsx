import { useCallback, useEffect, useState } from "react";
import { api, localToday } from "../api.js";

export function dueLabel(due, status) {
  if (!due) return null;
  const today = localToday();
  const tomorrow = new Date(Date.now() + 864e5).toLocaleDateString("en-CA");
  if (status !== "done" && due < today) return { text: `Overdue · ${fmtDate(due)}`, cls: "overdue" };
  if (due === today) return { text: "Due today", cls: "soon" };
  if (due === tomorrow) return { text: "Due tomorrow", cls: "soon" };
  return { text: `Due ${fmtDate(due)}`, cls: "" };
}

export const fmtDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

export default function TaskList({ refreshKey = 0 }) {
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("todo");

  const load = useCallback(() => api("/tasks").then((t) => { setTasks(t); setError(""); }, (e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load, refreshKey]);

  async function run(action) {
    try {
      await action();
    } catch (e) {
      setError(e.message);
    }
    load();
  }
  const toggle = (t) => run(() => api(`/tasks/${t.id}`, { method: "PATCH", body: { status: t.status === "done" ? "todo" : "done" } }));
  const remove = (t) => window.confirm(`Delete "${t.title}"?`) && run(() => api(`/tasks/${t.id}`, { method: "DELETE" }));

  if (!tasks) return error ? <div className="error">{error}</div> : <div className="muted">Loading tasks…</div>;

  const shown = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);
  const count = (s) => tasks.filter((t) => t.status === s).length;

  return (
    <div className="tasklist">
      <div className="segmented">
        {[["todo", `Open (${count("todo")})`], ["done", `Done (${count("done")})`], ["all", `All (${tasks.length})`]].map(([id, label]) => (
          <button key={id} className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>{label}</button>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      {shown.length === 0 && <div className="empty">{filter === "todo" ? "Nothing open. Ask the assistant to add a task." : "No tasks here."}</div>}
      <ul>
        {shown.map((t) => {
          const due = dueLabel(t.due_date, t.status);
          return (
            <li key={t.id} className={t.status === "done" ? "task done" : "task"}>
              <input type="checkbox" checked={t.status === "done"} onChange={() => toggle(t)} aria-label={`Mark "${t.title}" ${t.status === "done" ? "not done" : "done"}`} />
              <div className="task-body">
                <div className="task-title">{t.title}</div>
                {t.description && <div className="task-desc">{t.description}</div>}
                <div className="task-meta">
                  <span className={`badge pri-${t.priority}`}>{t.priority}</span>
                  {due && <span className={`due ${due.cls}`}>{due.text}</span>}
                  <span className="id">#{t.id}</span>
                </div>
              </div>
              <button className="icon" title="Delete task" aria-label={`Delete "${t.title}"`} onClick={() => remove(t)}>✕</button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
