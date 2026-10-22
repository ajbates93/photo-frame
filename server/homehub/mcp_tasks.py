from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .hub import Hub
from .providers.tasks import TaskStore, normalise_due
from .timeutil import LONDON, iso, local_midnight

TITLE_MAX = 200

ADD_DESCRIPTION = (
    "Add a task to the family dashboard. The time zone is Europe/London. "
    "'After work' means 18:00 local time. `due` is ISO 8601: give a plain date "
    "(YYYY-MM-DD) when no time of day was mentioned (the task is then date-only), or a "
    "date and time (e.g. 2026-10-22T18:00) when one was; times without an offset are "
    "Europe/London local time. `assignee` is alex, vicky or any (default any)."
)


def parse_due(value: str | None) -> str | None:
    """Turn a tool `due` into a London-offset ISO string (None for no due date)."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            return iso(local_midnight(date.fromisoformat(text)))
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LONDON)
        return normalise_due(iso(dt))
    except ValueError:
        raise ValueError(
            "due must be YYYY-MM-DD (date only) or an ISO 8601 date-time such as "
            "2026-10-22T18:00 (Europe/London unless an offset is given)"
        ) from None


def _reply(message: str, payload: object) -> str:
    return f"{message}\n{json.dumps(payload)}"


def build_mcp(tasks: TaskStore, hub: Hub) -> FastMCP:
    mcp = FastMCP(
        "family-tasks",
        instructions="Manage the family task list shown on the home dashboard.",
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        # Reachable by LAN IP/hostname; access is controlled by the bearer secret instead.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    async def changed() -> None:
        await hub.refresh_one("tasks")

    @mcp.tool(description=ADD_DESCRIPTION)
    async def add_task(
        title: str,
        assignee: Literal["alex", "vicky", "any"] = "any",
        due: str | None = None,
    ) -> str:
        title = title.strip()
        if not title:
            raise ValueError("title must not be empty")
        if len(title) > TITLE_MAX:
            raise ValueError(f"title must be at most {TITLE_MAX} characters")
        stored_due = parse_due(due)
        task = await asyncio.to_thread(tasks.add, title, assignee, stored_due)
        await changed()
        when = f", due {stored_due}" if stored_due else ""
        return _reply(f"Added task '{title}' for {assignee}{when}.", task)

    @mcp.tool(
        description=(
            "List family tasks. Open tasks only unless include_done is true. "
            "Due times are Europe/London."
        )
    )
    async def list_tasks(include_done: bool = False) -> str:
        found = await asyncio.to_thread(tasks.list)
        if not include_done:
            found = [t for t in found if not t["done"]]
        return _reply(f"{len(found)} task(s).", found)

    @mcp.tool(description="Mark a family task as done, by its id (from list_tasks).")
    async def complete_task(id: str) -> str:
        if not await asyncio.to_thread(tasks.set_done, id, True):
            raise ValueError(f"unknown task id: {id}")
        await changed()
        task = next((t for t in await asyncio.to_thread(tasks.list) if t["id"] == id), None)
        return _reply(f"Completed task {id}.", task)

    @mcp.tool(description="Permanently delete a family task, by its id (from list_tasks).")
    async def delete_task(id: str) -> str:
        if not await asyncio.to_thread(tasks.delete, id):
            raise ValueError(f"unknown task id: {id}")
        await changed()
        return _reply(f"Deleted task {id}.", {"id": id})

    return mcp


class BearerGate:
    """ASGI wrapper: 401 JSON unless `is_authorized(Authorization header)` is true."""

    def __init__(self, app, is_authorized: Callable[[str | None], bool]):
        self.app = app
        self.is_authorized = is_authorized

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope["headers"]}
            given = headers.get(b"authorization")
            value = given.decode("utf-8", "surrogateescape") if given is not None else None
            if not self.is_authorized(value):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

