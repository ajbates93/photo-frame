import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

MAC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MAC)
import settings_merge as sm  # noqa: E402

CMD = '/usr/bin/python3 "/Users/x/Library/Application Support/homehub-mac/claude_hook.py"'
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
          "Notification", "Stop", "SessionEnd"]


def alex_shape():
    return {
        "model": "opus",
        "hooks": {
            "PostToolUseFailure": [{"matcher": "Read|Write|Edit|Bash",
                                    "hooks": [{"type": "command", "command": "/bin/echo fail"}]}],
            "SessionStart": [{"matcher": "*",
                              "hooks": [{"type": "command", "command": "/bin/echo start", "timeout": 10}]}],
        },
        "statusLine": {"type": "command", "command": "/bin/echo status"},
        "enabledPlugins": {"a@b": True},
        "zzz": [1, {"k": None}],
    }


class MergeTests(unittest.TestCase):
    def test_preserves_existing_and_adds_seven(self):
        orig = alex_shape()
        out = sm.merge(copy.deepcopy(orig), CMD)
        for k in ("PostToolUseFailure",):
            self.assertEqual(out["hooks"][k], orig["hooks"][k])
        self.assertEqual(out["hooks"]["SessionStart"][0], orig["hooks"]["SessionStart"][0])
        self.assertEqual(len(out["hooks"]["SessionStart"]), 2)
        for e in EVENTS:
            entries = [x for x in out["hooks"][e] if "homehub-mac/claude_hook.py" in json.dumps(x)]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0], {"matcher": "*", "hooks": [
                {"type": "command", "command": CMD, "timeout": 5}]})
        self.assertEqual(out["statusLine"], orig["statusLine"])
        self.assertEqual(list(out.keys()), list(orig.keys()))
        self.assertNotIn("PostToolUseFailure", EVENTS)

    def test_idempotent(self):
        once = sm.merge(alex_shape(), CMD)
        twice = sm.merge(copy.deepcopy(once), CMD)
        self.assertEqual(json.dumps(once), json.dumps(twice))

    def test_unmerge_restores_exactly_with_order(self):
        orig = alex_shape()
        back = sm.unmerge(sm.merge(copy.deepcopy(orig), CMD))
        self.assertEqual(json.dumps(back), json.dumps(orig))

    def test_unmerge_without_hooks_key_original(self):
        orig = {"a": 1, "statusLine": {"x": 1}}
        back = sm.unmerge(sm.merge(copy.deepcopy(orig), CMD))
        self.assertEqual(json.dumps(back), json.dumps(orig))

    def test_unmerge_keeps_foreign_entry_in_same_event(self):
        s = sm.merge(alex_shape(), CMD)
        self.assertEqual(len(sm.unmerge(s)["hooks"]["SessionStart"]), 1)

    def test_unmerge_noop_when_absent(self):
        orig = alex_shape()
        self.assertEqual(json.dumps(sm.unmerge(copy.deepcopy(orig))), json.dumps(orig))

    def test_input_not_mutated(self):
        orig = alex_shape()
        snap = json.dumps(orig)
        sm.merge(orig, CMD)
        self.assertEqual(json.dumps(orig), snap)

    def test_unknown_keys_preserved(self):
        out = sm.merge({"weird": {"deep": [1, 2]}, "hooks": {"Custom": []}}, CMD)
        self.assertEqual(out["weird"], {"deep": [1, 2]})
        self.assertEqual(out["hooks"]["Custom"], [])


