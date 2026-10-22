from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..timeutil import iso

DONE_TTL = timedelta(minutes=30)
SILENT_TTL = timedelta(hours=6)
USAGE_TTL = timedelta(minutes=30)
PROJECT_MAX = 100

WORKING_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
WAITING_TYPES = {"permission_prompt", "elicitation_dialog"}
WAITING_MESSAGE = re.compile(r"permission", re.IGNORECASE)
WAITING_TOOLS = {"AskUserQuestion"}
SESSION_ID_MAX = 200
ORDER = {"waiting": 0, "working": 1, "done": 2}


@dataclass
class _Session:
    project: str
    state: str
    since: datetime
    last_seen: datetime


def project_name(cwd: Any) -> str:
    """Basename of cwd only; the full path is never kept."""
    if isinstance(cwd, str):
        parts = [p for p in re.split(r"[\\/]", cwd) if p]
        if parts:
            name = parts[-1].encode("utf-8", "replace").decode("utf-8")
            return name[:PROJECT_MAX]
    return "unknown"


def valid_session_id(sid: Any) -> bool:
    if not isinstance(sid, str) or not sid or len(sid) > SESSION_ID_MAX:
        return False
    try:
        sid.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def public_id(session_id: str) -> str:
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:12]


def _is_waiting(payload: dict) -> bool:
    ntype = payload.get("notification_type")
    if ntype in WAITING_TYPES:
        return True
    if ntype is not None:
        return False  # e.g. idle_prompt fires after every Stop; not "needs you"
    message = payload.get("message")
    return isinstance(message, str) and WAITING_MESSAGE.search(message) is not None


class UsageError(ValueError):
    pass


def _pct_block(body: Any, name: str) -> dict:
    block = body.get(name) if isinstance(body, dict) else None
    if not isinstance(block, dict):
        raise UsageError(f"{name} must be an object")
    pct = block.get("pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct) \
            or not 0 <= pct <= 100:
        raise UsageError(f"{name}.pct must be a number between 0 and 100")
    raw = block.get("resetsAt")
    try:
        if not isinstance(raw, str):
            raise TypeError
        at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise UsageError(f"{name}.resetsAt must be an ISO 8601 timestamp with offset") from None
    if at.tzinfo is None:
        raise UsageError(f"{name}.resetsAt must include a UTC offset")
    return {"pct": pct, "resetsAt": iso(at)}


def validate_usage(body: Any) -> dict:
    if not isinstance(body, dict):
        raise UsageError("body must be a JSON object")
    plan = body.get("plan")
    if not isinstance(plan, str) or not plan.strip() or len(plan) > 50:
        raise UsageError("plan must be a non-empty string")
    return {
        "plan": plan,
        "session": _pct_block(body, "session"),
        "weekly": _pct_block(body, "weekly"),
    }


class ClaudeProvider:
    """In-memory Claude Code session tracker fed by hook payloads, plus pushed usage."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._usage: dict | None = None
        self._usage_at: datetime | None = None

    def handle_hook(self, payload: dict, now: datetime) -> None:
        """Apply a hook payload. Only session_id, project and state are retained."""
        sid = public_id(payload["session_id"])
        event = payload.get("hook_event_name")
        if event == "SessionEnd":
            self._sessions.pop(sid, None)
            return
        if event == "PreToolUse" and payload.get("tool_name") in WAITING_TOOLS:
            new = "waiting"
        elif event in WORKING_EVENTS:
            new = "working"
        elif event == "Stop":
            new = "done"
        elif event == "Notification" and _is_waiting(payload):
            new = "waiting"
        elif event in ("Notification", "SubagentStop"):
            session = self._sessions.get(sid)
            if session is not None:
                session.last_seen = now
            return
        else:
            return
        session = self._sessions.get(sid)
        project = project_name(payload.get("cwd"))
        if session is None:
            self._sessions[sid] = _Session(project, new, now, now)
            return
        if project != "unknown":
            session.project = project
        if session.state != new:
            session.state = new
            session.since = now
        session.last_seen = now

    def set_usage(self, body: Any, now: datetime) -> None:
        self._usage = validate_usage(body)
        self._usage_at = now

    def _prune(self, now: datetime) -> None:
        for sid, s in list(self._sessions.items()):
            if now - s.last_seen > SILENT_TTL or (s.state == "done" and now - s.since > DONE_TTL):
                del self._sessions[sid]

    async def refresh(self, now: datetime) -> dict:
        self._prune(now)
        ordered = sorted(
            self._sessions.items(), key=lambda kv: (ORDER[kv[1].state], -kv[1].since.timestamp())
        )
        usage = None
        if self._usage is not None and self._usage_at is not None \
                and now - self._usage_at <= USAGE_TTL:
            usage = self._usage
        return {
            "sessions": [
                {"id": sid, "project": s.project, "state": s.state, "since": iso(s.since)}
                for sid, s in ordered
            ],
            "usage": usage,
        }
