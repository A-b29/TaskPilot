"""TaskPilot API: auth, the chat agent, the user's own tasks, and admin views."""
import os
import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import tools
from .agent import LLMUnavailable, run_agent
from .auth import create_token, current_user, hash_password, require_admin, verify_password
from .db import Base, SessionLocal, Task, User, engine, get_db


def seed():
    """Create the demo admin and demo user from env vars (only if they don't exist yet)."""
    accounts = [
        (os.getenv("ADMIN_EMAIL"), os.getenv("ADMIN_PASSWORD"), "Admin", "admin"),
        (os.getenv("DEMO_USER_EMAIL"), os.getenv("DEMO_USER_PASSWORD"), "Demo User", "user"),
    ]
    with SessionLocal() as db:
        for email, password, name, role in accounts:
            if not (email and password) or db.scalar(select(User).where(User.email == email.lower())):
                continue
            user = User(email=email.lower(), name=name, password_hash=hash_password(password), role=role)
            db.add(user)
            db.flush()
            if role == "user":  # a few sample tasks so the demo isn't empty
                today = date.today()
                db.add_all([
                    Task(user_id=user.id, title="Submit monthly report", due_date=today + timedelta(days=3), priority="high"),
                    Task(user_id=user.id, title="Book dentist appointment", due_date=today + timedelta(days=10)),
                    Task(user_id=user.id, title="Read onboarding handbook", priority="low", status="done"),
                ])
        db.commit()


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    seed()
    yield


app = FastAPI(title="TaskPilot API", description="Manage to-do tasks by chatting with an AI agent.", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Browsers send the Origin without a trailing slash, so "https://x.vercel.app/" must not break CORS.
    allow_origins=[o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------

class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    # deliberately no "role" field: every sign-up is a normal user


class LoginIn(BaseModel):
    email: str
    password: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]  # clients can't inject system/tool messages
    content: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    today: date | None = None  # the user's local date, so "Friday" means their Friday


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    priority: str | None = None
    status: str | None = None


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role}


def auth_out(u: User) -> dict:
    return {"token": create_token(u), "user": user_out(u)}


# ---------- routes ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Please enter a valid email address.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), role="user")
    db.add(user)
    db.commit()
    return auth_out(user)


@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password.")
    return auth_out(user)


@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@app.post("/chat")
def chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from the user.")
    try:
        return run_agent(db, user, [m.model_dump() for m in body.messages], body.today or date.today())
    except LLMUnavailable as e:
        raise HTTPException(503, str(e))


@app.get("/tasks")
def my_tasks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return tools.list_tasks(db, user)["tasks"]


@app.patch("/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _tool_or_http(tools.update_task, db, user, task_id=task_id, **body.model_dump(exclude_none=True))["updated"]


@app.delete("/tasks/{task_id}")
def remove_task(task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _tool_or_http(tools.delete_task, db, user, task_id=task_id)


def _tool_or_http(fn, db, user, **kwargs):
    try:
        return fn(db, user, **kwargs)
    except tools.NotFound as e:
        raise HTTPException(404, str(e))
    except tools.ToolError as e:
        raise HTTPException(422, str(e))


@app.get("/admin/users")
def admin_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Task.user_id, func.count()).group_by(Task.user_id)).all())
    open_counts = dict(db.execute(select(Task.user_id, func.count()).where(Task.status == "todo").group_by(Task.user_id)).all())
    users = db.scalars(select(User).order_by(User.id))
    return [{**user_out(u), "created_at": u.created_at, "tasks": counts.get(u.id, 0), "open_tasks": open_counts.get(u.id, 0)}
            for u in users]


@app.get("/admin/tasks")
def admin_tasks(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(Task, User.email).join(User, Task.user_id == User.id)
                      .order_by(Task.status.desc(), Task.due_date.is_(None), Task.due_date, Task.id))
    return [{**tools.task_dict(t), "owner_email": email} for t, email in rows]
