import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import homehub_client  # noqa: E402

SECRET = "s3cret-token-value"  # ggignore (fake test value)


class Handler(BaseHTTPRequestHandler):
    received = []
    status = 200

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        Handler.received.append(
            (self.path, dict(self.headers), json.loads(body.decode() or "null"))
        )
        out = json.dumps({"ok": True, "echo": self.headers.get("Authorization")}).encode()
        self.send_response(Handler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class ClientTests(unittest.TestCase):
    def setUp(self):
        homehub_client._warned_mode = False
        Handler.received = []
        Handler.status = 200
        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        os.environ["HOMEHUB_LOG_DIR"] = os.path.join(self.tmp.name, "logs")
        self.addCleanup(os.environ.pop, "HOMEHUB_LOG_DIR", None)
        self.cfg = {"url": "http://127.0.0.1:%d" % self.port, "secret": SECRET}

    def write_env(self, mode, text=None):
        p = os.path.join(self.tmp.name, "helper.env")
        with open(p, "w") as f:
            f.write(text or "HOMEHUB_URL=http://x\nHOMEHUB_SECRET=%s\n" % SECRET)
        os.chmod(p, mode)
        return p

    def logtext(self):
        d = os.environ["HOMEHUB_LOG_DIR"]
        out = ""
        if os.path.isdir(d):
            for n in os.listdir(d):
                with open(os.path.join(d, n)) as f:
                    out += f.read()
        return out

    def test_sends_bearer_and_content_type(self):
        self.assertTrue(homehub_client.post_json("/api/x", {"a": 1}, cfg=self.cfg))
        path, headers, body = Handler.received[0]
        self.assertEqual(path, "/api/x")
        self.assertEqual(headers["Authorization"], "Bearer " + SECRET)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body, {"a": 1})

    def test_401_returns_false(self):
        Handler.status = 401
        self.assertFalse(homehub_client.post_json("/api/x", {}, cfg=self.cfg))

    def test_server_down_false_within_timeout(self):
        self.srv.shutdown()
        self.srv.server_close()
        t = time.time()
        ok = homehub_client.post_json("/api/x", {}, timeout=1.0, cfg=self.cfg)
        self.assertFalse(ok)
        self.assertLess(time.time() - t, 2.0)

    def test_no_config_returns_false(self):
        os.environ["HOMEHUB_ENV"] = os.path.join(self.tmp.name, "missing.env")
        self.addCleanup(os.environ.pop, "HOMEHUB_ENV", None)
        self.assertFalse(homehub_client.post_json("/api/x", {}))

    def test_load_config_modes(self):
        p = self.write_env(0o644)
        self.assertIsNone(homehub_client.load_config(p))
        self.assertIn("mode", self.logtext())
        os.chmod(p, 0o600)
        self.assertEqual(
            homehub_client.load_config(p), {"url": "http://x", "secret": SECRET}
        )

    def test_load_config_missing_or_incomplete(self):
        self.assertIsNone(
            homehub_client.load_config(os.path.join(self.tmp.name, "nope"))
        )
        p = self.write_env(0o600, "# c\nHOMEHUB_URL=http://x\n")
        self.assertIsNone(homehub_client.load_config(p))

    def test_load_config_env_override(self):
        p = self.write_env(0o600)
        os.environ["HOMEHUB_ENV"] = p
        self.addCleanup(os.environ.pop, "HOMEHUB_ENV", None)
        self.assertEqual(homehub_client.load_config()["secret"], SECRET)

    def test_log_never_contains_secret(self):
        homehub_client.post_json("/api/x", {}, cfg=self.cfg)
        Handler.status = 401
        homehub_client.post_json("/api/x", {}, cfg=self.cfg)
        self.assertNotIn(SECRET, self.logtext())
        self.assertNotIn("Bearer", self.logtext())

    def test_redirect_not_followed_and_token_not_leaked(self):
        other = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        target = "http://127.0.0.1:%d/steal" % other.server_address[1]

        class Redir(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        redir = HTTPServer(("127.0.0.1", 0), Redir)
        threading.Thread(target=redir.serve_forever, daemon=True).start()
        self.addCleanup(redir.server_close)
        self.addCleanup(redir.shutdown)
        cfg = {"url": "http://127.0.0.1:%d" % redir.server_address[1], "secret": SECRET}
        self.assertFalse(homehub_client.post_json("/api/x", {}, cfg=cfg))
        time.sleep(0.2)
        self.assertEqual(Handler.received, [])

    def test_log_capped(self):
        for _ in range(3000):
            homehub_client.log("cap", "x" * 100)
        p = os.path.join(os.environ["HOMEHUB_LOG_DIR"], "cap.log")
        self.assertLess(os.path.getsize(p), 215 * 1024)
        self.assertGreater(os.path.getsize(p), 50 * 1024)


if __name__ == "__main__":
    unittest.main()
