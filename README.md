# TaskPilot: an AI agent that manages your tasks

TaskPilot is a to-do app you run by chatting. You type things like *"Add a task to submit the monthly report by Friday"* or *"Mark the report done and add a task to start the next one"*. An LLM agent picks the right tools (add, list, update, delete) and changes the data in Postgres. The task list next to the chat updates as it goes. Admins can see every user and every task, and can assign tasks to other people.

## Live app

**[Open TaskPilot →](https://task-pilot-xi.vercel.app)**

| | Link |
|---|---|
<<<<<<< HEAD
| App (frontend) | [task-pilot-xi.vercel.app](https://task-pilot-xi.vercel.app) |
| Backend API (FastAPI) | [taskpilot-api-kyar.onrender.com](https://taskpilot-api-kyar.onrender.com/health) |
| API docs (Swagger) | [taskpilot-api-kyar.onrender.com/docs](https://taskpilot-api-kyar.onrender.com/docs) |
| Source code | [github.com/A-b29/TaskPilot](https://github.com/A-b29/TaskPilot) |
=======
| Frontend | `https://task-pilot-xi.vercel.app` |
| Backend (FastAPI) | `https://taskpilot-api-kyar.onrender.com` (Swagger UI at [`/docs`](https://<your-api>.onrender.com/docs)) |
>>>>>>> 1d481a78cb323f0e0617935715bccbcadf93656a

> The backend is on Render's free plan, which **sleeps after 15 minutes idle**. The first request after that can take about a minute while it wakes up. The login page shows a "waking up the server" message when this happens.

**Demo logins**

| Role | Email | Password |
|---|---|---|
| Admin | `admin@taskpilot.app` | `admin123` |
| User | `demo@taskpilot.app` | `demo1234` |

The demo user starts with three sample tasks. You can also sign up for a new account, which always gets the normal **user** role.

## Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** + SQLAlchemy 2 | Required. SQLAlchemy runs on SQLite locally and Postgres in production with no code changes. |
| Database | **Neon Postgres** (free) | Hosted, free, no card needed, and it survives Render restarts (Render's disk is wiped). |
| LLM | **Groq**, `openai/gpt-oss-120b` (free tier) | Fast, generous free tier, and OpenAI's open-weight model is reliable at tool calling. It's called through the **OpenAI-compatible API** with the `openai` SDK, so switching to Gemini, OpenRouter or OpenAI only means changing `LLM_BASE_URL` and `LLM_MODEL`. |
| Agent | Plain tool-calling loop (~60 lines, `backend/app/agent.py`) | The job is "LLM picks tools, backend runs them, repeat". A framework like LangChain would hide that small loop without adding anything. |
| Auth | Own JWT (PyJWT) + stdlib `hashlib.scrypt` for passwords | Small and easy to explain. scrypt is a memory-hard password hash in Python's standard library, so there's no extra dependency. |
| Frontend | **React 19 + Vite**, plain CSS | Simple and fast to build. No UI library needed for three pages. Light and dark mode follow the OS setting. |
| Hosting | Vercel (frontend) + Render (backend) + Neon (DB) | All free, no credit card. |

## How the AI part works

1. The chat page sends the last ~20 messages plus the user's **local date**, so "Friday" means their Friday.
2. The backend builds a system prompt (today's date, the rules) and calls the LLM with JSON schemas for the tools this user may use: `add_task`, `list_tasks`, `update_task`, `delete_task`, plus `list_users` and `assign_task` for admins.
3. When the model asks for tool calls, the backend **runs them itself** against the database and sends back the results. The loop repeats (up to 8 rounds) until the model answers in plain text. That loop is what makes multi-step requests work. "Mark the report done and add the next one" becomes `list_tasks(search="report")` → `update_task(id, status="done")` + `add_task("Start next report")`.
4. The reply comes back with every tool call (name, arguments, result), and the UI shows these as chips you can expand.

**Safe by design:** tools never take a user id from the LLM. Each tool function gets the logged-in user from the backend and filters every query by `user.id`. An unknown argument such as an injected `user_id` is rejected before the tool runs (`run_tool` in `backend/app/tools.py`). Admin tools are only offered to admins and are checked again on the server. Asking for someone else's task id returns "not found", the same as an id that doesn't exist.

## Login and roles

- `POST /auth/signup` and `POST /auth/login` return a JWT (valid for 7 days). The frontend keeps it in `localStorage` and sends it as `Authorization: Bearer …`.
- Passwords are stored only as salted **scrypt** hashes.
- Sign-up has **no role field**, so every new account is `user`. The admin account is created at startup from env vars (`ADMIN_EMAIL` / `ADMIN_PASSWORD`). Nobody can make themselves admin.
- Roles are checked **on the backend, on every request**. The token only stores the user id, and the role is read from the database each time. `/admin/*` routes use a `require_admin` dependency, so a normal user calling them directly gets **403**.
- The frontend only shows the **Admin** tab to admins. That's for convenience only; the backend is what enforces access.

| Role | Can do |
|---|---|
| User | Chat with the agent about their own tasks, view/complete/delete their own tasks |
| Admin | Everything a user can do, plus see all users and all tasks (Admin page), and ask the agent to list users or assign a task to another user |

## Features beyond the minimum

- **Confirmation before deleting**: the agent's `delete_task` only *requests* a deletion. The chat shows the task(s) with **Confirm delete / Cancel** buttons, and nothing is deleted until the user clicks. This also covers bulk deletes ("delete all my done tasks").
- **See which tools ran**: every reply shows chips like `✓ list_tasks ✓ update_task`. Click them to see the exact arguments and results.
- **Priorities and due dates** (low/medium/high), with "Due today", "Due tomorrow" and "Overdue" labels.
- **Admin tools in the agent**: admins can say *"Assign 'Review Q4 budget' to demo@taskpilot.app, due next Monday"*.
- **Admin dashboard**: users with open/total task counts, and all tasks filterable by user and status.
- **Live task panel** next to the chat that refreshes after every agent action. There is also a separate **My tasks** page with manual tick-off and delete.
- **Summaries**: "Give me a summary of my open tasks" or "what's overdue?" works through `list_tasks` filters (status, priority, due date range, keyword).
- **Chat history** is saved per user in the browser, so it survives a page reload.
- **Friendly errors**: LLM timeouts, rate limits and provider errors become plain messages (HTTP 503) instead of crashes. The UI also explains free-tier cold starts.
- **Tests** (`backend/tests/test_app.py`) cover role enforcement, cross-user isolation (including a "malicious" LLM that tries to edit another user's task, inject `user_id`, or call admin tools), the multi-step agent loop, delete confirmation, and LLM failure handling. They use a fake LLM, so no API key is needed.
- Dark mode and a mobile layout.

## Run it locally

You need Python 3.12+ and Node 20+.

```bash
git clone https://github.com/A-b29/TaskPilot.git
cd TaskPilot

# backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # then fill in LLM_API_KEY (free at https://console.groq.com/keys)
uvicorn app.main:app --reload --env-file .env
# API on http://localhost:8000, docs at http://localhost:8000/docs
# With DATABASE_URL empty, it uses a local SQLite file.

# tests (no API key needed)
pip install pytest
python -m pytest -q

# frontend (new terminal)
cd frontend
npm install
cp .env.example .env              # VITE_API_URL=http://localhost:8000
npm run dev                       # http://localhost:5173
```

### Environment variables (backend)

| Name | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL from Neon/Supabase (`postgresql://…`). Empty = local SQLite. |
| `JWT_SECRET` | Random string used to sign tokens. |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Any OpenAI-compatible provider. Defaults to Groq. |
| `LLM_REASONING_EFFORT` | `low` keeps gpt-oss fast and light on tokens. Leave it empty for models that don't support it. |
| `CORS_ORIGINS` | Comma-separated frontend URLs, e.g. `https://taskpilot.vercel.app`. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD` | Demo accounts created on startup if missing. |

The frontend needs only `VITE_API_URL`.

## Project structure

```
backend/
  app/main.py      routes: auth, chat, tasks, admin
  app/agent.py     LLM tool-calling loop + friendly error handling
  app/tools.py     task operations (shared by the agent and the REST API) + tool schemas
  app/auth.py      password hashing, JWT, current_user / require_admin
  app/db.py        SQLAlchemy engine and models (User, Task)
  tests/test_app.py
frontend/src/
  App.jsx          session, navigation (Admin tab only for admins)
  api.js           fetch wrapper (token, readable errors)
  pages/           Login, Chat, Admin
  components/TaskList.jsx
render.yaml        Render blueprint for the backend
```

## What's not finished / could be improved

- **Free LLM rate limits**: Groq's free tier allows 8,000 tokens per minute for `gpt-oss-120b`, and a multi-step request uses about 3–4k. If several people chat at once, replies slow down (the SDK waits and retries) or show a friendly "AI is busy, try again" message. The free tier also caps daily tokens. A paid tier, or a second provider as a fallback, would fix this.
- **No streaming**: replies arrive in one piece after the agent finishes. That's about 2–3 s on Groq, longer when rate-limited.
- **Chat history is stored in the browser**, not the database, so it doesn't follow you to another device.
- **No database migrations** (Alembic). Tables are created on startup, which is fine for this schema but not for future changes.
- **No rate limiting** on `/chat`. A busy user could use up the shared free LLM quota.
- **Reminders and recurring tasks** aren't implemented. Admins can't change roles or deactivate users from the UI.
- The JWT lives in `localStorage`. An httpOnly cookie would be safer against XSS but needs more cross-site setup between Vercel and Render.
- Small open models sometimes produce a malformed tool call. The app catches this and asks the user to rephrase instead of crashing.
