"""Checks for the parts that must not break: roles, per-user scoping, and the multi-step agent loop.
Run from backend/:  python -m pytest -q   (no network or API key needed; the LLM is faked)."""
import json
import os
import tempfile
from types import SimpleNamespace as NS

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"] = "admin@test.com", "adminpass123"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app).__enter__()  # runs startup (create tables + seed admin)


def signup(email, **extra):
    r = client.post("/auth/signup", json={"name": "T", "email": email, "password": "password123", **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def test_roles_enforced_on_backend():
    headers, user = signup("alice@test.com", role="admin")  # trying to self-promote
    assert user["role"] == "user"
    assert client.get("/admin/users", headers=headers).status_code == 403
    assert client.get("/admin/tasks", headers=headers).status_code == 403
    assert client.get("/admin/users").status_code == 401

    token = client.post("/auth/login", json={"email": "admin@test.com", "password": "adminpass123"}).json()["token"]
    r = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and any(u["email"] == "alice@test.com" for u in r.json())
    assert client.post("/auth/login", json={"email": "admin@test.com", "password": "wrong"}).status_code == 401


def fake_llm(*turns):
    """Returns a stand-in for client.chat.completions.create that replays scripted model turns."""
    script = iter(turns)

    def create(**_):
        calls, text = next(script)
        tool_calls = [NS(id=f"c{i}", function=NS(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
        return NS(choices=[NS(message=NS(content=text, tool_calls=tool_calls or None))])
    return create


def test_agent_multi_step_and_scoping(monkeypatch):
    bob, _ = signup("bob@test.com")
    eve, _ = signup("eve@test.com")
    monkeypatch.setattr(agent.client.chat.completions, "create", fake_llm(
        ([("add_task", {"title": "Submit monthly report", "due_date": "2026-11-13", "priority": "high"})], None),
        ([], "Added it."),
    ))
    r = client.post("/chat", headers=bob, json={"messages": [{"role": "user", "content": "add report task"}]})
    assert r.status_code == 200 and r.json()["tool_calls"][0]["ok"]
    report_id = r.json()["tool_calls"][0]["result"]["created"]["id"]

    # "Mark the report done and add a task to start the next one" -> two tool calls in one request
    monkeypatch.setattr(agent.client.chat.completions, "create", fake_llm(
        ([("list_tasks", {"search": "report"})], None),
        ([("update_task", {"task_id": report_id, "status": "done"}), ("add_task", {"title": "Start next report"})], None),
        ([], "Marked done and added the next one."),
    ))
    r = client.post("/chat", headers=bob, json={"messages": [{"role": "user", "content": "mark report done and add next"}]})
    assert [c["tool"] for c in r.json()["tool_calls"]] == ["list_tasks", "update_task", "add_task"]
    tasks = {t["title"]: t["status"] for t in client.get("/tasks", headers=bob).json()}
    assert tasks == {"Submit monthly report": "done", "Start next report": "todo"}

    # Eve's agent tries to touch Bob's task, inject a user_id, and use an admin tool: all refused.
    monkeypatch.setattr(agent.client.chat.completions, "create", fake_llm(
        ([("update_task", {"task_id": report_id, "status": "todo"}),
          ("add_task", {"title": "x", "user_id": 1}),
          ("assign_task", {"user_email": "bob@test.com", "title": "spam"})], None),
        ([], "Couldn't do that."),
    ))
    r = client.post("/chat", headers=eve, json={"messages": [{"role": "user", "content": "hack"}]})
    assert not any(c["ok"] for c in r.json()["tool_calls"])
    assert client.get("/tasks", headers=eve).json() == []
    assert client.patch(f"/tasks/{report_id}", headers=eve, json={"status": "todo"}).status_code == 404
    assert client.delete(f"/tasks/{report_id}", headers=eve).status_code == 404

    # Agent delete only asks for confirmation; the real delete is the user's REST call.
    monkeypatch.setattr(agent.client.chat.completions, "create", fake_llm(
        ([("delete_task", {"task_id": report_id})], None), ([], "Please confirm."),
    ))
    r = client.post("/chat", headers=bob, json={"messages": [{"role": "user", "content": "delete report"}]})
    assert r.json()["pending_deletes"][0]["id"] == report_id
    assert len(client.get("/tasks", headers=bob).json()) == 2
    assert client.delete(f"/tasks/{report_id}", headers=bob).status_code == 200
    assert len(client.get("/tasks", headers=bob).json()) == 1


def test_llm_failure_is_friendly(monkeypatch):
    headers, _ = signup("carol@test.com")

    def boom(**_):
        raise agent.openai.APITimeoutError(request=None)
    monkeypatch.setattr(agent.client.chat.completions, "create", boom)
    r = client.post("/chat", headers=headers, json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503 and "too long" in r.json()["detail"]
