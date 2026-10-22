from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from homehub.mcp_tasks import build_mcp, parse_due
from homehub.providers.tasks import TaskStore


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "t.db")


@pytest.fixture
def refreshed(hub):
    calls = []

    async def refresh_one(name):
        calls.append(name)
        return True

    hub.refresh_one = refresh_one
    return calls


@pytest.fixture
def server(store, hub, refreshed):
    return build_mcp(store, hub)._mcp_server


def payload(result) -> object:
    return json.loads(result.content[0].text.split("\n", 1)[1])


async def test_lists_four_tools_with_guidance(server):
    async with connect(server) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"add_task", "list_tasks", "complete_task", "delete_task"}
        desc = tools["add_task"].description
        assert "Europe/London" in desc and "18:00" in desc and "date-only" in desc


async def test_add_date_only_is_local_midnight(store, refreshed, server):
    async with connect(server) as session:
        r = await session.call_tool("add_task", {"title": "Bins", "due": "2026-10-22"})
        assert not r.isError
        task = payload(r)
        assert task["due"] == "2026-10-22T00:00:00+01:00"
        assert task["assignee"] == "any"
        assert store.list()[0]["id"] == task["id"]
        assert refreshed == ["tasks"]


async def test_add_naive_datetime_is_london_time(server):
    async with connect(server) as session:
        winter = payload(await session.call_tool(
            "add_task", {"title": "x", "assignee": "vicky", "due": "2026-12-01T18:00"}))
        assert winter["due"] == "2026-12-01T18:00:00+00:00"
        summer = payload(await session.call_tool("add_task", {"title": "y", "due": "2026-07-01T18:00"}))
        assert summer["due"] == "2026-07-01T18:00:00+01:00"


async def test_add_offset_datetime_converted_to_london(server):
    async with connect(server) as session:
        task = payload(await session.call_tool(
            "add_task", {"title": "x", "due": "2026-07-01T17:00:00+00:00"}))
        assert task["due"] == "2026-07-01T18:00:00+01:00"


@pytest.mark.parametrize("bad", ["tomorrow", "2026-13-40", "2026-10-22T25:00"])
async def test_add_bad_due_is_tool_error(store, bad, server):
    async with connect(server) as session:
        r = await session.call_tool("add_task", {"title": "x", "due": bad})
        assert r.isError
        assert "due must be" in r.content[0].text
        assert store.list() == []


async def test_add_bad_assignee_and_title_are_errors(store, server):
    async with connect(server) as session:
        assert (await session.call_tool("add_task", {"title": "x", "assignee": "bob"})).isError
        assert (await session.call_tool("add_task", {"title": "  "})).isError
        assert (await session.call_tool("add_task", {"title": "x" * 201})).isError
        assert store.list() == []


async def test_list_excludes_done_by_default(store, server):
    async with connect(server) as session:
        a = store.add("open", "any", None)
        b = store.add("finished", "alex", None)
        store.set_done(b["id"], True)
        assert [t["id"] for t in payload(await session.call_tool("list_tasks", {}))] == [a["id"]]
        both = payload(await session.call_tool("list_tasks", {"include_done": True}))
        assert {t["id"] for t in both} == {a["id"], b["id"]}


async def test_complete_and_delete_by_id(store, refreshed, server):
    async with connect(server) as session:
        t = store.add("thing", "any", None)
        done = payload(await session.call_tool("complete_task", {"id": t["id"]}))
        assert done["done"] is True and store.list()[0]["done"] is True
        r = await session.call_tool("delete_task", {"id": t["id"]})
        assert not r.isError and store.list() == []
        assert refreshed == ["tasks", "tasks"]


async def test_unknown_id_is_tool_error(refreshed, server):
    async with connect(server) as session:
        for name in ("complete_task", "delete_task"):
            r = await session.call_tool(name, {"id": "nope"})
            assert r.isError and "unknown task id" in r.content[0].text
        assert refreshed == []


def test_parse_due_none():
    assert parse_due(None) is None and parse_due("") is None


INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}
HEADERS = {"Accept": "application/json, text/event-stream"}


def test_http_requires_bearer(client):
    r = client.post("/mcp", json=INIT, headers=HEADERS)
    assert r.status_code == 401 and r.json() == {"error": "unauthorized"}
    bad = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_http_with_bearer_serves_mcp_and_shares_store(client):
    h = {**HEADERS, "Authorization": "Bearer test-secret"}
    r = client.post("/mcp", json=INIT, headers=h)
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "family-tasks"
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "add_task", "arguments": {"title": "Via HTTP", "due": "2026-10-23"}}}
    assert client.post("/mcp", json=call, headers=h).status_code == 200
    titles = [t["title"] for t in client.get("/api/state").json()["tasks"]]
    assert "Via HTTP" in titles
