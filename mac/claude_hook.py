#!/usr/bin/python3
"""Claude Code hook forwarder.

Reads a hook payload on stdin, keeps a reduced subset, and POSTs it to the
home server from a detached grandchild process. Prints nothing and always
exits 0 so Claude Code is never slowed or broken.
"""
import json
import os
import sys

MAX_STDIN = 2 * 1024 * 1024
MAX_MESSAGE = 200
KEEP = ("hook_event_name", "session_id", "cwd", "notification_type", "tool_name")


def reduce(payload):
    if not isinstance(payload, dict):
        return None
    if not payload.get("session_id") or not payload.get("hook_event_name"):
        return None
    out = {}
    for k in KEEP:
        v = payload.get(k)
        if isinstance(v, str):
            out[k] = v
    if "session_id" not in out or "hook_event_name" not in out:
        return None
    msg = payload.get("message")
    if out["hook_event_name"] == "Notification" and isinstance(msg, str):
        out["message"] = msg[:MAX_MESSAGE]
    return out


def _read_stdin(stdin):
    buf = getattr(stdin, "buffer", stdin)
    data = buf.read(MAX_STDIN + 1)
    if len(data) > MAX_STDIN:
        # Drain the rest so the writer never sees a broken pipe, then drop.
        while buf.read(65536):
            pass
        return None
    return data


def _post(body):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import homehub_client
    homehub_client.post_json("/api/claude/hook", body, timeout=2.0)


def main(stdin):
    try:
        data = _read_stdin(stdin)
        if not data:
            return 0
        body = reduce(json.loads(data.decode("utf-8")))
        if body is None:
            return 0
    except Exception:
        return 0

    if os.environ.get("HOMEHUB_HOOK_SYNC") == "1":
        try:
            _post(body)
        except Exception:
            pass
        return 0

    try:
        pid = os.fork()
    except Exception:
        return 0
    if pid != 0:
        try:
            os.waitpid(pid, 0)  # first child exits immediately
        except Exception:
            pass
        return 0
    # First child: new session, fork again, exit.
    try:
        os.setsid()
        if os.fork() != 0:
            os._exit(0)
        # Grandchild: detach stdio, post, exit.
        os.chdir("/")
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        os.closerange(3, 256)
        try:
            _post(body)
        except Exception as e:
            try:
                import homehub_client
                homehub_client.log("hook", "post raised %s" % type(e).__name__)
            except Exception:
                pass
    finally:
        os._exit(0)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        main(sys.stdin)
    except Exception:
        pass
    sys.exit(0)
