from __future__ import annotations

import io
import logging
import re
import stat

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from homehub.app import Services, create_app
from homehub.config import Config, Drive
from homehub.hub import Hub
from homehub.providers.photos import PhotosProvider
from tests.conftest import FIXED_NOW

ROOT = "root"
FOLDER = "application/vnd.google-apps.folder"


def jpeg(size=(400, 300), orientation=None, color=(200, 30, 30)) -> bytes:
    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[0x010F] = "PhoneCo"  # Make: must be stripped
    if orientation:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def private_jpeg() -> bytes:
    """JPEG carrying a GPS IFD, XMP and a COM comment, all of which must not survive."""
    exif = Image.Exif()
    exif[0x010F] = "PhoneCo"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (51.0, 30.0, 0.0), "W", (0.0, 6.0, 0.0)
    xmp = (b'<?xpacket begin="" id="x"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
           b"secret-xmp</x:xmpmeta><?xpacket end='w'?>")
    buf = io.BytesIO()
    Image.new("RGB", (400, 300)).save(buf, "JPEG", exif=exif, xmp=xmp, comment=b"secret-comment")
    return buf.getvalue()


def meta(fid, md5, time=None, loc=None, w=100, h=100):
    m = {"width": w, "height": h}
    if time:
        m["time"] = time
    if loc:
        m["location"] = {"latitude": loc[0], "longitude": loc[1]}
    return {"id": fid, "name": f"{fid}.jpg", "mimeType": "image/jpeg", "md5Checksum": md5,
            "imageMediaMetadata": m}


class FakeDrive:
    """Minimal stand-in for the googleapiclient Drive v3 resource."""

    def __init__(self, tree: dict[str, list[dict]], blobs: dict[str, bytes], page=2):
        self.tree, self.blobs, self.page = tree, blobs, page
        self.list_calls: list[dict] = []
        self.downloads: list[str] = []

    def files(self):
        return self

    def list(self, **kw):
        self.list_calls.append(kw)
        parent = re.search(r"'([^']+)' in parents", kw["q"]).group(1)
        items = self.tree.get(parent, [])
        start = int(kw.get("pageToken") or 0)
        chunk = items[start:start + self.page]
        body = {"files": chunk}
        if start + self.page < len(items):
            body["nextPageToken"] = str(start + self.page)
        return _Req(body)

    def get_media(self, fileId):
        self.downloads.append(fileId)
        return _Req(self.blobs[fileId])


class _Req:
    def __init__(self, value):
        self.value = value

    def execute(self, num_retries=0):
        return self.value


class FakeGeo:
    def __init__(self):
        self.calls = []

    async def place(self, lat, lon):
        self.calls.append((lat, lon))
        return "Testville"


@pytest.fixture
def cfg(tmp_path):
    return Config(shared_secret="s", drive=Drive("root", "x.json"), data_dir=tmp_path / "data")


def provider(cfg, drive, geo=None):
    return PhotosProvider(cfg, service=drive, geocoder=geo or FakeGeo())


def tree_and_blobs():
    tree = {
        ROOT: [
            meta("a", "a" * 32, "2026:07:01 12:00:00", (51.5, -0.1)),
            {"id": "sub", "name": "sub", "mimeType": FOLDER},
            meta("b", "b" * 32, "2025:01:15 09:30:00"),
            meta("c", "c" * 32),  # undated
        ],
        "sub": [meta("d", "d" * 32, "2026:12:25 08:00:00")],
    }
    blobs = {k: jpeg() for k in "abcd"}
    return tree, blobs


async def test_lists_recursively_across_pages_and_orders(cfg):
    tree, blobs = tree_and_blobs()
    drive = FakeDrive(tree, blobs, page=2)
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert [p["id"] for p in out] == ["d" * 32, "a" * 32, "b" * 32, "c" * 32]
    assert any(c.get("pageToken") for c in drive.list_calls)
    assert out[0] == {
        "id": "d" * 32, "url": f"/api/photos/{'d' * 32}",
        "takenAt": "2026-12-25T08:00:00+00:00", "place": None, "width": 400, "height": 300,
    }
    assert out[-1]["takenAt"] is None
    fields = drive.list_calls[0]["fields"]
    assert "md5Checksum" in fields and "imageMediaMetadata(time,location,width,height,rotation)" in fields


async def test_taken_at_uses_bst_offset_and_place_from_geocoder(cfg):
    tree, blobs = tree_and_blobs()
    geo = FakeGeo()
    out = await provider(cfg, FakeDrive(tree, blobs), geo).refresh(FIXED_NOW)
    a = next(p for p in out if p["id"] == "a" * 32)
    assert a["takenAt"] == "2026-07-01T12:00:00+01:00"
    assert a["place"] == "Testville"
    assert geo.calls == [(51.5, -0.1)]


