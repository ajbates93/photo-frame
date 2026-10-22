"""`homehub --check`: one refresh of every provider, one line each.

Output is counts and short reasons only, never titles, names, emails, URLs, IPs or places.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from .app import Services, aclose_services, build_services
from .config import Config
from .providers.calendar import FeedError
from .providers.keep import KeepNotSetUp, KeepUnreachable, ListNotFound
from .timeutil import now_london

TIMEOUT_S = 45.0
ORDER = ("calendar", "weather", "photos", "keep", "tasks", "plugs", "speaker", "claude", "screen")
SKIP = "not configured"


class CheckError(Exception):
    """A failure whose message is already safe to print."""


def _reason(e: Exception) -> str:
    if isinstance(e, TimeoutError):
        return "timed out"
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    if isinstance(e, KeepNotSetUp):
        return "Keep is not set up"
    if isinstance(e, KeepUnreachable):
        return "Keep is unreachable"
    if isinstance(e, ListNotFound):
        return "list not found"
    if isinstance(e, (FeedError, CheckError)):
        return str(e)
    return type(e).__name__  # never str(e): it can carry URLs or addresses


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


async def run_check(
    cfg: Config,
    services: Services | None = None,
    timeout: float = TIMEOUT_S,
    out: Callable[[str], None] = print,
) -> int:
    """Print one OK/SKIP/FAIL line per provider; return 1 if any FAIL, else 0."""
    services, owns_http = build_services(cfg, services)
    now = now_london()
    checks: dict[str, Callable[[], Awaitable[str]] | str] = {}

    def add(name: str, fn: Callable[[], Awaitable[str]] | None, why: str = SKIP) -> None:
        checks[name] = fn if fn is not None else why

    async def calendar() -> str:
        text = _plural(len(await services.calendar.refresh(now)), "event")
        ok, total = getattr(services.calendar, "feeds_ok", (0, 0))
        return f"{text}, {ok}/{total} feeds" if total else text

    async def weather() -> str:
        data = await services.weather.refresh(now)
        return _plural(len(data["hourly"]), "hourly entry", "hourly entries")

    async def photos() -> str:
        try:
            n = await services.photos.check()
        except RuntimeError as e:  # the provider's messages carry no paths or ids
            raise CheckError(str(e)) from None
        return f"{_plural(n, 'photo')} listed"

    async def keep() -> str:
        if not services.keep.set_up():
            raise KeepNotSetUp
        data = await services.keep.refresh(now)
        if not getattr(services.keep, "list_found", True):
            raise ListNotFound
        return _plural(len(data["items"]), "item")

    async def tasks() -> str:
        from .providers.tasks import TasksProvider

        return _plural(len(await TasksProvider(services.tasks).refresh(now)), "task")

    async def plugs() -> str:
        data = await services.plugs.refresh(now)
        up = sum(1 for p in data if p["reachable"])
        if data and not up:
            raise CheckError(f"0 of {len(data)} reachable")
        return f"{up} of {len(data)} reachable"

    async def speaker() -> str:
        sp = services.speaker
        await sp.start()
        await sp.wait_discovered()
        if await sp.refresh(now) is None:
            raise CheckError("speaker not found")
        return "found"

    async def claude() -> str:
        return _plural(len((await services.claude.refresh(now))["sessions"]), "session")

    async def screen() -> str:
        return f"mode {(await services.screen.refresh(now))['mode']}"

    add("calendar", calendar if services.calendar else None)
    add("weather", weather if services.weather else None)
    add("photos", photos if services.photos else None)
    add("keep", keep if services.keep else None)
    add("tasks", tasks)
    if services.plugs:
        add("plugs", plugs)
    elif cfg.plugs and cfg.tapo is None:
        add("plugs", None, "FAIL:[tapo] section missing")
    else:
        add("plugs", None)
    add("speaker", speaker if services.speaker else None)
    add("claude", claude)
    add("screen", screen)

    async def one(name: str) -> tuple[str, str]:
        job = checks[name]
        if isinstance(job, str):
            if job.startswith("FAIL:"):
                return "FAIL", job[5:]
            return "SKIP", job
        try:
            return "OK", await asyncio.wait_for(job(), timeout)
        except Exception as e:  # noqa: BLE001
            return "FAIL", _reason(e)

    try:
        results = await asyncio.gather(*(one(n) for n in ORDER))
    finally:
        await aclose_services(services, owns_http)
    failed = False
    for name, (status, detail) in zip(ORDER, results):
        failed |= status == "FAIL"
        out(f"{status:<4} {name}  ({detail})" if detail else f"{status:<4} {name}")
    return 1 if failed else 0
