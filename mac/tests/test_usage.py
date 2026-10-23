import io
import json
import os
import plistlib
import stat
import sys
import tempfile
import time
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import usage  # noqa: E402

TOKEN = "sk-ant-oat01-FAKE-TOKEN-VALUE"  # ggignore (fake test value)
SECRET = "helper-secret-value"  # ggignore (fake test value)
USAGE = {
    "five_hour": {"utilization": 42.5, "resets_at": "2026-10-22T18:00:00.123456+00:00"},
    "seven_day": {"utilization": 17, "resets_at": "2026-10-27T09:00:00Z"},
    "seven_day_opus": None,
}
CREDS = {"claudeAiOauth": {"accessToken": TOKEN, "subscriptionType": "max", "scopes": ["x"]}}


class Other(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Other.seen.append(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class Handler(BaseHTTPRequestHandler):
    redirect_to = None
    posts = []
    usage_status = 200
    usage_body = USAGE
    usage_headers = None

    def _send(self, status, obj):
        out = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        Handler.usage_headers = {k.lower(): v for k, v in self.headers.items()}
        if Handler.redirect_to:
            self.send_response(302)
            self.send_header("Location", Handler.redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(Handler.usage_status, Handler.usage_body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        Handler.posts.append((self.path, json.loads(self.rfile.read(n).decode())))
        self._send(200, {"ok": True})

    def log_message(self, *a):
        pass


class UsageBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Handler.posts = []
        Handler.usage_status = 200
        Handler.usage_body = USAGE
        Handler.usage_headers = None
        self.logdir = os.path.join(self.tmp.name, "logs")
        env = os.path.join(self.tmp.name, "helper.env")
        with open(env, "w") as f:
            f.write("HOMEHUB_URL=http://127.0.0.1:%d\nHOMEHUB_SECRET=%s\n" % (self.port, SECRET))
        os.chmod(env, 0o600)
        patcher = mock.patch.dict(os.environ, {
            "HOMEHUB_ENV": env,
            "HOMEHUB_LOG_DIR": self.logdir,
            "HOMEHUB_USAGE_URL": "http://127.0.0.1:%d/api/oauth/usage" % self.port,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_security(self, output, rc=0):
        p = os.path.join(self.tmp.name, "fake-security")
        with open(p, "w") as f:
            f.write("#!/bin/sh\ncat <<'EOF_FAKE'\n%s\nEOF_FAKE\nexit %d\n" % (output, rc))
        os.chmod(p, 0o755)
        os.environ["HOMEHUB_SECURITY_BIN"] = p
        self.addCleanup(os.environ.pop, "HOMEHUB_SECURITY_BIN", None)

    def logtext(self):
        out = ""
        if os.path.isdir(self.logdir):
            for n in os.listdir(self.logdir):
                with open(os.path.join(self.logdir, n)) as f:
                    out += f.read()
        return out


class ToPayloadTests(unittest.TestCase):
    def test_generic(self):
        p = usage.to_payload("max", USAGE)
        self.assertEqual(p["plan"], "Max")
        self.assertEqual(p["session"]["pct"], 42.5)
        self.assertEqual(p["session"]["resetsAt"], "2026-10-22T18:00:00.123456+00:00")
        self.assertEqual(p["weekly"]["pct"], 17)
        self.assertEqual(p["weekly"]["resetsAt"], "2026-10-27T09:00:00+00:00")  # Z normalised
        self.assertEqual(set(p), {"plan", "session", "weekly"})

    def test_deviations_give_none(self):
        def mod(**kw):
            d = json.loads(json.dumps(USAGE))
            for path, v in kw.items():
                a, b = path.split("__")
                if v is KeyError:
                    del d[a][b]
                else:
                    d[a][b] = v
            return d
        bad = [
            mod(five_hour__utilization=101),
            mod(seven_day__utilization=-1),
            mod(five_hour__utilization="40"),
            mod(five_hour__utilization=True),
            mod(five_hour__utilization=float("nan")),
            mod(five_hour__utilization=KeyError),
            mod(seven_day__resets_at=KeyError),
            mod(five_hour__resets_at="tomorrow"),
            mod(five_hour__resets_at="2026-10-22T18:00:00"),  # no offset
            mod(seven_day__resets_at=12345),
            {"five_hour": USAGE["five_hour"]},
            {},
            [],
            None,
        ]
        for b in bad:
            self.assertIsNone(usage.to_payload("max", b), b)

    def test_bad_plan(self):
        for plan in (None, "", 5):
            self.assertIsNone(usage.to_payload(plan, USAGE))


class ReadCredentialsTests(UsageBase):
    def test_ok(self):
        self.fake_security(json.dumps(CREDS))
        self.assertEqual(usage.read_credentials(), {"token": TOKEN, "plan": "max"})

    def test_hex_encoded_output(self):
        self.fake_security(json.dumps(CREDS).encode().hex())
        self.assertEqual(usage.read_credentials(), {"token": TOKEN, "plan": "max"})

    def test_bad_hex_logs_type_only(self):
        self.fake_security("ffff")
        self.assertIsNone(usage.read_credentials())
        self.assertIn("keychain read failed: ", self.logtext())

    def test_plan_capped(self):
        c = {"claudeAiOauth": {"accessToken": TOKEN, "subscriptionType": "x" * 80}}
        self.fake_security(json.dumps(c))
        self.assertEqual(len(usage.read_credentials()["plan"]), 50)

    def test_malformed(self):
        for out in ("not json", "[]", json.dumps({"claudeAiOauth": {}}),
                    json.dumps({"claudeAiOauth": {"accessToken": TOKEN}}),
                    json.dumps({"other": 1})):
            self.fake_security(out)
            self.assertIsNone(usage.read_credentials(), out)

    def test_failure_exit(self):
        self.fake_security("", rc=44)
        self.assertIsNone(usage.read_credentials())

    def test_refused_read_backs_off_then_retries(self):
        calls = os.path.join(self.tmp.name, "calls")
        self.fake_security("", rc=51)
        usage.main([])
        self.assertTrue(usage.backing_off())
        # While backing off, main() must not run `security` at all.
        p = os.path.join(self.tmp.name, "counting-security")
        with open(p, "w") as f:
            f.write("#!/bin/sh\necho x >> %s\nexit 51\n" % calls)
        os.chmod(p, 0o755)
        os.environ["HOMEHUB_SECURITY_BIN"] = p
        usage.main([])
        self.assertFalse(os.path.exists(calls))
        # Once the window has passed it asks again.
        self.assertFalse(usage.backing_off(now=time.time() + usage.KEYCHAIN_BACKOFF_S + 1))
        with open(usage._backoff_path(), "w") as f:
            f.write("0")
        usage.main([])
        self.assertTrue(os.path.exists(calls))

    def test_missing_binary(self):
        os.environ["HOMEHUB_SECURITY_BIN"] = "/nonexistent/security"
        self.addCleanup(os.environ.pop, "HOMEHUB_SECURITY_BIN", None)
        self.assertIsNone(usage.read_credentials())


class FetchTests(UsageBase):
    def test_ok_and_headers(self):
        self.assertEqual(usage.fetch_usage(TOKEN), USAGE)
        self.assertEqual(Handler.usage_headers["authorization"], "Bearer " + TOKEN)
        self.assertEqual(Handler.usage_headers["anthropic-beta"], "oauth-2025-04-20")

    def test_401_and_500(self):
        for s in (401, 500):
            Handler.usage_status = s
            self.assertIsNone(usage.fetch_usage(TOKEN))

    def test_non_dict_json(self):
        Handler.usage_body = [1]
        self.assertIsNone(usage.fetch_usage(TOKEN))

    def test_oversize_response(self):
        Handler.usage_body = {"pad": "x" * (300 * 1024)}
        self.assertIsNone(usage.fetch_usage(TOKEN))

    def test_redirect_not_followed(self):
        other = HTTPServer(("127.0.0.1", 0), Other)
        Other.seen = []
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        Handler.redirect_to = "http://127.0.0.1:%d/steal" % other.server_address[1]
        self.addCleanup(setattr, Handler, "redirect_to", None)
        self.assertIsNone(usage.fetch_usage(TOKEN))
        self.assertEqual(Other.seen, [])

    def test_connection_refused(self):
        os.environ["HOMEHUB_USAGE_URL"] = "http://127.0.0.1:1/x"
        self.assertIsNone(usage.fetch_usage(TOKEN))


class MainTests(UsageBase):
    def test_posts_payload_and_never_logs_token(self):
        self.fake_security(json.dumps(CREDS))
        self.assertEqual(usage.main([]), 0)
        self.assertEqual(len(Handler.posts), 1)
        path, body = Handler.posts[0]
        self.assertEqual(path, "/api/claude/usage")
        self.assertEqual(body["plan"], "Max")
        self.assertNotIn(TOKEN, json.dumps(body))
        self.assertNotIn(TOKEN, self.logtext())
        self.assertNotIn(SECRET, self.logtext())

    def test_401_no_post_one_log_line(self):
        self.fake_security(json.dumps(CREDS))
        Handler.usage_status = 401
        self.assertEqual(usage.main([]), 0)
        self.assertEqual(Handler.posts, [])
        self.assertNotIn(TOKEN, self.logtext())
        self.assertGreaterEqual(len(self.logtext().strip().splitlines()), 1)

    def test_bad_shape_no_post(self):
        self.fake_security(json.dumps(CREDS))
        Handler.usage_body = {"five_hour": {"utilization": 500, "resets_at": "x"}}
        self.assertEqual(usage.main([]), 0)
        self.assertEqual(Handler.posts, [])

    def test_no_credentials_no_post(self):
        self.fake_security("garbage")
        self.assertEqual(usage.main([]), 0)
        self.assertEqual(Handler.posts, [])
        self.assertIsNone(Handler.usage_headers)

    def test_print_keys_no_post_no_token(self):
        self.fake_security(json.dumps(CREDS))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(usage.main(["--print-keys"]), 0)
        out = buf.getvalue()
        self.assertEqual(Handler.posts, [])
        for k in ("five_hour", "seven_day", "utilization", "resets_at"):
            self.assertIn(k, out)
        self.assertIn("42.5", out)
        self.assertIn("17", out)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("2026-10", out)  # key names and percentages only
        self.assertNotIn(TOKEN, self.logtext())


class PlistTests(unittest.TestCase):
    def test_template_renders_valid(self):
        with open(os.path.join(HERE, "..", "launchagents", "dev.homehub.usage.plist.in")) as f:
            text = f.read()
        for k, v in (("@PYTHON@", "/usr/bin/python3"), ("@SCRIPT@", "/x/usage.py"),
                     ("@LOGDIR@", "/x/logs")):
            text = text.replace(k, v)
        self.assertNotIn("@", text)
        d = plistlib.loads(text.encode())
        self.assertEqual(d["Label"], "dev.homehub.usage")
        self.assertEqual(d["StartInterval"], 300)
        self.assertIs(d["RunAtLoad"], True)
        self.assertEqual(d["ProcessType"], "Background")
        self.assertNotIn("KeepAlive", d)
        self.assertEqual(d["ProgramArguments"], ["/usr/bin/python3", "/x/usage.py"])


if __name__ == "__main__":
    unittest.main()
