import os
import stat
import subprocess
import tempfile
import unittest

MAC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(MAC, "install.sh")
UNINSTALL = os.path.join(MAC, "uninstall.sh")
SECRET = "s3cr3t-value-xyz"  # ggignore (fake test value)
SETTINGS = '{\n  "statusLine": {"type": "command", "command": "x"},\n  "hooks": {"SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "echo hi"}]}]}\n}\n'


def snapshot(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[p] = open(p, "rb").read()
    return out


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.rec = os.path.join(self.tmp.name, "rec.txt")
        os.makedirs(self.home)
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.home, ".claude"))
        for name in ("claude", "launchctl"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> "$REC"\nexit 0\n' % name)
            os.chmod(p, 0o755)
        self.sp = os.path.join(self.home, ".claude", "settings.json")
        with open(self.sp, "w") as f:
            f.write(SETTINGS)
        self.toml = os.path.join(self.tmp.name, "config.toml")
        with open(self.toml, "w") as f:
            f.write('port = 1\n[auth]\nshared_secret = "%s"\n' % SECRET)
        self.env = {"HOME": self.home, "REC": self.rec, "PYTHONDONTWRITEBYTECODE": "1",
                    "PATH": self.bin + ":/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOMEHUB_CONFIG_TOML": self.toml}

    def tearDown(self):
        self.tmp.cleanup()

    def run_sh(self, script, *args, stdin=""):
        return subprocess.run(["/bin/bash", script] + list(args), env=self.env, input=stdin,
                              capture_output=True, text=True, timeout=60)

    def test_syntax(self):
        for s in (INSTALL, UNINSTALL):
            self.assertEqual(subprocess.run(["bash", "-n", s]).returncode, 0)

    def test_dry_run_touches_nothing(self):
        before = snapshot(self.tmp.name)
        r = self.run_sh(INSTALL, "--dry-run", stdin="\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(self.tmp.name), before)
        self.assertFalse(os.path.exists(self.rec))
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        self.assertEqual(sorted(os.listdir(self.home)), [".claude"])

    def test_dry_run_with_url_never_reads_stdin(self):
        r = subprocess.run(["/bin/bash", INSTALL, "--dry-run", "--url", "http://h.test"],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["/bin/bash", INSTALL, "--dry-run"],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_invalid_settings_installs_nothing(self):
        with open(self.sp, "w") as f:
            f.write("{ nope")
        before = snapshot(self.tmp.name)
        r = self.run_sh(INSTALL, "--yes", "--url", "http://h.test")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(snapshot(self.tmp.name), before)
        self.assertFalse(os.path.exists(self.rec))
        self.assertIn("nothing was changed", r.stderr)

    def test_bootstrap_retry_after_first_failure(self):
        p = os.path.join(self.bin, "launchctl")
        with open(p, "w") as f:
            f.write('#!/bin/sh\necho "launchctl $*" >> "$REC"\n'
                    'if [ "$1" = bootstrap ] && [ ! -f "$REC.failed" ]; then touch "$REC.failed"; exit 5; fi\nexit 0\n')
        self.env["HOMEHUB_RETRY_SLEEP"] = "0"
        r = self.run_sh(INSTALL, "--yes", "--url", "http://h.test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.rec).read().count("launchctl bootstrap"), 3)

    def test_bootstrap_persistent_failure_explains(self):
        p = os.path.join(self.bin, "launchctl")
        with open(p, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = bootstrap ] && exit 5\nexit 0\n')
        self.env["HOMEHUB_RETRY_SLEEP"] = "0"
        r = self.run_sh(INSTALL, "--yes", "--url", "http://h.test")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("re-run install.sh", r.stderr)
        self.assertIn("LaunchAgent", r.stderr)

    def test_mcp_failure_listed_in_summary(self):
        p = os.path.join(self.bin, "claude")
        with open(p, "w") as f:
            f.write('#!/bin/sh\n[ "$2" = add ] && exit 1\nexit 0\n')
        r = self.run_sh(INSTALL, "--yes", "--url", "http://h.test")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Installed with warnings", r.stdout)
        self.assertIn("claude mcp add", r.stdout)
        self.assertNotIn(SECRET, r.stdout + r.stderr)

    def test_toml_regex_decoy_and_fallbacks(self):
        cases = [
            ('# shared_secret = "decoy"\nshared_secret = "real-one"\n', "real-one"),
            ("shared_secret = 'single'\n", "single"),
            ('shared_secret = "has\\\\back"\n', None),   # backslash -> prompt
            ('other = 1\n', None),                      # not found -> prompt
        ]
        for body, want in cases:
            with open(self.toml, "w") as f:
                f.write(body)
            r = self.run_sh(INSTALL, "--yes", "--url", "http://h.test", stdin="prompted-secret\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            env = os.path.join(self.home, ".config", "homehub", "helper.env")
            got = [l for l in open(env).read().splitlines() if l.startswith("HOMEHUB_SECRET=")][0].split("=", 1)[1]
            self.assertEqual(got, want or "prompted-secret", body)

    def test_uninstall_continues_past_failure(self):
        self.assertEqual(self.run_sh(INSTALL, "--yes", "--url", "http://h.test").returncode, 0)
        with open(self.sp, "w") as f:
            f.write("{ broken")
        r = self.run_sh(UNINSTALL, "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("settings.json", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Library", "Application Support", "homehub-mac")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "homehub", "helper.env")))
        self.assertIn("claude mcp remove homehub", open(self.rec).read())

    def test_rerun_keeps_configured_url_on_enter(self):
        r = self.run_sh(INSTALL, "--yes", "--url", "http://pi.test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_sh(INSTALL, "--yes", stdin="\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env = os.path.join(self.home, ".config", "homehub", "helper.env")
        self.assertIn("HOMEHUB_URL=http://pi.test\n", open(env).read())
        self.assertIn("Server URL [http://pi.test]", r.stdout)

    def test_install_and_uninstall(self):
        r = self.run_sh(INSTALL, "--yes", stdin="http://example.test:9\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout + r.stderr
        self.assertNotIn(SECRET, out)
        asup = os.path.join(self.home, "Library", "Application Support", "homehub-mac")
        for f in ("homehub_client.py", "claude_hook.py", "presence.py", "usage.py"):
            self.assertTrue(os.path.exists(os.path.join(asup, f)), f)
        env = os.path.join(self.home, ".config", "homehub", "helper.env")
        self.assertEqual(stat.S_IMODE(os.stat(env).st_mode), 0o600)
        txt = open(env).read()
        self.assertIn("HOMEHUB_URL=http://example.test:9", txt)
        self.assertIn("HOMEHUB_SECRET=" + SECRET, txt)
        la = os.path.join(self.home, "Library", "LaunchAgents")
        for n in ("presence", "usage"):
            p = os.path.join(la, "dev.homehub.%s.plist" % n)
            body = open(p).read()
            self.assertNotIn("@", body)
            self.assertIn(os.path.join(asup, n + ".py"), body)
        rec = open(self.rec).read()
        self.assertIn("launchctl bootstrap gui/", rec)
        self.assertIn("claude mcp remove homehub -s user", rec)
        self.assertIn("claude mcp add --scope user --transport http homehub http://example.test:9/mcp", rec)
        settings = open(self.sp).read()
        self.assertIn("homehub-mac/claude_hook.py", settings)
        self.assertIn(os.path.join(asup, "claude_hook.py"), settings)
        self.assertEqual(len([n for n in os.listdir(os.path.join(self.home, ".claude"))
                              if "bak-homehub" in n]), 1)
        # idempotent re-run
        r = self.run_sh(INSTALL, "--yes", stdin="http://example.test:9\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.sp).read().count("claude_hook.py"), settings.count("claude_hook.py"))
        # uninstall
        os.remove(self.rec)
        r = self.run_sh(UNINSTALL, "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import json
        self.assertEqual(json.load(open(self.sp)), json.loads(SETTINGS))
        self.assertFalse(os.path.exists(asup))
        self.assertFalse(os.path.exists(env))
        for n in ("presence", "usage"):
            self.assertFalse(os.path.exists(os.path.join(la, "dev.homehub.%s.plist" % n)))
        rec = open(self.rec).read()
        self.assertIn("launchctl bootout gui/", rec)
        self.assertIn("claude mcp remove homehub", rec)


if __name__ == "__main__":
    unittest.main()
