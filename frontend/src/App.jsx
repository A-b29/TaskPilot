import { useEffect, useState } from "react";
import { api, loadSession, saveSession, setUnauthorizedHandler } from "./api.js";
import Login from "./pages/Login.jsx";
import Chat from "./pages/Chat.jsx";
import Admin from "./pages/Admin.jsx";
import TaskList from "./components/TaskList.jsx";

export default function App() {
  const [session, setSession] = useState(loadSession);
  const [page, setPage] = useState("chat");

  const login = (s) => {
    saveSession(s);
    setSession(s);
  };
  const logout = () => {
    saveSession(null);
    setSession(null);
    setPage("chat");
  };

  useEffect(() => {
    setUnauthorizedHandler(logout);
    // Refresh the user's name/role from the server (the backend is the source of truth for roles).
    if (session) api("/auth/me").then((user) => login({ ...loadSession(), user })).catch(() => {});
  }, []);

  if (!session) return <Login onLogin={login} />;

  const { user } = session;
  const pages = [["chat", "Assistant"], ["tasks", "My tasks"], ...(user.role === "admin" ? [["admin", "Admin"]] : [])];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">✓</span> TaskPilot
        </div>
        <nav>
          {pages.map(([id, label]) => (
            <button key={id} className={page === id ? "tab active" : "tab"} onClick={() => setPage(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="who">
          <span className="name">{user.name}</span>
          <span className={`badge role-${user.role}`}>{user.role}</span>
          <button className="ghost" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <main>
        {page === "chat" && <Chat user={user} />}
        {page === "tasks" && (
          <section className="card page">
            <h2>My tasks</h2>
            <p className="muted">Everything the assistant adds or changes shows up here. You can also tick tasks off by hand.</p>
            <TaskList />
          </section>
        )}
        {page === "admin" && user.role === "admin" && <Admin />}
      </main>
    </div>
  );
}
