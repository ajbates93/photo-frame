#!/usr/bin/python3
"""Merge / unmerge the homehub Claude Code hooks in ~/.claude/settings.json.

Python 3.9 stdlib only. merge() and unmerge() are pure functions; the CLI
shows a diff (--dry-run) or writes the file atomically after a backup (--apply).
Never prints anything from the settings file other than the diff of our own change.
"""
import argparse
import copy
import datetime
import difflib
import json
import os
import shutil
import sys
import tempfile

TAG = "homehub-mac/claude_hook.py"
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
          "Notification", "Stop", "SessionEnd"]
DEFAULT_SETTINGS = os.path.expanduser("~/.claude/settings.json")


def default_hook_cmd(home=None):
    home = home or os.path.expanduser("~")
    return '/usr/bin/python3 "%s/Library/Application Support/homehub-mac/claude_hook.py"' % home


def _is_ours(entry):
    try:
        return any(TAG in str(h.get("command", "")) for h in entry.get("hooks", []))
    except Exception:
        return False


class ShapeError(ValueError):
    """settings.json has an unexpected hooks structure; refuse to touch it."""


def merge(settings, hook_cmd, info=None):
    """Return a copy of settings with one tagged entry per event (idempotent).

    If info (a dict) is given it records what this call created:
    info["created_hooks"] (bool) and info["created_events"] (list).
    """
    out = copy.deepcopy(settings)
    if "hooks" in out and not isinstance(out["hooks"], dict):
        raise ShapeError("'hooks' is not an object")
    hooks = out.get("hooks")
    if info is not None:
        info.setdefault("created_events", [])
        info.setdefault("created_hooks", False)
    if hooks is None:
        hooks = {}
        out["hooks"] = hooks
        if info is not None:
            info["created_hooks"] = True
    for event in EVENTS:
        if event in hooks and not isinstance(hooks[event], list):
            raise ShapeError("hooks.%s is not a list" % event)
    for event in EVENTS:
        entries = hooks.get(event)
        if entries is None:
            entries = []
            hooks[event] = entries
            if info is not None:
                info["created_events"].append(event)
        if any(_is_ours(e) for e in entries):
            continue
        entries.append({"matcher": "*", "hooks": [
            {"type": "command", "command": hook_cmd, "timeout": 5}]})
    return out


def unmerge(settings, created=None):
    """Return a copy with only the tagged entries removed.

    created=None: delete an event key / "hooks" that is left empty (legacy).
    created={"created_events": [...], "created_hooks": bool}: delete an emptied
    key only if our merge created it, so pre-existing empty values survive.
    """
    out = copy.deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    removed = False
    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not _is_ours(e)]
        if len(kept) == len(entries):
            continue
        removed = True
        if kept or (created is not None and event not in created.get("created_events", [])):
            hooks[event] = kept
        else:
            del hooks[event]
    if removed and "hooks" in out and hooks == {} and (created is None or created.get("created_hooks")):
        del out["hooks"]
    return out


def _state_path(path):
    return path + ".homehub-state"


def _read_state(path):
    try:
        with open(_state_path(path)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _free_backup(path, stamp):
    base = "%s.bak-homehub-%s" % (path, stamp)
    cand, n = base, 0
    while os.path.exists(cand):
        n += 1
        cand = "%s-%d" % (base, n)
    return cand


def _dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def _atomic_write(path, text, mode):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-homehub-", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=DEFAULT_SETTINGS)
    ap.add_argument("--hook-cmd", default=None)
    ap.add_argument("--unmerge", action="store_true")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    path = a.settings
    cmd = a.hook_cmd or default_hook_cmd()

    exists = os.path.exists(path)
    if exists:
        with open(path) as f:
            old_text = f.read()
        try:
            current = json.loads(old_text)
            if not isinstance(current, dict):
                raise ValueError("not an object")
        except ValueError:
            sys.stderr.write("error: %s is not valid JSON settings; nothing changed\n" % path)
            return 2
        mode = os.stat(path).st_mode & 0o7777
    else:
        old_text, current, mode = "", {}, 0o600

    info = {}
    try:
        if a.unmerge:
            if not exists:
                print("no settings file; nothing to remove")
                return 0
            new = unmerge(current, _read_state(path))
        else:
            new = merge(current, cmd, info)
    except ShapeError as e:
        sys.stderr.write("error: unexpected settings structure (%s); nothing changed\n" % e)
        return 2

    if new == current and exists:
        print("settings.json already up to date; no changes")
        if a.unmerge and a.apply and os.path.exists(_state_path(path)):
            os.unlink(_state_path(path))
        return 0
    new_text = _dump(new)
    if a.dry_run:
        diff = difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                    "settings.json (current)", "settings.json (proposed)")
        sys.stdout.write("".join(diff))
        return 0

    if exists:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = _free_backup(path, stamp)
        shutil.copy2(path, backup)
        print("backup: " + backup)
    _atomic_write(path, new_text, mode)
    if a.unmerge:
        if os.path.exists(_state_path(path)):
            os.unlink(_state_path(path))
    elif not os.path.exists(_state_path(path)):
        _atomic_write(_state_path(path), json.dumps(info), 0o600)
    print("updated: " + path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
