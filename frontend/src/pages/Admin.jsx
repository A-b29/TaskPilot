import { useEffect, useState } from "react";
import { api } from "../api.js";
import { dueLabel } from "../components/TaskList.jsx";

export default function Admin() {
  const [users, setUsers] = useState(null);
  const [tasks, setTasks] = useState(null);
  const [owner, setOwner] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api("/admin/users"), api("/admin/tasks")]).then(([u, t]) => { setUsers(u); setTasks(t); }, (e) => setError(e.message));
  }, []);

  if (error) return <div className="card page error">{error}</div>;
  if (!users) return <div className="card page muted">Loading…</div>;

  const shown = tasks.filter((t) => (!owner || t.owner_email === owner) && (!status || t.status === status));

  return (
    <>
      <section className="card page">
        <h2>Users ({users.length})</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Open</th><th>Total</th><th>Joined</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td><span className={`badge role-${u.role}`}>{u.role}</span></td>
                  <td>{u.open_tasks}</td>
                  <td>{u.tasks}</td>
                  <td>{new Date(u.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card page">
        <div className="row spread">
          <h2>All tasks ({shown.length})</h2>
          <div className="row">
            <select value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Filter by user">
              <option value="">All users</option>
              {users.map((u) => <option key={u.id} value={u.email}>{u.email}</option>)}
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">Any status</option>
              <option value="todo">Open</option>
              <option value="done">Done</option>
            </select>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Task</th><th>Owner</th><th>Priority</th><th>Due</th><th>Status</th></tr>
            </thead>
            <tbody>
              {shown.map((t) => {
                const due = dueLabel(t.due_date, t.status);
                return (
                  <tr key={t.id} className={t.status === "done" ? "done" : ""}>
                    <td className="id">{t.id}</td>
                    <td>{t.title}</td>
                    <td>{t.owner_email}</td>
                    <td><span className={`badge pri-${t.priority}`}>{t.priority}</span></td>
                    <td className={`due ${due?.cls || ""}`}>{due ? due.text : "—"}</td>
                    <td>{t.status === "done" ? "Done" : "Open"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {shown.length === 0 && <div className="empty">No tasks match.</div>}
        </div>
      </section>
    </>
  );
}
