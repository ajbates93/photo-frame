import os
import plistlib
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import presence  # noqa: E402

IOREG_OUT = """+-o IOHIDSystem  <class IOHIDSystem, id 0x100000abc, registered, matched, active, busy 0 (1 ms), retain 8>
    {
      "HIDIdleTime" = 30000000000
      "HIDParameters" = {"HIDClickTime"=500000000}
    }
"""
PLIST = os.path.join(HERE, "..", "launchagents", "dev.homehub.presence.plist.in")


def completed(out, rc=0):
    return subprocess.CompletedProcess(["ioreg"], rc, stdout=out, stderr="")


class IdleTests(unittest.TestCase):
    def test_parses_nanoseconds(self):
        with mock.patch("subprocess.run", return_value=completed(IOREG_OUT)) as r:
            self.assertEqual(presence.idle_seconds(), 30.0)
        self.assertEqual(r.call_args[0][0][0], "/usr/sbin/ioreg")
        self.assertEqual(r.call_args[1]["timeout"], 2)

    def test_garbage_is_none(self):
        with mock.patch("subprocess.run", return_value=completed("nothing here")):
            self.assertIsNone(presence.idle_seconds())

    def test_nonzero_exit_is_none(self):
        with mock.patch("subprocess.run", return_value=completed(IOREG_OUT, 1)):
            self.assertIsNone(presence.idle_seconds())

    def test_timeout_is_none(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ioreg", 2)):
            self.assertIsNone(presence.idle_seconds())

    def test_missing_binary_is_none(self):
        with mock.patch("subprocess.run", side_effect=OSError("nope")):
            self.assertIsNone(presence.idle_seconds())


class MainTests(unittest.TestCase):
    def test_active_posts_with_offset_time(self):
        with mock.patch.object(presence, "idle_seconds", return_value=30.0), \
                mock.patch("homehub_client.post_json", return_value=True) as p:
            before = datetime.now().astimezone()
            self.assertEqual(presence.main(), 0)
        path, body = p.call_args[0][0], p.call_args[0][1]
        self.assertEqual(path, "/api/presence")
        self.assertIs(body["active"], True)
        at = datetime.fromisoformat(body["at"])
        self.assertIsNotNone(at.utcoffset())
        expected = before - timedelta(seconds=30)
        self.assertLess(abs((at - expected).total_seconds()), 5)

    def test_idle_does_not_post(self):
        for idle in (120.0, 500.0, None):
            with mock.patch.object(presence, "idle_seconds", return_value=idle), \
                    mock.patch("homehub_client.post_json") as p:
                self.assertEqual(presence.main(), 0)
            p.assert_not_called()

    def test_post_exception_still_zero(self):
        with mock.patch.object(presence, "idle_seconds", return_value=1.0), \
                mock.patch("homehub_client.post_json", side_effect=RuntimeError("x")):
            self.assertEqual(presence.main(), 0)


class PlistTests(unittest.TestCase):
    def test_template_renders_valid(self):
        with open(PLIST) as f:
            text = f.read()
        for k, v in (("@PYTHON@", "/usr/bin/python3"), ("@SCRIPT@", "/x/presence.py"),
                     ("@LOGDIR@", "/x/logs")):
            text = text.replace(k, v)
        self.assertNotIn("@", text)
        d = plistlib.loads(text.encode())
        self.assertEqual(d["Label"], "dev.homehub.presence")
        self.assertEqual(d["StartInterval"], 60)
        self.assertIs(d["RunAtLoad"], True)
        self.assertEqual(d["ProcessType"], "Background")
        self.assertNotIn("KeepAlive", d)
        self.assertEqual(d["ProgramArguments"], ["/usr/bin/python3", "/x/presence.py"])
        self.assertTrue(d["StandardOutPath"].startswith("/x/logs/"))
        self.assertTrue(d["StandardErrorPath"].startswith("/x/logs/"))


if __name__ == "__main__":
    unittest.main()