class EdgeTests(unittest.TestCase):
    def test_preexisting_empty_values_survive_via_state(self):
        orig = {"a": 1, "hooks": {"Stop": []}}
        info = {}
        merged = sm.merge(copy.deepcopy(orig), CMD, info)
        back = sm.unmerge(merged, info)
        self.assertEqual(json.dumps(back), json.dumps(orig))
        orig2 = {"a": 1, "hooks": {}}
        info = {}
        back = sm.unmerge(sm.merge(copy.deepcopy(orig2), CMD, info), info)
        self.assertEqual(json.dumps(back), json.dumps(orig2))

    def test_bad_shapes_raise(self):
        with self.assertRaises(sm.ShapeError):
            sm.merge({"hooks": []}, CMD)
        with self.assertRaises(sm.ShapeError):
            sm.merge({"hooks": {"Stop": {}}}, CMD)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(MAC, "settings_merge.py"),
                               "--settings", self.path, "--hook-cmd", CMD] + list(args),
                              capture_output=True, text=True)

    def write(self, text, mode=0o640):
        with open(self.path, "w") as f:
            f.write(text)
        os.chmod(self.path, mode)

    def backups(self):
        return [n for n in os.listdir(self.tmp.name) if n.startswith("settings.json.bak-homehub-")]

    def test_dry_run_prints_diff_changes_nothing(self):
        text = json.dumps(alex_shape(), indent=2) + "\n"
        self.write(text)
        r = self.run_cli("--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("+++", r.stdout)
        self.assertIn("homehub-mac/claude_hook.py", r.stdout)
        self.assertEqual(open(self.path).read(), text)
        self.assertEqual(self.backups(), [])
        self.assertEqual(os.listdir(self.tmp.name), ["settings.json"])

    def test_apply_backup_mode_and_roundtrip(self):
        text = json.dumps(alex_shape(), indent=2) + "\n"
        self.write(text, 0o640)
        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.backups()
        self.assertEqual(len(b), 1)
        self.assertEqual(open(os.path.join(self.tmp.name, b[0])).read(), text)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)
        merged = json.load(open(self.path))
        self.assertEqual(len(merged["hooks"]["Stop"]), 1)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), sorted(["settings.json", b[0], "settings.json.homehub-state"]))  # no temp leftovers
        r = self.run_cli("--apply")  # idempotent: no change, no new backup
        self.assertEqual(len(self.backups()), 1)
        r = self.run_cli("--apply", "--unmerge")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.load(open(self.path)), alex_shape())

    def test_invalid_json_aborts_untouched(self):
        self.write("{ not json", 0o600)
        for flag in ("--dry-run", "--apply"):
            r = self.run_cli(flag)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(open(self.path).read(), "{ not json")
        self.assertEqual(self.backups(), [])

    def test_missing_file_created_with_only_hooks(self):
        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.load(open(self.path))
        self.assertEqual(list(d.keys()), ["hooks"])
        self.assertEqual(sorted(d["hooks"]), sorted(EVENTS))
        self.assertEqual(self.backups(), [])

    def test_empty_preexisting_survive_install_uninstall(self):
        orig = {"x": 1, "hooks": {"Stop": []}}
        self.write(json.dumps(orig, indent=2) + "\n")
        self.assertEqual(self.run_cli("--apply").returncode, 0)
        self.assertEqual(self.run_cli("--apply", "--unmerge").returncode, 0)
        self.assertEqual(json.dumps(json.load(open(self.path))), json.dumps(orig))
        self.assertFalse(os.path.exists(self.path + ".homehub-state"))

    def test_unmerge_without_ours_does_not_rewrite(self):
        text = '{"a":1,   "hooks": {}}'
        self.write(text)
        r = self.run_cli("--apply", "--unmerge")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(open(self.path).read(), text)
        self.assertEqual(self.backups(), [])

    def test_bad_shape_exit_2_untouched(self):
        for text in ('{"hooks": []}', '{"hooks": {"Stop": "x"}}'):
            self.write(text)
            r = self.run_cli("--apply")
            self.assertEqual(r.returncode, 2)
            self.assertEqual(open(self.path).read(), text)
            self.assertEqual(self.backups(), [])

    def test_backup_never_overwritten(self):
        self.write('{"a": 1}')
        import settings_merge
        stamp_orig = settings_merge.datetime.datetime
        class Fixed(stamp_orig):
            @classmethod
            def now(cls, tz=None):
                return stamp_orig(2026, 1, 2, 3, 4, 5)
        settings_merge.datetime.datetime = Fixed
        try:
            existing = self.path + ".bak-homehub-20260102-030405"
            open(existing, "w").write("PRECIOUS")
            self.assertEqual(settings_merge.main(["--settings", self.path, "--hook-cmd", CMD, "--apply"]), 0)
        finally:
            settings_merge.datetime.datetime = stamp_orig
        self.assertEqual(open(existing).read(), "PRECIOUS")
        self.assertEqual(open(existing + "-1").read(), '{"a": 1}')

    def test_unmerge_missing_file_is_noop(self):
        r = self.run_cli("--apply", "--unmerge")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
