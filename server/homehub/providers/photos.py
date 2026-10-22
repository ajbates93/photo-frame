"""Photos from a Google Drive folder (service account), resized into a local JPEG cache.

The Drive client is synchronous, so all of it runs on one dedicated worker thread (httplib2
is not thread-safe) with a socket timeout. Photos are processed one at a time
(download -> decode -> save -> free) to stay inside the Pi's memory budget. Names, places and
coordinates are personal, so only Drive ids are ever logged.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import httplib2
import httpx
import pillow_heif
from PIL import Image, ImageOps

from ..config import SERVER_DIR, Config
from ..timeutil import LONDON, iso
from .geocode import Geocoder

pillow_heif.register_heif_opener()

log = logging.getLogger("homehub.photos")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = (
    "nextPageToken, files(id,name,mimeType,md5Checksum,size,"
    "imageMediaMetadata(time,location,width,height,rotation))"
)
HTTP_TIMEOUT_S = 30
NUM_RETRIES = 2
MAX_SIZE = (1280, 800)
JPEG_QUALITY = 82
MD5_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000  # JPEG/MPO (DCT draft keeps the decode small)
MAX_PIXELS_NONJPEG = 30_000_000  # HEIC/PNG/WebP decode at full size
PROGRESS_EVERY = 10


def parse_taken_at(raw: Any) -> str | None:
    """Drive's "YYYY:MM:DD HH:MM:SS" is camera wall time: treat it as London local."""
    if not isinstance(raw, str):
        return None
    try:
        return iso(datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").replace(tzinfo=LONDON))
    except ValueError:
        return None


def _is_transient(e: Exception) -> bool:
    """Network hiccups and Drive 5xx/429 are worth retrying next refresh."""
    status = getattr(getattr(e, "resp", None), "status", None)
    if status is not None:
        try:
            return int(status) >= 500 or int(status) == 429
        except (TypeError, ValueError):
            return False
    return isinstance(e, (OSError, httplib2.HttpLib2Error))


def _process_image(holder: list[bytes]) -> tuple[Image.Image, int, int]:
    """Decode, orient and shrink to fit, reducing as early as the format allows.

    JPEGs use draft mode (DCT-domain downscale); other formats (pillow-heif 1.8 has no
    reduced-size decode) are bounded by the MAX_PIXELS check on the header size. The
    downloaded bytes are released as soon as the bitmap is decoded.
    """
    bio = io.BytesIO(holder.pop())  # sole reference: bytes die with bio
    try:
        with Image.open(bio) as img:
            is_jpeg = img.format in ("JPEG", "MPO")  # Pixel/Samsung photos open as MPO
            if img.width * img.height > (MAX_PIXELS if is_jpeg else MAX_PIXELS_NONJPEG):
                raise ValueError("image too large")
            if is_jpeg:
                img.draft("RGB", (MAX_SIZE[0], MAX_SIZE[0]))  # long side stays >= 1280
            img.load()
            bio.close()  # free the compressed bytes before the transpose/resize copies
            img.thumbnail((MAX_SIZE[0], MAX_SIZE[0]), Image.Resampling.LANCZOS)
            out = ImageOps.exif_transpose(img)
            if out.mode != "RGB":
                out = out.convert("RGB")
            out.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
            return out, out.width, out.height
    finally:
        bio.close()


class PhotosProvider:
    def __init__(
        self,
        cfg: Config,
        service: Any = None,
        geocoder: Geocoder | None = None,
        on_progress: Callable[[list[dict]], None] | None = None,
    ):
        self.cfg = cfg
        self.dir = cfg.data_dir / "photos"
        self._service = service
        self._geocoder = geocoder
        self._http: httpx.AsyncClient | None = None
        self.on_progress = on_progress
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drive")
        self._warned_unconfigured = False
        self._sizes: dict[str, tuple[int, int]] = {}
        self._failed: set[str] = set()
        self._last: list[dict] = []

    # --- setup -------------------------------------------------------------------------

    def _key_path(self) -> Path | None:
        drive = self.cfg.drive
        if drive is None or not drive.folder_id or not drive.service_account_file:
            return None
        return SERVER_DIR / drive.service_account_file  # absolute paths win

    def _get_service(self):
        if self._service is not None:
            return self._service
        key = self._key_path()
        if key is None or not key.is_file():
            return None
        import google_auth_httplib2
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(str(key), scopes=SCOPES)
        http = google_auth_httplib2.AuthorizedHttp(
            creds, http=httplib2.Http(timeout=HTTP_TIMEOUT_S)
        )
        self._service = build("drive", "v3", http=http, cache_discovery=False)
        return self._service

    def _get_geocoder(self) -> Geocoder:
        if self._geocoder is None:
            self._http = httpx.AsyncClient(timeout=10.0)
            self._geocoder = Geocoder(self.cfg.data_dir / "geocode.json", self._http)
        return self._geocoder

    # --- Drive (worker thread) ---------------------------------------------------------

    def _list_all(self, service, root: str) -> list[dict]:
        found: dict[str, dict] = {}
        seen_folders = {root}
        queue = [root]
        while queue:
            folder = queue.pop()
            token = None
            while True:
                req = service.files().list(
                    q=(f"'{folder}' in parents and trashed=false and "
                       f"(mimeType contains 'image/' or mimeType='{FOLDER_MIME}')"),
                    fields=FIELDS,
                    pageSize=1000,
                    pageToken=token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                resp = req.execute(num_retries=NUM_RETRIES)
                for f in resp.get("files", []):
                    if f.get("mimeType") == FOLDER_MIME:
                        if f["id"] not in seen_folders:
                            seen_folders.add(f["id"])
                            queue.append(f["id"])
                    elif MD5_RE.match(f.get("md5Checksum") or ""):
                        found.setdefault(f["md5Checksum"], f)
                token = resp.get("nextPageToken")
                if not token:
                    break
        return list(found.values())

    def _fetch_and_save(self, service, f: dict) -> tuple[int, int] | None:
        """Download one file, write the resized JPEG; return its size or None if skipped."""
        md5 = f["md5Checksum"]
        meta = f.get("imageMediaMetadata") or {}
        try:
            size = int(f.get("size") or 0)
            pixels = int(meta.get("width") or 0) * int(meta.get("height") or 0)
        except (TypeError, ValueError):
            size = pixels = 0
        if size > MAX_BYTES or pixels > MAX_PIXELS:
            log.warning("skipping photo %s (too large)", f.get("id"))
            self._failed.add(md5)
            return None
        try:
            data = service.files().get_media(fileId=f["id"]).execute(num_retries=NUM_RETRIES)
        except Exception as e:  # noqa: BLE001 - classify, then skip this one photo
            log.warning("skipping photo %s (%s)", f.get("id"), type(e).__name__)
            if not _is_transient(e):
                self._failed.add(md5)
            return None
        try:
            holder = [data]
            del data
            img, w, h = _process_image(holder)
            self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self.dir / f"{md5}.jpg.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out:
                img.save(out, "JPEG", quality=JPEG_QUALITY, comment=b"")  # no exif/xmp: stripped
            img.close()
            os.replace(tmp, self.dir / f"{md5}.jpg")
            return w, h
        except Exception as e:  # noqa: BLE001 - one bad photo must not stop the rest
            log.warning("skipping photo %s (%s)", f.get("id"), type(e).__name__)
            self._failed.add(md5)
            return None

    def _cached_size(self, md5: str) -> tuple[int, int] | None:
        if md5 in self._sizes:
            return self._sizes[md5]
        try:
            with Image.open(self.dir / f"{md5}.jpg") as im:
                self._sizes[md5] = im.size
        except (OSError, ValueError):
            return None
        return self._sizes[md5]

    def _has_cache(self) -> bool:
        return self.dir.is_dir() and any(
            p.suffix == ".jpg" and MD5_RE.match(p.stem) for p in self.dir.iterdir())

    def _prune(self, keep: set[str]) -> None:
        """Delete cached photos no longer in Drive; never touches files that aren't ours."""
        if not self.dir.is_dir():
            return
        for p in self.dir.iterdir():
            if p.suffix not in (".jpg", ".tmp"):
                continue
            stem = p.name.removesuffix(".tmp").removesuffix(".jpg")
            if not MD5_RE.match(stem):
                continue
            if p.suffix == ".jpg" and stem in keep:
                continue
            p.unlink(missing_ok=True)
            self._sizes.pop(stem, None)

    # --- provider API ------------------------------------------------------------------

    async def _entry(self, f: dict, size: tuple[int, int]) -> dict:
        md5 = f["md5Checksum"]
        meta = f.get("imageMediaMetadata") or {}
        place = None
        loc = meta.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            place = await self._get_geocoder().place(lat, lon)
        return {
            "id": md5, "url": f"/api/photos/{md5}", "takenAt": parse_taken_at(meta.get("time")),
            "place": place, "width": size[0], "height": size[1],
        }

    @staticmethod
    def _sorted(entries: list[dict]) -> list[dict]:
        dated = sorted((e for e in entries if e["takenAt"]), key=lambda e: e["takenAt"],
                       reverse=True)
        return dated + [e for e in entries if not e["takenAt"]]

    async def _list_remote(self) -> list[dict] | None:
        """List the Drive folder; None when Drive is not configured."""
        loop = asyncio.get_running_loop()
        try:
            service = await loop.run_in_executor(self._executor, self._get_service)
        except Exception as e:  # noqa: BLE001 - keep key paths/details out of logs
            raise RuntimeError(f"drive auth failed ({type(e).__name__})") from None
        if service is None:
            return None
        try:
            return await loop.run_in_executor(
                self._executor, self._list_all, service,
                self.cfg.drive.folder_id if self.cfg.drive else "")
        except Exception as e:  # noqa: BLE001 - HttpError reprs carry the folder id and URL
            status = getattr(getattr(e, "resp", None), "status", None)
            raise RuntimeError(
                f"drive list failed ({type(e).__name__}, status {status})") from None

    async def check(self) -> int:
        """Dry run for `homehub --check`: list the folder, download nothing."""
        files = await self._list_remote()
        if files is None:
            raise RuntimeError("drive key file missing")
        return len(files)

    async def refresh(self, now: datetime) -> list[dict]:
        loop = asyncio.get_running_loop()
        files = await self._list_remote()
        if files is None:
            if not self._warned_unconfigured:
                self._warned_unconfigured = True
                log.warning("photos not configured (no [drive] section or key file)")
            return []
        wanted = {f["md5Checksum"] for f in files}
        if not files and self._has_cache():
            log.warning("Drive folder returned no photos; keeping cache and previous list")
            return self._last
        await loop.run_in_executor(self._executor, self._prune, wanted)

        entries: list[dict] = []
        new: list[dict] = []
        for f in files:
            size = await loop.run_in_executor(self._executor, self._cached_size, f["md5Checksum"])
            if size is None:
                if f["md5Checksum"] not in self._failed:
                    new.append(f)
            else:
                entries.append(await self._entry(f, size))
        if new and entries and self.on_progress is not None:
            self.on_progress(self._sorted(entries))  # warm cache is visible straight away
        fetched = 0
        for f in new:
            size = await loop.run_in_executor(
                self._executor, self._fetch_and_save, self._service, f)
            if size is not None:
                self._sizes[f["md5Checksum"]] = size
                entries.append(await self._entry(f, size))
                fetched += 1
                if fetched % PROGRESS_EVERY == 0 and self.on_progress is not None:
                    self.on_progress(self._sorted(entries))
        log.info("photos: %d cached, %d new", len(files) - len(new), len(new))
        self._last = self._sorted(entries)
        return self._last

    def on_error(self, last: list[dict] | None) -> list[dict]:
        return last if last is not None else []

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        self._executor.shutdown(wait=False, cancel_futures=True)
