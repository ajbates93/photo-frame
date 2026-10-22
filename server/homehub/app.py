from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Route

from .config import Config, load_config
from .hub import Hub
from .mcp_tasks import BearerGate, build_mcp
from .providers.calendar import CalendarProvider
from .providers.claude import ClaudeProvider, UsageError, valid_session_id
from .providers.keep import (
    ItemNotFound,
    KeepNotSetUp,
    KeepProvider,
    KeepUnreachable,
    ListNotFound,
)
from .providers.photos import PhotosProvider
from .providers.plugs import PlugNotFound, PlugOffline, PlugsProvider
from .providers.screen import ScreenProvider
from .providers.speaker import NothingPlaying, SpeakerProvider, SpeakerUnavailable
from .providers.tasks import TasksProvider, TaskStore, normalise_due
from .providers.weather import WeatherProvider

SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DIST = SERVER_DIR.parent / "dashboard" / "dist"
log = logging.getLogger("homehub.app")
DEFAULT_CONFIG = SERVER_DIR / "config.toml"
USER_AGENT = "homehub/0.1 (family dashboard)"


def bearer_matches(authorization: str | None, shared_secret: str) -> bool:
    """Constant-time check of an Authorization header against the shared secret."""
    if authorization is None:
        return False
    expected = f"Bearer {shared_secret}".encode()
    given = authorization.encode("utf-8", "surrogateescape")
    return secrets.compare_digest(given, expected)


def make_require_secret(shared_secret: str):
    def require_secret(authorization: str | None = Header(default=None)) -> None:
        if not bearer_matches(authorization, shared_secret):
            raise HTTPException(status_code=401, detail="unauthorized")

    return require_secret


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _serve_static(dist_dir: Path, path: str):
    """Serve a dashboard file, falling back to index.html (SPA)."""
    index = dist_dir / "index.html"
    if not index.is_file():
        return JSONResponse({"error": "dashboard not built"}, status_code=404)
    rel = path.lstrip("/")
    if rel:
        candidate = (dist_dir / rel).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist_dir.resolve()):
            return FileResponse(candidate)
    return FileResponse(index)


@dataclass
class Services:
    """Injectable backends; anything left None is built from config."""

    tasks: TaskStore | None = None
    screen: ScreenProvider | None = None
    keep: KeepProvider | None = None
    photos: PhotosProvider | None = None
    plugs: PlugsProvider | None = None
    speaker: SpeakerProvider | None = None
    claude: ClaudeProvider | None = None
    calendar: CalendarProvider | None = None
    weather: WeatherProvider | None = None
    http: httpx.AsyncClient | None = None  # shared by calendar and weather


ASSIGNEES = ("alex", "vicky", "any")
TITLE_MAX = 200
HOOK_MAX_BYTES = 256 * 1024


def _bad(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=400)


