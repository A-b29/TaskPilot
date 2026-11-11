"""Task operations, shared by the AI agent (as LLM tools) and the REST API.

Safety: every function gets the logged-in `user` from the backend. No tool takes a user id from the
LLM, and every query is filtered by `user.id`, so a user's agent can only ever touch that user's tasks.
Admin-only tools are offered to admins only and re-checked in `run_tool`.
"""
import inspect
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import Task, User

PRIORITIES = ("low", "medium", "high")
STATUSES = ("todo", "done")


class ToolError(Exception):
    """Something the caller can fix (bad date, unknown id). Shown to the LLM / user as-is."""


class NotFound(ToolError):
    pass


def task_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "priority": t.priority,
        "status": t.status,
    }


def _date(value):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolError(f"'{value}' is not a valid date, use YYYY-MM-DD.")


def _choice(value, options, field):
    if value not in options:
        raise ToolError(f"{field} must be one of: {', '.join(options)}.")
    return value


def _title(value):
    value = str(value or "").strip()
    if not 1 <= len(value) <= 200:
        raise ToolError("Title must be 1-200 characters.")
    return value


def _own_task(db: Session, user: User, task_id) -> Task:
    try:
        task = db.get(Task, int(task_id))
    except (TypeError, ValueError):
        task = None
    if task is None or task.user_id != user.id:  # same message either way: don't reveal other users' ids
        raise NotFound(f"You have no task with id {task_id}.")
    return task


def _create(db, owner, title, description, due_date, priority) -> dict:
    task = Task(
        user_id=owner.id,
        title=_title(title),
        description=str(description or "").strip()[:2000],
        due_date=_date(due_date),
        priority=_choice(priority or "medium", PRIORITIES, "priority"),
    )
    db.add(task)
    db.commit()
    return task_dict(task)


# ---- tools available to every user ----

def add_task(db, user, title, description="", due_date=None, priority="medium"):
    return {"created": _create(db, user, title, description, due_date, priority)}


def list_tasks(db, user, status=None, priority=None, due_from=None, due_to=None, search=None):
    q = select(Task).where(Task.user_id == user.id)
    if status:
        q = q.where(Task.status == _choice(status, STATUSES, "status"))
    if priority:
        q = q.where(Task.priority == _choice(priority, PRIORITIES, "priority"))
    if due_from:
        q = q.where(Task.due_date >= _date(due_from))
    if due_to:
        q = q.where(Task.due_date <= _date(due_to))
    if search:
        q = q.where(or_(Task.title.ilike(f"%{search}%"), Task.description.ilike(f"%{search}%")))
    # open tasks first, then by due date (no due date last)
    q = q.order_by(Task.status.desc(), Task.due_date.is_(None), Task.due_date, Task.id).limit(200)
    tasks = [task_dict(t) for t in db.scalars(q)]
    return {"count": len(tasks), "tasks": tasks}


def update_task(db, user, task_id, title=None, description=None, due_date=None, priority=None, status=None):
    task = _own_task(db, user, task_id)
    if title is not None:
        task.title = _title(title)
    if description is not None:
        task.description = str(description).strip()[:2000]
    if due_date is not None:  # "" clears the due date
        task.due_date = _date(due_date)
    if priority is not None:
        task.priority = _choice(priority, PRIORITIES, "priority")
    if status is not None:
        task.status = _choice(status, STATUSES, "status")
    db.commit()
    return {"updated": task_dict(task)}


def request_delete(db, user, task_id):
    """The agent never deletes directly: it asks, and the user confirms in the UI (DELETE /tasks/{id})."""
    task = _own_task(db, user, task_id)
    return {"status": "awaiting_user_confirmation", "task": task_dict(task),
            "note": "NOT deleted yet. The user must press Confirm in the app."}


def delete_task(db, user, task_id):
    task = _own_task(db, user, task_id)
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


# ---- admin-only tools ----

def list_users(db, user):
    users = db.scalars(select(User).order_by(User.id))
    return {"users": [{"id": u.id, "email": u.email, "name": u.name, "role": u.role} for u in users]}


def assign_task(db, user, user_email, title, description="", due_date=None, priority="medium"):
    owner = db.scalar(select(User).where(User.email == (user_email or "").strip().lower()))
    if owner is None:
        raise NotFound(f"No user with email {user_email}.")
    return {"assigned_to": owner.email, "created": _create(db, owner, title, description, due_date, priority)}


USER_TOOLS = {"add_task": add_task, "list_tasks": list_tasks, "update_task": update_task, "delete_task": request_delete}
ADMIN_TOOLS = {"list_users": list_users, "assign_task": assign_task}


def tools_for(user: User) -> dict:
    return USER_TOOLS | ADMIN_TOOLS if user.role == "admin" else USER_TOOLS


def run_tool(db: Session, user: User, name: str, args: dict) -> dict:
    fn = tools_for(user).get(name)
    if fn is None:
        return {"error": f"Tool '{name}' is not available to you."}
    try:
        inspect.signature(fn).bind(db, user, **args)  # rejects unknown/missing args (e.g. an injected user_id)
    except TypeError as e:
        return {"error": f"Invalid arguments for {name}: {e}"}
    try:
        return fn(db, user, **args)
    except ToolError as e:
        db.rollback()
        return {"error": str(e)}


# ---- JSON schemas the LLM sees ----

def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required)}}}


_DATE = {"type": "string", "description": "Date as YYYY-MM-DD"}
_PRIORITY = {"type": "string", "enum": list(PRIORITIES)}
_STATUS = {"type": "string", "enum": list(STATUSES)}
_ID = {"type": "integer", "description": "Task id (get it from list_tasks)"}

SCHEMAS = {
    "add_task": _fn("add_task", "Create a new task for the current user.", {
        "title": {"type": "string", "description": "Short task title"},
        "description": {"type": "string"}, "due_date": _DATE, "priority": _PRIORITY}, ["title"]),
    "list_tasks": _fn("list_tasks", "List the current user's tasks. All filters are optional and combine with AND.", {
        "status": _STATUS, "priority": _PRIORITY,
        "due_from": {**_DATE, "description": "Only tasks due on/after this date (YYYY-MM-DD)"},
        "due_to": {**_DATE, "description": "Only tasks due on/before this date (YYYY-MM-DD)"},
        "search": {"type": "string", "description": "One keyword matched against title/description, e.g. 'report'"}}),
    "update_task": _fn("update_task", "Change fields of one task. Use status='done' to complete it. Only pass fields that change.", {
        "task_id": _ID, "title": {"type": "string"}, "description": {"type": "string"},
        "due_date": {**_DATE, "description": "New due date YYYY-MM-DD, or empty string to remove it"},
        "priority": _PRIORITY, "status": _STATUS}, ["task_id"]),
    "delete_task": _fn("delete_task", "Request deletion of one task. The user must confirm in the app before it is actually deleted.",
                       {"task_id": _ID}, ["task_id"]),
    "list_users": _fn("list_users", "Admin only: list all users (id, email, name, role).", {}),
    "assign_task": _fn("assign_task", "Admin only: create a task in another user's list.", {
        "user_email": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
        "due_date": _DATE, "priority": _PRIORITY}, ["user_email", "title"]),
}


def schemas_for(user: User) -> list[dict]:
    return [SCHEMAS[name] for name in tools_for(user)]
