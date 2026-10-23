# Mac Helpers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Alex's Mac to the home server with three small background helpers:
- report desk activity, so the frame switches off when he's away;
- forward Claude Code hook events, so the dashboard shows live sessions and "Needs you";
- push Claude plan usage, so the usage meters work.

The plan also registers the server's MCP task tool with Claude Code, so "add a task …" works from any session.

**Architecture:** Python 3.9-compatible standard-library scripts. macOS ships `/usr/bin/python3` 3.9, so the scripts need no installs. They live in the repo's `mac/` folder and are copied to `~/Library/Application Support/homehub-mac/` by an installer. Two LaunchAgents run on timers:
- **presence**, every 60 s;
- **usage**, every 300 s.

Claude Code hooks call a forwarder script that detaches immediately, so Claude is never slowed down. All three share one small client module that reads `~/.config/homehub/helper.env` (mode 0600), which holds `HOMEHUB_URL` and `HOMEHUB_SECRET`. The installer merges hooks into `~/.claude/settings.json`, keeping Alex's existing hooks and status line and backing the file up first. It registers the MCP server with `claude mcp add`.

**Tech Stack:** Python 3.9 standard library only (`urllib.request`, `json`, `subprocess`, `os`); `launchd`; the macOS `security` and `ioreg` CLIs; the Claude Code CLI. Tests use `/usr/bin/python3 -m unittest`.

**Spec:** `docs/superpowers/specs/2026-10-22-photo-frame-dashboard-design.md` §7 ("Claude", "Mac activity helper"). **Contract:** `docs/api-contract.md` → "Helper endpoints (bearer secret)".

## Global Constraints

- Python 3.9 standard library only. No third-party packages, no f-string `=` debugging, and no `match` statements.
- Nothing ever prints or logs the shared secret, the Claude OAuth token, hook message text, tool inputs, transcript paths or full `cwd`. Logs go to `~/Library/Logs/homehub-mac/*.log` and contain only short status lines.
- Every network call has a timeout of 3 s or less (hook forwarder 2 s). A failure is swallowed after one short log line. A helper never crashes the LaunchAgent into a respawn loop.
- **Claude Code must never be slowed or broken by the hooks.** The hook command prints nothing to stdout, exits 0 within 50 ms (it double-forks to post in the background), and ignores all errors.
- The hook forwarder sends a **reduced** payload only: `hook_event_name`, `session_id`, `cwd`, `notification_type`, `tool_name`, plus `message` for Notification events only, truncated to 200 characters. The server only uses these fields, and the rest can contain code or file contents.
- The usage helper reads the Claude Code OAuth token from the macOS Keychain item `Claude Code-credentials` using `security find-generic-password -s "Claude Code-credentials" -w`. The token stays in memory only and is used solely to call Anthropic's usage endpoint over HTTPS. **Only percentages, reset times and the plan name** are sent to the home server. (Alex decided this, accepting that it is unofficial and may break.)
- The installer is idempotent and reversible. It backs up `~/.claude/settings.json` to `settings.json.bak-homehub-<timestamp>` before changing it, shows a diff and asks for confirmation. It keeps all existing hooks (currently `PostToolUseFailure` and `SessionStart`) and the existing `statusLine`. `uninstall.sh` removes exactly what was added.
- The repo is public, so no real URLs other than placeholders (`http://homehub.local`), no secrets and no personal data go into committed files.
- The server URL is `http://localhost:8000` while the server runs on the Mac, and `http://homehub.local` after the Pi deploy. It's a single setting in `helper.env`.

## Review Focus