OPEN_BODY_MAX_BYTES = 64 * 1024


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """The request body, or None if it is over `limit` bytes (declared or streamed)."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            return None
    return bytes(raw)


def _too_large() -> JSONResponse:
    return JSONResponse({"error": "payload too large"}, status_code=413)


def _parse_object(raw: bytes) -> dict | None:
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def _is_json_type(request: Request) -> bool:
    ctype = request.headers.get("content-type", "")
    return ctype.split(";", 1)[0].strip().lower() == "application/json"


async def _json_object(request: Request, require_json_type: bool = True) -> dict | JSONResponse:
    """Read a capped JSON-object body, or the error response to return instead.

    Open (LAN) write routes insist on Content-Type: application/json: browsers can't send
    it cross-site without a CORS preflight, which this server never grants (CSRF guard).
    """
    if require_json_type and not _is_json_type(request):
        return _bad("Content-Type must be application/json")
    raw = await _read_capped(request, OPEN_BODY_MAX_BYTES)
    if raw is None:
        return _too_large()
    body = _parse_object(raw)
    if body is None:
        return _bad("body must be a JSON object")
    return body


def build_services(cfg: Config, services: Services | None = None) -> tuple[Services, bool]:
    """Fill every backend not injected from config; unconfigured ones stay None.

    The one place providers are constructed. Returns the services and whether this call
    created the shared HTTP client (so the caller must close it).
    """
    services = services or Services()
    if services.tasks is None:
        cfg.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        services.tasks = TaskStore(cfg.data_dir / "state.db")
    if services.screen is None:
        services.screen = ScreenProvider(cfg.screen)
    if services.claude is None:
        services.claude = ClaudeProvider()
    owns_http = False
    wants_calendar = services.calendar is None and any(c.ics_url for c in cfg.calendars)
    wants_weather = services.weather is None and cfg.location is not None
    if services.http is None and (wants_calendar or wants_weather):
        services.http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
        owns_http = True
    if wants_calendar:
        services.calendar = CalendarProvider(cfg, services.http)
    if wants_weather:
        services.weather = WeatherProvider(cfg, services.http)
    if services.keep is None and cfg.keep is not None:
        services.keep = KeepProvider(cfg)
    if services.photos is None and cfg.drive is not None:
        services.photos = PhotosProvider(cfg)
    if cfg.plugs and cfg.tapo is None:
        log.warning("[[plugs]] are configured but [tapo] is missing: plugs are disabled")
    if services.plugs is None and cfg.tapo is not None and cfg.plugs:
        services.plugs = PlugsProvider(cfg.plugs, cfg.tapo)
    if services.speaker is None and cfg.speaker is not None:
        services.speaker = SpeakerProvider(cfg.speaker)
    return services, owns_http


async def aclose_services(services: Services, owns_http: bool) -> None:
    """Release everything build_services may have opened.

    Every close runs independently: one failing never skips the rest. Only the exception
    type is logged (messages can carry paths or addresses).
    """
    async def run(name: str, fn) -> None:
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            log.warning("closing %s failed (%s)", name, type(e).__name__)

    if services.keep is not None:
        await run("keep", services.keep.flush)
    if services.photos is not None:
        await run("photos", services.photos.aclose)
    if services.plugs is not None:
        await run("plugs", services.plugs.aclose)
    if services.speaker is not None:
        await run("speaker", services.speaker.aclose)
    if owns_http and services.http is not None:
        await run("http", services.http.aclose)


DEFAULT_INTERVALS = {
    "events": 300, "weather": 1800, "photos": 21600, "shopping": 60, "tasks": 60,
    "plugs": 15, "speaker": 10, "claude": 15, "screen": 15,
}


def register_providers(hub: Hub, cfg: Config, services: Services) -> None:
    """Register each present provider with its configured interval (section name -> source)."""
    iv = {**DEFAULT_INTERVALS, **cfg.intervals}
    if services.calendar is not None:
        hub.register("events", services.calendar, iv["events"])
    if services.weather is not None:
        hub.register("weather", services.weather, iv["weather"])
    if services.photos is not None:
        services.photos.on_progress = lambda value: hub.set_section("photos", value)
        hub.register("photos", services.photos, iv["photos"])
    if services.keep is not None:
        hub.register("shopping", services.keep, iv["shopping"])
    hub.register("tasks", TasksProvider(services.tasks), iv["tasks"])
    if services.plugs is not None:
        hub.register("plugs", services.plugs, iv["plugs"])
    if services.speaker is not None:
        services.speaker.on_found = lambda: hub.refresh_one("speaker")
        services.speaker.on_change = lambda: hub.refresh_one("speaker")
        hub.register("speaker", services.speaker, iv["speaker"])
    hub.register("claude", services.claude, iv["claude"])
    hub.register("screen", services.screen, iv["screen"])


def create_app(
    cfg: Config,
    hub: Hub | None = None,
    dist: Path | str | None = None,
    services: Services | None = None,
) -> FastAPI:
    hub = hub or Hub(cfg)
    services, owns_http = build_services(cfg, services)
    register_providers(hub, cfg, services)
    tasks, screen, keep = services.tasks, services.screen, services.keep
    plugs, speaker, claude = services.plugs, services.speaker, services.claude
    photos_dir = cfg.data_dir / "photos"
    require_secret = make_require_secret(cfg.shared_secret)
    dist_dir = Path(dist) if dist is not None else Path(os.environ.get("HOMEHUB_DIST", DEFAULT_DIST))

    mcp = build_mcp(tasks, hub)
    mcp_app = mcp.streamable_http_app()  # creates mcp.session_manager

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        try:
            if speaker is not None:
                await speaker.start()
            task = asyncio.create_task(hub.run())
            async with mcp.session_manager.run():
                yield
        finally:
            try:
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:  # noqa: BLE001
                        log.warning("hub stopped with %s", type(e).__name__)
            finally:
                await aclose_services(services, owns_http)

    app = FastAPI(lifespan=lifespan)
    app.state.hub = hub
    app.state.services = services
    # Served at exactly /mcp (a Mount would redirect to /mcp/); bypasses FastAPI
    # dependencies, so the bearer check is an ASGI wrapper sharing bearer_matches.
    app.router.routes.append(Route(
        "/mcp",
        BearerGate(mcp_app, lambda a: bearer_matches(a, cfg.shared_secret)),
        methods=["GET", "POST", "DELETE"],
    ))
    app.state.require_secret = require_secret  # use as Depends(...)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if exc.status_code == 404 and request.method == "GET" and not _is_api(path):
            return _serve_static(dist_dir, path)
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = exc.errors()
        msg = "invalid request"
        if errs:
            loc = ".".join(str(x) for x in errs[0].get("loc", ()) if x != "body")
            msg = f"{loc}: {errs[0].get('msg', 'invalid')}" if loc else str(errs[0].get("msg"))
        return JSONResponse({"error": msg}, status_code=400)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/state")
    async def state():
        return hub.get_state()

    def _keep_error(exc: Exception) -> JSONResponse:
        if isinstance(exc, ItemNotFound):
            return JSONResponse({"error": "unknown item"}, status_code=404)
        if isinstance(exc, ListNotFound):
            return JSONResponse({"error": "Keep list not found"}, status_code=503)
        if isinstance(exc, KeepUnreachable):
            return JSONResponse({"error": "Keep is unreachable"}, status_code=503)
        return JSONResponse({"error": "Keep is not set up"}, status_code=503)

    def _publish_shopping(section: dict | None) -> dict:
        # The write already synced twice; publish its in-memory list instead of a third
        # sync, which would push the reply past the dashboard's 8 s timeout.
        if section is not None:
            hub.set_section("shopping", section)
        return hub.get_state()

    @app.post("/api/shopping/items")
    async def add_shopping_item(request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        text = body.get("text")
        if not isinstance(text, str) or not text:
            return _bad("text required")
        if len(text) > TITLE_MAX:
            return _bad(f"text must be at most {TITLE_MAX} characters")
        if keep is None:
            return _keep_error(KeepNotSetUp())
        try:
            section = await keep.add(text, hub.now())
        except (KeepNotSetUp, KeepUnreachable, ListNotFound) as e:
            return _keep_error(e)
        return _publish_shopping(section)

    @app.patch("/api/shopping/items/{item_id}")
    async def patch_shopping_item(item_id: str, request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        checked = body.get("checked")
        if not isinstance(checked, bool):
            return _bad("checked must be a boolean")
        if keep is None:
            return _keep_error(KeepNotSetUp())
        try:
            section = await keep.set_checked(item_id, checked, hub.now())
        except (KeepNotSetUp, KeepUnreachable, ListNotFound, ItemNotFound) as e:
            return _keep_error(e)
        return _publish_shopping(section)

    @app.post("/api/tasks")
    async def add_task(request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        title = body.get("title")
        if not isinstance(title, str) or not title:
            return _bad("title required")
        if len(title) > TITLE_MAX:
            return _bad(f"title must be at most {TITLE_MAX} characters")
        if body.get("assignee") not in ASSIGNEES:
            return _bad("assignee must be alex, vicky or any")
        try:
            due = normalise_due(body.get("due"))
        except ValueError as e:
            return _bad(str(e))
        await asyncio.to_thread(tasks.add, title, body["assignee"], due)
        await hub.refresh_one("tasks")
        return hub.get_state()

    @app.patch("/api/tasks/{task_id}")
    async def patch_task(task_id: str, request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        done = body.get("done")
        if not isinstance(done, bool):
            return _bad("done must be a boolean")
        if not await asyncio.to_thread(tasks.set_done, task_id, done):
            return JSONResponse({"error": "unknown task"}, status_code=404)
        await hub.refresh_one("tasks")
        return hub.get_state()

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str):
        if not await asyncio.to_thread(tasks.delete, task_id):
            return JSONResponse({"error": "unknown task"}, status_code=404)
        await hub.refresh_one("tasks")
        return hub.get_state()

    @app.get("/api/photos/{photo_id:path}")
    async def get_photo(photo_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", photo_id):
            return _bad("invalid photo id")
        path = photos_dir / f"{photo_id}.jpg"
        if not path.is_file():
            return JSONResponse({"error": "unknown photo"}, status_code=404)
        return FileResponse(
            path, media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.post("/api/plugs/{plug_id}")
    async def set_plug(plug_id: str, request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        if plugs is None or plugs.find(plug_id) is None:
            return JSONResponse({"error": "Plug not found"}, status_code=404)
        on = body.get("on")
        if not isinstance(on, bool):
            return _bad("on must be a boolean")
        try:
            await plugs.set(plug_id, on)
        except PlugNotFound:
            return JSONResponse({"error": "Plug not found"}, status_code=404)
        except PlugOffline as e:
            return JSONResponse({"error": f"{e.name} is offline"}, status_code=503)
        # Publish from the cache: a full refresh polls every plug (4 s each when one hangs)
        # and would push the reply past the dashboard's 8 s timeout.
        hub.set_section("plugs", plugs.section())
        return hub.get_state()

    @app.post("/api/speaker")
    async def set_speaker(request: Request):
        body = await _json_object(request)
        if isinstance(body, JSONResponse):
            return body
        action = body.get("action")
        if action not in ("play", "pause", "volume"):
            return _bad("Invalid speaker action")
        volume = body.get("volume")
        if action == "volume" and (
            isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume)
        ):
            return _bad("Invalid speaker action")
        if speaker is None:
            return JSONResponse({"error": "Speaker unavailable"}, status_code=503)
        try:
            if action == "play":
                await speaker.play()
            elif action == "pause":
                await speaker.pause()
            else:
                await speaker.volume(volume)
        except NothingPlaying:
            return JSONResponse({"error": "Nothing is playing"}, status_code=409)
        except SpeakerUnavailable:
            return JSONResponse({"error": "Speaker unavailable"}, status_code=503)
        await hub.refresh_one("speaker")
        return hub.get_state()

    @app.post("/api/presence", dependencies=[Depends(require_secret)])
    async def presence(request: Request):
        body = await _json_object(request, require_json_type=False)
        if isinstance(body, JSONResponse):
            return body
        active = body.get("active")
        if not isinstance(active, bool):
            return _bad("active must be a boolean")
        at = hub.now()
        if body.get("at") is not None:
            raw = body["at"]
            try:
                if not isinstance(raw, str):
                    raise TypeError
                at = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                return _bad("at must be an ISO 8601 timestamp with offset")
            if at.tzinfo is None:
                return _bad("at must include a UTC offset")
        screen.set_presence(active, min(at, hub.now()))
        await hub.refresh_one("screen")
        return {"ok": True, "mode": hub.get_state()["screen"]["mode"]}

    @app.post("/api/claude/hook", dependencies=[Depends(require_secret)])
    async def claude_hook(request: Request):
        raw = await _read_capped(request, HOOK_MAX_BYTES)
        if raw is None:
            return _too_large()
        body = _parse_object(raw)
        if body is None:
            return _bad("body must be a JSON object")
        if not valid_session_id(body.get("session_id")):
            return _bad("session_id must be a UTF-8 string of at most 200 characters")
        claude.handle_hook(body, hub.now())
        await hub.refresh_one("claude")
        return {"ok": True}

    @app.post("/api/claude/usage", dependencies=[Depends(require_secret)])
    async def claude_usage(request: Request):
        raw = await _read_capped(request, HOOK_MAX_BYTES)
        if raw is None:
            return _too_large()
        body = _parse_object(raw)
        if body is None:
            return _bad("body must be a JSON object")
        try:
            claude.set_usage(body, hub.now())
        except UsageError as e:
            return _bad(str(e))
        await hub.refresh_one("claude")
        return {"ok": True}

    @app.post("/api/screen/wake")
    async def wake():
        screen.wake(hub.now())
        await hub.refresh_one("screen")
        return hub.get_state()

    return app


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        stream=sys.stdout, level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx/httpcore log request URLs at INFO/DEBUG. Those carry secrets (calendar feed
    # links) and the home location (weather), so keep them to warnings only.
    for name in ("httpx", "httpcore", "kasa", "pychromecast", "zeroconf"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # googleapiclient's retry warnings include the request URL (Drive folder id).
    for name in ("googleapiclient.http", "googleapiclient.discovery_cache"):
        logging.getLogger(name).setLevel(logging.ERROR)


def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    from .config import ConfigError

    parser = argparse.ArgumentParser(prog="homehub", description="Family dashboard home hub")
    parser.add_argument(
        "--check", action="store_true",
        help="try one refresh of each provider, print OK/SKIP/FAIL per provider and exit",
    )
    args = parser.parse_args(argv)
    configure_logging(logging.WARNING if args.check else logging.INFO)
    try:
        cfg = load_config(os.environ.get("HOMEHUB_CONFIG", DEFAULT_CONFIG))
    except ConfigError as e:
        raise SystemExit(f"config error: {e}") from None
    if args.check:
        from .check import run_check

        raise SystemExit(asyncio.run(run_check(cfg)))
    # No access log: a line per 5 s state poll would wear the Pi's SD card.
    uvicorn.run(create_app(cfg), host="0.0.0.0", port=8000, log_config=None, access_log=False)