async def test_resize_to_fit_and_strip_exif(cfg):
    drive = FakeDrive({ROOT: [meta("a", "a" * 32)]}, {"a": jpeg((4000, 3000))})
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    f = cfg.data_dir / "photos" / f"{'a' * 32}.jpg"
    with Image.open(f) as im:
        assert im.size == (1067, 800)
        assert len(im.getexif()) == 0
        assert im.format == "JPEG"
    assert (out[0]["width"], out[0]["height"]) == (1067, 800)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


async def test_exif_orientation_applied(cfg):
    drive = FakeDrive({ROOT: [meta("a", "a" * 32)]}, {"a": jpeg((800, 400), orientation=6)})
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert (out[0]["width"], out[0]["height"]) == (400, 800)


async def test_cache_reused_and_orphans_removed(cfg):
    tree, blobs = tree_and_blobs()
    drive = FakeDrive(tree, blobs)
    p = provider(cfg, drive)
    await p.refresh(FIXED_NOW)
    assert sorted(drive.downloads) == ["a", "b", "c", "d"]
    photos = cfg.data_dir / "photos"
    (photos / ("e" * 32 + ".jpg")).write_bytes(b"old")
    tree[ROOT] = [x for x in tree[ROOT] if x["id"] != "b"]
    drive.downloads.clear()
    out = await p.refresh(FIXED_NOW)
    assert drive.downloads == []
    assert not (photos / ("b" * 32 + ".jpg")).exists()
    assert not (photos / ("e" * 32 + ".jpg")).exists()
    assert {x["id"] for x in out} == {"a" * 32, "c" * 32, "d" * 32}


async def test_undecodable_file_skipped_with_id_only_warning(cfg, caplog):
    tree = {ROOT: [meta("bad1", "f" * 32), meta("a", "a" * 32)]}
    drive = FakeDrive(tree, {"bad1": b"not an image", "a": jpeg()})
    with caplog.at_level(logging.INFO):
        out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert [p["id"] for p in out] == ["a" * 32]
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1 and "bad1" in warns[0].getMessage()
    assert "bad1.jpg" not in caplog.text


async def test_unconfigured_returns_empty(tmp_path):
    cfg = Config(shared_secret="s", data_dir=tmp_path)
    assert await PhotosProvider(cfg).refresh(FIXED_NOW) == []
    cfg = Config(shared_secret="s", drive=Drive("root", str(tmp_path / "missing.json")),
                 data_dir=tmp_path)
    assert await PhotosProvider(cfg).refresh(FIXED_NOW) == []


async def test_publishes_cached_list_before_downloads(cfg):
    tree, blobs = tree_and_blobs()
    p = provider(cfg, FakeDrive(tree, blobs))
    await p.refresh(FIXED_NOW)
    seen = []
    p2 = provider(cfg, FakeDrive(tree, blobs))
    p2.on_progress = lambda photos: seen.append(len(photos))
    tree[ROOT].append(meta("n", "9" * 32))
    blobs["n"] = jpeg()
    await p2.refresh(FIXED_NOW)
    assert seen and seen[0] == 4  # the 4 warm photos appear before the new one is fetched


def test_on_error_keeps_last(cfg):
    p = provider(cfg, FakeDrive({}, {}))
    assert p.on_error([{"id": "x"}]) == [{"id": "x"}]
    assert p.on_error(None) == []


def make_client(cfg, tmp_path):
    hub = Hub(cfg, now=lambda: FIXED_NOW)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    return TestClient(create_app(cfg, hub, dist=dist, services=Services(photos=None)))


