import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "claude_hook.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import claude_hook  # noqa: E402

SECRET = "hook-secret-xyz"  # ggignore (fake test value)


class Handler(BaseHTTPRequestHandler):
    received = []
    status = 200
    delay = 0

    def do_POST(self):
        if Handler.delay:
            time.sleep(Handler.delay)
        n = int(self.headers.get("Content-Length", 0))
        Handler.received.append(
            (self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n)))
        )
        self.send_response(Handler.status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class ReduceTests(unittest.TestCase):
    def test_drops_sensitive_fields(self):
        r = claude_hook.reduce({
            "hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/x",
            "tool_name": "Bash", "tool_input": {"command": "rm"},
            "transcript_path": "/t", "prompt": "secret", "message": "hi",
        })
        self.assertEqual(r, {"hook_event_name": "PreToolUse", "session_id": "s",
                             "cwd": "/x", "tool_name": "Bash"})

    def test_message_only_for_notification_truncated(self):
        r = claude_hook.reduce({"hook_event_name": "Notification", "session_id": "s",
                                "notification_type": "permission_prompt",
                                "message": "m" * 500})
        self.assertEqual(len(r["message"]), 200)
        self.assertEqual(r["notification_type"], "permission_prompt")

    def test_missing_required(self):
        self.assertIsNone(claude_hook.reduce({"hook_event_name": "Stop"}))
        self.assertIsNone(claude_hook.reduce({"session_id": "s"}))
        self.assertIsNone(claude_hook.reduce([1]))


class SubprocessTests(unittest.TestCase):
    def setUp(self):
        Handler.received = []
        Handler.status = 200
        Handler.delay = 0
        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.envfile = os.path.join(self.tmp.name, "helper.env")
        with open(self.envfile, "w") as f:
            f.write("HOMEHUB_URL=http://127.0.0.1:%d\nHOMEHUB_SECRET=%s\n"
                    % (self.srv.server_address[1], SECRET))
        os.chmod(self.envfile, 0o600)

    def run_hook(self, data, envfile=None, extra=None):
        env = dict(os.environ)
        env["HOMEHUB_ENV"] = envfile or self.envfile
        env["HOMEHUB_LOG_DIR"] = os.path.join(self.tmp.name, "logs")
        env.update(extra or {})
        t = time.time()
        p = subprocess.run(["/usr/bin/python3", HOOK], input=data, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return p, time.time() - t

    def wait_received(self, n=1):
        for _ in range(100):
            if len(Handler.received) >= n:
                return True
            time.sleep(0.05)
        return False

    def test_valid_posts_reduced_body_detached(self):
        payload = {"hook_event_name": "PreToolUse", "session_id": "abc", "cwd": "/w",
                   "tool_name": "Edit", "tool_input": {"x": 1}, "transcript_path": "/t"}
        p, dt = self.run_hook(json.dumps(payload).encode())
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, b"")
        self.assertEqual(p.stderr, b"")
        self.assertLess(dt, 0.2)
        self.assertTrue(self.wait_received())
        path, auth, body = Handler.received[0]
        self.assertEqual(path, "/api/claude/hook")
        self.assertEqual(auth, "Bearer " + SECRET)
        self.assertEqual(body, {"hook_event_name": "PreToolUse", "session_id": "abc",
                                "cwd": "/w", "tool_name": "Edit"})

    def test_sync_mode_posts(self):
        p, _ = self.run_hook(json.dumps({"hook_event_name": "Stop", "session_id": "a"}).encode(),
                             extra={"HOMEHUB_HOOK_SYNC": "1"})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(Handler.received), 1)

    def test_bad_inputs_exit_zero_fast_silent(self):
        for data in (b"{not json", b"", b"[]", b"null",
                     b'{"hook_event_name":"Stop"}', b"x" * (5 * 1024 * 1024),
                     b"\xff\xfe"):
            p, dt = self.run_hook(data)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(p.stdout, b"")
            self.assertEqual(p.stderr, b"")
            self.assertLess(dt, 0.2)
        time.sleep(0.3)
        self.assertEqual(Handler.received, [])

    def test_big_valid_json_over_cap_exits_zero(self):
        big = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s",
                          "tool_input": "y" * (5 * 1024 * 1024)}).encode()
        p, dt = self.run_hook(big)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, b"")
        self.assertLess(dt, 0.5)

    def test_missing_env_exits_zero(self):
        p, dt = self.run_hook(
            json.dumps({"hook_event_name": "Stop", "session_id": "a"}).encode(),
            envfile=os.path.join(self.tmp.name, "nope.env"))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, b"")
        self.assertLess(dt, 0.2)

    def test_slow_server_does_not_delay_hook(self):
        Handler.delay = 1.5
        p, dt = self.run_hook(json.dumps({"hook_event_name": "Stop", "session_id": "a"}).encode())
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"", b""))
        self.assertLess(dt, 0.2)
        self.assertEqual(Handler.received, [])
        for _ in range(60):
            if Handler.received:
                break
            time.sleep(0.05)
        self.assertEqual(len(Handler.received), 1)

    def test_server_401_and_down_exit_zero(self):
        Handler.status = 401
        p, dt = self.run_hook(json.dumps({"hook_event_name": "Stop", "session_id": "a"}).encode())
        self.assertEqual((p.returncode, p.stdout), (0, b""))
        self.assertLess(dt, 0.2)
        self.assertTrue(self.wait_received())
        self.srv.shutdown()
        p, dt = self.run_hook(json.dumps({"hook_event_name": "Stop", "session_id": "a"}).encode())
        self.assertEqual((p.returncode, p.stdout), (0, b""))
        self.assertLess(dt, 0.2)


if __name__ == "__main__":
    unittest.main()