1. **The hook forwarder never delays or breaks Claude Code.** That covers the server being down, slow, or answering 401 or 413; malformed stdin; a huge `PreToolUse` payload; and a missing `helper.env`. In every case the command must exit 0 quickly with empty stdout. Tested in Task 2.
2. **Secrets stay out of logs and argv.** The token is never placed on a command line visible in `ps`, other than the `security` call itself. Neither the token nor the secret appears in log files. `helper.env` is mode 0600. Tested in Tasks 1, 4 and 5.
3. **The settings merge preserves Alex's config.** Existing hooks, matchers and `statusLine` stay byte-equivalent. Re-running the installer doesn't duplicate hooks. Uninstall restores exactly. Tested in Task 5.
4. **Presence when asleep, locked or off-network.** No posts while asleep (LaunchAgents don't run). When locked or idle, the helper posts nothing new, so the server goes idle after 30 min. When off the home network, the post times out quietly. Tested in Task 3.
5. **Usage payload shape drift.** If Anthropic's response changes or the token has expired (401), the helper sends nothing (the server then shows "Usage unavailable" after 30 min) and logs one line. It never posts garbage. Tested in Task 4.

---

## File Structure

```
mac/
  README.md                       # what each helper does, install/uninstall, privacy notes
  homehub_client.py               # load helper.env, post_json(path, body, timeout) -> bool, log()
  claude_hook.py                  # stdin hook JSON -> reduced payload -> detached POST /api/claude/hook
  presence.py                     # HIDIdleTime -> POST /api/presence when active
  usage.py                        # Keychain token -> Anthropic usage -> POST /api/claude/usage
  settings_merge.py               # merge/unmerge homehub hooks into ~/.claude/settings.json (pure functions + CLI)
  launchagents/dev.homehub.presence.plist.in
  launchagents/dev.homehub.usage.plist.in
  install.sh                      # copy scripts, write helper.env (0600), load agents, merge hooks, add MCP
  uninstall.sh
  tests/test_client.py  test_hook.py  test_presence.py  test_usage.py  test_settings_merge.py
```

---

### Task 1: Shared client and config

**Files:** `mac/homehub_client.py`, `mac/tests/test_client.py`

**Interfaces:**
- `load_config(path=DEFAULT_ENV) -> dict|None` parses `KEY=value` lines and returns `{"url", "secret"}`, or `None` if the file is missing, incomplete, or readable by group or others (mode not 0600), logging one line in that last case.
- `post_json(path: str, body: dict, timeout: float = 3.0, cfg=None) -> bool` POSTs JSON with `Authorization: Bearer <secret>` and `Content-Type: application/json`. It returns True on 2xx and never raises.
- `log(name: str, msg: str)` appends a timestamped line to `~/Library/Logs/homehub-mac/<name>.log`, capped at about 200 KB by truncating the oldest half.

- [ ] **Step 1: Write failing tests** with a local `http.server` on 127.0.0.1:
  - The bearer header and content type are sent.
  - A 401 response returns False.
  - Server down returns False within the timeout.
  - `load_config` rejects a 0644 file and accepts a 0600 one.
  - The log file never contains the secret, even when the server echoes it back.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s mac/tests -p 'test_client.py'`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(mac): shared homehub client`

### Task 2: Claude Code hook forwarder

**Files:** `mac/claude_hook.py`, `mac/tests/test_hook.py`

**Interfaces:**
- `reduce(payload: dict) -> dict|None` keeps only the allowed fields listed in the constraints. It returns `None` when `session_id` or `hook_event_name` is missing.
- `main(stdin) -> int` reads at most 2 MB from stdin, reduces it, and double-forks. The child posts to `/api/claude/hook` with a 2 s timeout, while the parent returns 0 at once. The parent never writes to stdout or stderr.

- [ ] **Step 1: Write failing tests:**
  - `reduce` drops `tool_input`, `transcript_path` and `prompt`.
  - `message` is only kept for Notification events, truncated to 200 characters.
  - Running the script as a subprocess with valid, malformed, empty and 5 MB inputs exits 0 in under 200 ms with empty stdout. A test server confirms the reduced body arrives for valid input.
  - With a missing `helper.env` it still exits 0.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s mac/tests -p 'test_hook.py'`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(mac): Claude Code hook forwarder`

### Task 3: Presence helper

**Files:** `mac/presence.py`, `mac/launchagents/dev.homehub.presence.plist.in`, `mac/tests/test_presence.py`

**Interfaces:**
- `idle_seconds() -> float|None` parses `HIDIdleTime` (nanoseconds) from `ioreg -c IOHIDSystem -d 4 -k HIDIdleTime -r`, with a 2 s subprocess timeout.
- `main() -> int` does nothing if idle is 120 s or more, or unknown. Otherwise it posts `{active: true, at: <now - idle, ISO with local offset>}` to `/api/presence`. It always exits 0.
- The plist uses `StartInterval` 60, `RunAtLoad` true and `ProcessType` Background. It runs `/usr/bin/python3 <installed path>/presence.py`, logs stdout and stderr to the log directory, and does not set `KeepAlive`.

- [ ] **Step 1: Write failing tests:**
  - Parsing real `ioreg` output fixtures (generic) works.
  - Idle 30 s posts with the correct `at`; idle 500 s does not post.
  - `ioreg` failing or timing out means no post and exit 0.
  - The plist template renders to valid XML with the correct interval.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s mac/tests -p 'test_presence.py'`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(mac): desk presence helper`

### Task 4: Claude usage helper

**Files:** `mac/usage.py`, `mac/launchagents/dev.homehub.usage.plist.in`, `mac/tests/test_usage.py`

**Interfaces:**
- `read_credentials() -> dict|None` runs `security find-generic-password -s "Claude Code-credentials" -w` with a 5 s timeout and parses the JSON. It returns `{"token", "plan"}` from `claudeAiOauth.accessToken` and `claudeAiOauth.subscriptionType`, or `None`, and never logs the value.
- `fetch_usage(token) -> dict|None` calls `GET https://api.anthropic.com/api/oauth/usage` with `Authorization: Bearer <token>` and `anthropic-beta: oauth-2025-04-20`, with a 5 s timeout. It returns the parsed JSON, or `None` on any error or a 401.
- `to_payload(creds_plan, usage_json) -> dict|None` maps `five_hour.utilization` to `session.pct` and `five_hour.resets_at` to `session.resetsAt`, and `seven_day.*` to `weekly.*`. It validates that the percentages are numbers from 0 to 100 and that `resetsAt` parses as an ISO date with an offset. `plan` is the title-cased subscription type (for example "Max"). It returns `None` on any deviation.
- `main() -> int` posts to `/api/claude/usage` when the payload is valid, and always exits 0.
- **The endpoint and field names are unofficial.** Step 4 verifies them live, read-only, printing only the key names and the percentages, and adjusts the parser if they differ.

- [ ] **Step 1: Write failing tests:**
  - `to_payload` works on a generic fixture.
  - Missing fields, a percentage over 100 or a non-ISO reset each give `None`.
  - `read_credentials` uses a fake `security` binary placed first on PATH; its malformed output gives `None`.
  - `fetch_usage` returns `None` on a 401 from a local server; the real endpoint is never called in tests.
  - The token never appears in logs.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s mac/tests -p 'test_usage.py'`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Then a **live read-only check with Alex present**, because macOS will show a Keychain prompt: `/usr/bin/python3 mac/usage.py --print-keys`. This prints only the response's key names and the two percentages, and makes no POST.
- [ ] **Step 5: Commit:** `feat(mac): Claude plan usage helper (Keychain token, percentages only)`

### Task 5: Installer, settings merge, MCP registration

**Files:** `mac/settings_merge.py`, `mac/install.sh`, `mac/uninstall.sh`, `mac/README.md`, `mac/tests/test_settings_merge.py`

**Interfaces:**
- `merge(settings: dict, hook_cmd: str) -> dict` adds one entry per event to `settings["hooks"]`. The events are SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop and SessionEnd. Each entry is `{matcher: "*", hooks: [{type: "command", command: hook_cmd, timeout: 5}]}`, appended after any existing entries. The command is tagged so it can be found again: it contains the installed path `homehub-mac/claude_hook.py`. If the tagged entry is already present, the merge does nothing.
- `unmerge(settings) -> dict` removes only the tagged entries, and removes an event key only if it is left empty.
- The `settings_merge.py` CLI supports `--dry-run`, which prints a unified diff, and `--apply`, which writes a timestamped backup and then the file.
- `install.sh` performs these steps:
  1. Checks `/usr/bin/python3` and the `claude` CLI.
  2. Copies the scripts to `~/Library/Application Support/homehub-mac/`.
  3. Asks for `HOMEHUB_URL`, defaulting to `http://localhost:8000`. It reads the secret from `server/config.toml` if the repo is on this Mac, using Python's tomllib if it exists, otherwise a simple regex; failing that, it prompts with input hidden. It writes `~/.config/homehub/helper.env` with umask 077.
  4. Renders and loads both LaunchAgents with `launchctl bootstrap gui/$UID`.
  5. Shows the settings diff and asks y/N before applying it.
  6. Runs `claude mcp add --scope user --transport http homehub "$URL/mcp" --header "Authorization: Bearer $SECRET"`, after removing any existing `homehub` entry.
  7. Prints a summary.
- `uninstall.sh` reverses all of these, leaving the logs.

- [ ] **Step 1: Write failing tests:**
  - Merging Alex's current shape (`PostToolUseFailure` and `SessionStart` entries plus `statusLine`) preserves them exactly and adds the seven events.
  - Merging twice is idempotent.
  - `unmerge` after `merge` equals the original.
  - Unknown top-level keys are preserved.
  - `install.sh` and `uninstall.sh` pass `bash -n`, and running `install.sh --dry-run` in a temp HOME touches nothing outside it.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s mac/tests`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all mac tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(mac): installer with safe Claude settings merge and MCP registration`

### Task 6: Install on Alex's Mac and verify end to end (with Alex)

- [ ] **Step 1: Run the installer.** Alex runs `mac/install.sh` in Terminal, reviews the settings diff and approves it.
- [ ] **Step 2: Check presence.** The dashboard's screen stays on while he works. `tail ~/Library/Logs/homehub-mac/presence.log` shows posts.
- [ ] **Step 3: Check the hooks.** Start a Claude Code session in any folder: the Claude screen shows it as Working, and then Done after Stop. Trigger a permission prompt, and it shows "Needs you".
- [ ] **Step 4: Check usage.** Within 5 minutes the usage meters show percentages. Accept the Keychain prompt with "Always Allow" if Alex chooses to.
- [ ] **Step 5: Check the MCP tool.** In a fresh Claude Code session, "Add a task for Alex for tomorrow to go for a run" makes the task appear on the dashboard as "tomorrow". `claude mcp list` shows `homehub` connected.
- [ ] **Step 6: Commit** any README corrections: `docs(mac): install notes from first run`