def test_route_headers_400_404(cfg, tmp_path):
    photos = cfg.data_dir / "photos"
    photos.mkdir(parents=True)
    (photos / ("a" * 32 + ".jpg")).write_bytes(jpeg())
    with make_client(cfg, tmp_path) as c:
        r = c.get(f"/api/photos/{'a' * 32}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert c.get("/api/photos/..%2fx").status_code == 400
        assert c.get("/api/photos/../x").status_code in (400, 404)
        assert c.get("/api/photos/ZZZ").status_code == 400
        r = c.get(f"/api/photos/{'b' * 32}")
        assert r.status_code == 404 and "error" in r.json()


async def test_privacy_markers_stripped(cfg):
    src = private_jpeg()
    assert b"secret-xmp" in src and b"secret-comment" in src
    drive = FakeDrive({ROOT: [meta("a", "a" * 32)]}, {"a": src})
    await provider(cfg, drive).refresh(FIXED_NOW)
    raw = (cfg.data_dir / "photos" / f"{'a' * 32}.jpg").read_bytes()
    assert b"secret-xmp" not in raw and b"secret-comment" not in raw
    assert b"Exif" not in raw and b"PhoneCo" not in raw
    with Image.open(io.BytesIO(raw)) as im:
        assert len(im.getexif()) == 0 and not im.getexif().get_ifd(0x8825)
        assert "comment" not in im.info and "xmp" not in im.info


async def test_oversized_files_skipped_without_download(cfg, caplog):
    big = meta("big", "1" * 32)
    big["size"] = str(31 * 1024 * 1024)
    wide = meta("wide", "2" * 32, w=10000, h=6000)
    ok = meta("ok", "3" * 32)
    drive = FakeDrive({ROOT: [big, wide, ok]}, {"ok": jpeg()})
    with caplog.at_level(logging.INFO):
        out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert drive.downloads == ["ok"]
    assert [p["id"] for p in out] == ["3" * 32]
    assert "big.jpg" not in caplog.text and "wide.jpg" not in caplog.text


async def test_failing_file_attempted_once_across_refreshes(cfg):
    drive = FakeDrive({ROOT: [meta("bad", "f" * 32)]}, {"bad": b"junk"})
    p = provider(cfg, drive)
    await p.refresh(FIXED_NOW)
    await p.refresh(FIXED_NOW)
    assert drive.downloads == ["bad"]


async def test_oversized_header_dimensions_rejected_after_download(cfg):
    from homehub.providers import photos as ph

    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    old = ph.MAX_PIXELS_NONJPEG
    ph.MAX_PIXELS_NONJPEG = 50  # metadata lied (0x0); header check still catches it
    try:
        drive = FakeDrive({ROOT: [meta("a", "a" * 32, w=0, h=0)]}, {"a": buf.getvalue()})
        p = provider(cfg, drive)
        assert await p.refresh(FIXED_NOW) == []
        await p.refresh(FIXED_NOW)
        assert drive.downloads == ["a"]  # blacklisted, not retried
    finally:
        ph.MAX_PIXELS_NONJPEG = old


async def test_nonjpeg_cap_is_lower_than_jpeg_cap(cfg, monkeypatch):
    from homehub.providers import photos as ph

    assert ph.MAX_PIXELS_NONJPEG == 30_000_000 and ph.MAX_PIXELS == 50_000_000
    monkeypatch.setattr(ph, "MAX_PIXELS_NONJPEG", 100)
    monkeypatch.setattr(ph, "MAX_PIXELS", 1_000_000)
    png = io.BytesIO()
    Image.new("RGB", (100, 100)).save(png, "PNG")  # 10_000 px: over the non-JPEG cap
    drive = FakeDrive({ROOT: [meta("p", "1" * 32), meta("j", "2" * 32)]},
                      {"p": png.getvalue(), "j": jpeg((100, 100))})
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert [x["id"] for x in out] == ["2" * 32]


async def test_mpo_uses_jpeg_draft(cfg, monkeypatch):
    from PIL import JpegImagePlugin

    buf = io.BytesIO()
    frames = [Image.new("RGB", (4000, 3000), (9, 9, 9)), Image.new("RGB", (400, 300))]
    frames[0].save(buf, "MPO", save_all=True, append_images=frames[1:])
    with Image.open(io.BytesIO(buf.getvalue())) as probe:
        assert probe.format == "MPO"
    calls = []
    real = JpegImagePlugin.JpegImageFile.draft
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft",
                        lambda self, *a: (calls.append(a), real(self, *a))[1])
    drive = FakeDrive({ROOT: [meta("a", "a" * 32)]}, {"a": buf.getvalue()})
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert calls and (out[0]["width"], out[0]["height"]) == (1067, 800)


async def test_transient_download_failure_is_retried(cfg):
    from googleapiclient.errors import HttpError
    from httplib2 import Response

    class Flaky(FakeDrive):
        def get_media(self, fileId):
            self.downloads.append(fileId)
            if len(self.downloads) == 1:
                class R:
                    def execute(self, num_retries=0):
                        raise HttpError(Response({"status": 503}), b"busy")
                return R()
            return _Req(self.blobs[fileId])

    drive = Flaky({ROOT: [meta("a", "a" * 32)]}, {"a": jpeg()})
    p = provider(cfg, drive)
    assert await p.refresh(FIXED_NOW) == []
    assert len(await p.refresh(FIXED_NOW)) == 1
    assert drive.downloads == ["a", "a"]


