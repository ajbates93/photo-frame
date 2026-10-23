#!/usr/bin/python3
"""Claude plan usage helper.

Reads the Claude Code OAuth token from the macOS Keychain, asks Anthropic's
(unofficial) usage endpoint for plan utilisation, and POSTs only percentages,
reset times and the plan name to the home server. The token stays in memory
and is never logged or printed. Always exits 0.
"""
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import homehub_client  # noqa: E402

DEFAULT_SECURITY = "/usr/bin/security"
DEFAULT_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
LOG = "usage"
MAX_RESPONSE = 256 * 1024
# After a refused Keychain read (Deny, or "Allow" without "Always"), wait this long before
# asking again, so macOS does not show a prompt every 5 minutes.
KEYCHAIN_BACKOFF_S = 3 * 3600


def _log(msg):
    homehub_client.log(LOG, msg)


def read_credentials():
    """Return {"token", "plan"} from the Keychain item, or None. Never logs values."""
    try:
        binary = os.environ.get("HOMEHUB_SECURITY_BIN") or DEFAULT_SECURITY
        r = subprocess.run(
            [binary, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=5,
        )
        if r.returncode != 0:
            _log("keychain read failed (exit %s); pausing %d h" % (r.returncode, KEYCHAIN_BACKOFF_S // 3600))
            _start_backoff()
            return None
        raw = r.stdout.strip()
        if raw and re.fullmatch(r"[0-9a-fA-F]+", raw) and len(raw) % 2 == 0:
            raw = bytes.fromhex(raw).decode("utf-8")
        data = json.loads(raw)
        oauth = data["claudeAiOauth"]
        token = oauth["accessToken"]
        plan = oauth["subscriptionType"]
        if not isinstance(token, str) or not token or not isinstance(plan, str) or not plan:
            _log("keychain item has unexpected shape")
            return None
        return {"token": token, "plan": plan[:50]}
    except Exception as e:
        _log("keychain read failed: %s" % type(e).__name__)
        return None


def _backoff_path():
    return os.path.join(homehub_client._log_dir(), "usage.keychain-backoff")


def _start_backoff(now=None):
    try:
        os.makedirs(homehub_client._log_dir(), exist_ok=True)
        with open(_backoff_path(), "w") as f:
            f.write(str(int((time.time() if now is None else now) + KEYCHAIN_BACKOFF_S)))
    except OSError as e:
        _log("could not record keychain backoff: %s" % type(e).__name__)


def backing_off(now=None):
    """True while a refused Keychain read is still within its backoff window."""
    try:
        with open(_backoff_path()) as f:
            until = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return (time.time() if now is None else now) < until


def fetch_usage(token):
    """GET the usage JSON (dict) or None on any error / 401."""
    try:
        url = os.environ.get("HOMEHUB_USAGE_URL") or DEFAULT_URL
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        })
        with homehub_client.no_redirect_open(req, 5) as resp:
            raw = resp.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            _log("usage response too large")
            return None
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            _log("usage response not an object")
            return None
        return data
    except urllib.error.HTTPError as e:
        _log("usage fetch -> HTTP %s" % e.code)
        return None
    except Exception as e:
        _log("usage fetch failed: %s" % type(e).__name__)
        return None


def _parse_iso(s):
    """Parse ISO-8601 with an offset (3.9-safe). Returns aware datetime or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    # fromisoformat on 3.9 wants 3 or 6 fractional digits.
    t = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], t, count=1)
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo is not None and d.utcoffset() is not None else None


def _window(obj):
    if not isinstance(obj, dict):
        return None
    pct = obj.get("utilization")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    if math.isnan(pct) or not 0 <= pct <= 100:
        return None
    resets = obj.get("resets_at")
    if _parse_iso(resets) is None:
        return None
    return {"pct": pct, "resetsAt": _parse_iso(resets).isoformat()}


def to_payload(creds_plan, usage_json):
    """Map the usage response to the server payload, or None on any deviation."""
    if not isinstance(creds_plan, str) or not creds_plan.strip():
        return None
    if not isinstance(usage_json, dict):
        return None
    session = _window(usage_json.get("five_hour"))
    weekly = _window(usage_json.get("seven_day"))
    if session is None or weekly is None:
        return None
    return {"plan": creds_plan.strip()[:50].title(), "session": session, "weekly": weekly}


def _key_tree(obj, prefix=""):
    lines = []
    if isinstance(obj, dict):
        for k in sorted(obj):
            lines.append(prefix + str(k))
            lines.extend(_key_tree(obj[k], prefix + str(k) + "."))
    return lines


def _print_keys():
    creds = read_credentials()
    if not creds:
        print("no credentials")
        return
    data = fetch_usage(creds["token"])
    if data is None:
        print("no usage response")
        return
    print("keys:")
    for line in _key_tree(data):
        print("  " + line)
    for name in ("five_hour", "seven_day"):
        w = data.get(name)
        pct = w.get("utilization") if isinstance(w, dict) else None
        if isinstance(pct, (int, float)) and not isinstance(pct, bool):
            print("%s.utilization = %s" % (name, pct))
        else:
            print("%s.utilization = (missing or not a number)" % name)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if "--print-keys" in argv:
            _print_keys()
            return 0
        if backing_off():
            return 0
        creds = read_credentials()
        if not creds:
            return 0
        data = fetch_usage(creds["token"])
        if data is None:
            return 0
        payload = to_payload(creds["plan"], data)
        if payload is None:
            _log("usage response shape unexpected; not posting")
            return 0
        homehub_client.post_json("/api/claude/usage", payload, timeout=3.0)
    except Exception as e:
        _log("unexpected error: %s" % type(e).__name__)
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
