"""Shared helper client: load helper.env, POST JSON to the home server, log.

Python 3.9 stdlib only. Never logs the secret, response bodies or hook content.
"""
import json
import os
import stat
import time
import urllib.error
import urllib.request

DEFAULT_ENV = os.path.expanduser("~/.config/homehub/helper.env")
DEFAULT_LOG_DIR = os.path.expanduser("~/Library/Logs/homehub-mac")
LOG_CAP = 200 * 1024
_warned_mode = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: the bearer token must only go to the configured host."""

    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def no_redirect_open(req, timeout):
    """Open a request without following redirects (callers handle HTTPError)."""
    return _OPENER.open(req, timeout=timeout)


def _log_dir():
    return os.environ.get("HOMEHUB_LOG_DIR") or DEFAULT_LOG_DIR


def log(name, msg):
    """Append a timestamped line; truncate the oldest half past ~200 KB."""
    try:
        d = _log_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        path = os.path.join(d, name + ".log")
        line = "%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), str(msg)[:300].replace("\n", " "))
        with open(path, "a") as f:
            f.write(line)
        if os.path.getsize(path) > LOG_CAP:
            with open(path, "rb") as f:
                data = f.read()
            data = data[len(data) // 2:]
            nl = data.find(b"\n")
            if nl != -1:
                data = data[nl + 1:]
            with open(path, "wb") as f:
                f.write(data)
    except Exception:
        pass


def load_config(path=None):
    """Return {"url", "secret"} or None (missing, incomplete, or mode != 0600)."""
    if path is None:
        path = os.environ.get("HOMEHUB_ENV") or DEFAULT_ENV
    try:
        st = os.stat(path)
    except OSError:
        return None
    if stat.S_IMODE(st.st_mode) & 0o077:
        global _warned_mode
        if not _warned_mode:
            _warned_mode = True
            log("client", "config file has unsafe mode (need 0600); ignoring")
        return None
    vals = {}
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                vals[k.strip()] = v
    except Exception:
        return None
    url = vals.get("HOMEHUB_URL")
    secret = vals.get("HOMEHUB_SECRET")
    if not url or not secret:
        return None
    return {"url": url.rstrip("/"), "secret": secret}


def post_json(path, body, timeout=3.0, cfg=None):
    """POST JSON with a bearer token. True on 2xx; never raises."""
    try:
        timeout = min(float(timeout), 3.0)
        if cfg is None:
            cfg = load_config()
        if not cfg:
            return False
        req = urllib.request.Request(
            cfg["url"].rstrip("/") + path,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer " + cfg["secret"],
                "Content-Type": "application/json",
            },
        )
        with _OPENER.open(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        log("client", "POST %s -> HTTP %s" % (path, e.code))
        return False
    except Exception as e:
        log("client", "POST %s failed: %s" % (path, type(e).__name__))
        return False
