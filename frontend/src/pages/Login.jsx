import { useState } from "react";
import { api } from "../api.js";

export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const timer = setTimeout(() => setSlow(true), 4000); // free backend cold start
    try {
      const body = mode === "login" ? { email: form.email, password: form.password } : form;
      onLogin(await api(`/auth/${mode}`, { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      clearTimeout(timer);
      setSlow(false);
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth" onSubmit={submit}>
        <div className="brand big">
          <span className="logo">✓</span> TaskPilot
        </div>
        <p className="muted">Manage your to-dos by chatting with an AI agent.</p>

        {mode === "signup" && (
          <label>
            Name
            <input value={form.name} onChange={set("name")} required maxLength={100} autoComplete="name" />
          </label>
        )}
        <label>
          Email
          <input type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
        </label>
        <label>
          Password
          <input
            type="password"
            value={form.password}
            onChange={set("password")}
            required
            minLength={mode === "signup" ? 8 : undefined}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>

        {error && <div className="error" role="alert">{error}</div>}
        {slow && <div className="hint">Waking up the server, which can take up to a minute on free hosting…</div>}

        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
        </button>
        <p className="muted small center">
          {mode === "login" ? "No account yet? " : "Already have an account? "}
          <button type="button" className="link" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
            {mode === "login" ? "Sign up" : "Log in"}
          </button>
        </p>
      </form>
    </div>
  );
}