async def test_permanent_download_failure_not_retried(cfg):
    from googleapiclient.errors import HttpError
    from httplib2 import Response

    class Gone(FakeDrive):
        def get_media(self, fileId):
            self.downloads.append(fileId)

            class R:
                def execute(self, num_retries=0):
                    raise HttpError(Response({"status": 404}), b"gone")
            return R()

    drive = Gone({ROOT: [meta("a", "a" * 32)]}, {})
    p = provider(cfg, drive)
    await p.refresh(FIXED_NOW)
    await p.refresh(FIXED_NOW)
    assert drive.downloads == ["a"]


async def test_png_is_converted(cfg):
    buf = io.BytesIO()
    Image.new("RGBA", (3000, 2000), (1, 2, 3, 128)).save(buf, "PNG")
    drive = FakeDrive({ROOT: [meta("a", "a" * 32)]}, {"a": buf.getvalue()})
    out = await provider(cfg, drive).refresh(FIXED_NOW)
    assert (out[0]["width"], out[0]["height"]) == (1200, 800)


async def test_drive_error_does_not_leak_folder_id(cfg, caplog):
    from googleapiclient.errors import HttpError
    from httplib2 import Response

    folder = "FOLDERSECRET123"
    cfg.drive = Drive(folder, "x.json")

    class Boom(FakeDrive):
        def list(self, **kw):
            raise HttpError(Response({"status": 403}), b"denied",
                            uri=f"https://www.googleapis.com/drive/v3/files?q={folder}")

    hub = Hub(cfg, now=lambda: FIXED_NOW)
    hub.register("photos", provider(cfg, Boom({}, {})), 60)
    with caplog.at_level(logging.DEBUG):
        assert await hub.refresh_one("photos") is False
    assert folder not in caplog.text
    assert "403" in caplog.text


def test_googleapiclient_loggers_quietened():
    from homehub.app import configure_logging

    configure_logging()
    assert logging.getLogger("googleapiclient.http").level == logging.ERROR


async def test_prune_only_touches_our_files(cfg):
    tree, blobs = tree_and_blobs()
    p = provider(cfg, FakeDrive(tree, blobs))
    await p.refresh(FIXED_NOW)
    photos = cfg.data_dir / "photos"
    (photos / "notes.jpg").write_bytes(b"mine")
    (photos / "readme.txt").write_text("mine")
    (photos / ("e" * 32 + ".jpg.tmp")).write_bytes(b"x")
    await p.refresh(FIXED_NOW)
    assert (photos / "notes.jpg").exists() and (photos / "readme.txt").exists()
    assert not (photos / ("e" * 32 + ".jpg.tmp")).exists()


async def test_empty_listing_keeps_cache_and_previous_list(cfg, caplog):
    tree, blobs = tree_and_blobs()
    p = provider(cfg, FakeDrive(tree, blobs))
    first = await p.refresh(FIXED_NOW)
    tree[ROOT] = []
    tree["sub"] = []
    with caplog.at_level(logging.WARNING):
        again = await p.refresh(FIXED_NOW)
    assert again == first and len(first) == 4
    assert len(list((cfg.data_dir / "photos").glob("*.jpg"))) == 4
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_empty_listing_with_empty_cache_is_just_empty(cfg):
    assert await provider(cfg, FakeDrive({ROOT: []}, {})).refresh(FIXED_NOW) == []


async def test_progress_published_every_ten_new_photos(cfg):
    files = [meta(f"f{i}", f"{i:032x}") for i in range(23)]
    drive = FakeDrive({ROOT: files}, {f"f{i}": jpeg((40, 30)) for i in range(23)}, page=50)
    p = provider(cfg, drive)
    seen = []
    p.on_progress = lambda photos: seen.append(len(photos))
    out = await p.refresh(FIXED_NOW)
    assert seen == [10, 20] and len(out) == 23


async def test_check_counts_without_downloading(cfg):
    tree, blobs = tree_and_blobs()
    drive = FakeDrive(tree, blobs, page=2)
    assert await provider(cfg, drive).check() == 4
    assert drive.downloads == []
    assert not (cfg.data_dir / "photos").exists()


async def test_check_without_key_file_raises_safe_message(tmp_path):
    cfg = Config(shared_secret="s", drive=Drive("root", "missing.json"), data_dir=tmp_path / "d")
    with pytest.raises(RuntimeError, match="^drive key file missing$"):
        await PhotosProvider(cfg).check()
