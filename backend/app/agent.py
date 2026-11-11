"""The TaskPilot agent: an LLM tool-calling loop over the task tools.

Any OpenAI-compatible chat API works (Groq, Gemini, OpenRouter, OpenAI...), picked with env vars.
Loop: send the conversation + tool schemas -> run every tool call the model asks for -> send the
results back -> repeat until the model answers in plain text. This is what makes multi-step requests
("mark X done and add Y") work: the model can call several tools, in one turn or across turns.
"""
import json
import logging
import os
from datetime import date, timedelta

import openai
from openai import OpenAI
from sqlalchemy.orm import Session

from .db import User
from .tools import run_tool, schemas_for

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY") or "not-set",
    base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
    timeout=float(os.getenv("LLM_TIMEOUT", "40")),
    max_retries=2,
)
MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
# Reasoning models (gpt-oss, qwen3) accept low/medium/high; leave unset for models that don't support it.
EXTRA_ARGS = {"reasoning_effort": v} if (v := os.getenv("LLM_REASONING_EFFORT")) else {}
MAX_STEPS = 8  # model round-trips per user message; stops runaway loops

SYSTEM_PROMPT = """You are TaskPilot, an assistant that manages {name}'s to-do list by calling tools.
Today is {weekday}, {today}. {role_note}
Calendar for the next two weeks (use it, don't compute weekdays yourself): {calendar}

Rules:
- Always use tools to read or change tasks. Never invent tasks, ids or results.
  Only say you did something if a tool result in this conversation confirms it.
- To change or delete a task the user names, first call list_tasks (search with one keyword) to get its id.
  If several tasks match and it's unclear which one is meant, ask instead of guessing.
- A message can ask for several things ("mark X done and add Y"). Do ALL of them before replying.
  Make independent tool calls together in one step instead of one per step.
- Turn relative dates into YYYY-MM-DD with the calendar. "Friday"/"next Monday" = the first such day after today.
  "This week" = today through Sunday {sunday}.
- Only set a description when the user gives details beyond the title.
- delete_task only REQUESTS deletion. Tell the user it is waiting for them to press Confirm.
- If a tool returns an error, fix the call or explain the problem briefly.
- Reply in a short, friendly message saying exactly what you did. Plain text only: no markdown, no ** or #.
  Use "- " bullets for lists and include due dates and priorities when listing tasks.
  If the request isn't about tasks, say what you can help with."""

ADMIN_NOTE = "The user is an ADMIN: they can also list all users and assign tasks to other users by email."


class LLMUnavailable(Exception):
    """The LLM provider failed or timed out; the message is safe to show the user."""


def _system_prompt(user: User, today: date) -> str:
    sunday = today + timedelta(days=6 - today.weekday())
    calendar = ", ".join(f"{d:%a} {d.isoformat()}" for d in (today + timedelta(days=i) for i in range(1, 15)))
    return SYSTEM_PROMPT.format(name=user.name, today=today.isoformat(), weekday=today.strftime("%A"), calendar=calendar,
                                sunday=sunday.isoformat(), role_note=ADMIN_NOTE if user.role == "admin" else "")


def _call_llm(messages, tools):
    try:
        return client.chat.completions.create(model=MODEL, messages=messages, tools=tools, temperature=0.1, **EXTRA_ARGS)
    except openai.APITimeoutError:
        raise LLMUnavailable("The AI is taking too long to respond. Please try again in a moment.")
    except openai.RateLimitError:
        raise LLMUnavailable("The AI service is busy (rate limit reached). Please wait a few seconds and try again.")
    except openai.AuthenticationError:
        logging.exception("LLM auth failed")
        raise LLMUnavailable("The AI service is not configured correctly. Please contact the admin.")
    except openai.BadRequestError as e:
        # e.g. Groq's "tool_use_failed" when the model emits a malformed tool call
        logging.warning("LLM bad request: %s", e)
        raise LLMUnavailable("The AI got confused by that request. Please try rephrasing it.")
    except openai.APIError:
        logging.exception("LLM call failed")
        raise LLMUnavailable("The AI service is unavailable right now. Please try again shortly.")


def run_agent(db: Session, user: User, history: list[dict], today: date) -> dict:
    messages = [{"role": "system", "content": _system_prompt(user, today)}, *history]
    tools = schemas_for(user)
    calls, pending_deletes = [], []

    for _ in range(MAX_STEPS):
        msg = _call_llm(messages, tools).choices[0].message
        if not msg.tool_calls:
            return {"reply": msg.content or "Done.", "tool_calls": calls, "pending_deletes": pending_deletes}

        # Echo the assistant turn back with only the standard fields (some providers reject extras).
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls]})

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = run_tool(db, user, tc.function.name, args) if isinstance(args, dict) else {"error": "Arguments must be a JSON object."}
            except json.JSONDecodeError:
                args, result = {}, {"error": "Arguments were not valid JSON."}
            calls.append({"tool": tc.function.name, "args": args, "result": result, "ok": "error" not in result})
            if result.get("status") == "awaiting_user_confirmation":
                pending_deletes.append(result["task"])
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    return {"reply": "I had to stop because that request needed too many steps. Please split it into smaller requests.",
            "tool_calls": calls, "pending_deletes": pending_deletes}
