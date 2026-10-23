#!/bin/bash
# Install the homehub Mac helpers.
# Flags: --dry-run (change nothing), --yes (skip y/N prompt; tests only), --url <server url>.
set -euo pipefail

DRY=0
YES=0
URL_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --url) shift; [ $# -gt 0 ] || { echo "--url needs a value" >&2; exit 2; }; URL_ARG="$1" ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY=/usr/bin/python3
APP="$HOME/Library/Application Support/homehub-mac"
CONF_DIR="$HOME/.config/homehub"
ENV_FILE="$CONF_DIR/helper.env"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/homehub-mac"
SETTINGS="$HOME/.claude/settings.json"
TOML="${HOMEHUB_CONFIG_TOML:-$REPO/server/config.toml}"
GUI="gui/$(id -u)"
HOOK_CMD="$PY \"$APP/claude_hook.py\""
RETRY_SLEEP="${HOMEHUB_RETRY_SLEEP:-1}"
SCRIPTS="homehub_client.py claude_hook.py presence.py usage.py"

STEP="starting"
MUTATING=0
WARNINGS=""
warn() { WARNINGS="${WARNINGS}  - $*"$'\n'; }
say() { echo "$*"; }
# act: returns 1 (and says so) in dry-run, so `if act ...; then <mutation>; fi` is skipped.
act() { if [ "$DRY" = 1 ]; then say "[dry-run] would: $*"; return 1; fi; return 0; }

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$MUTATING" = 1 ]; then
    echo "" >&2
    echo "Install failed during step: $STEP" >&2
    echo "Some changes may already be in place. It is safe to re-run install.sh, or to run uninstall.sh to remove everything." >&2
  elif [ "$rc" -ne 0 ]; then
    echo "Install stopped during: $STEP (nothing was changed)." >&2
  fi
}
trap on_exit EXIT

# ---- validation (no mutation before this block ends) ----
STEP="checking prerequisites"
[ -x "$PY" ] || { echo "error: $PY not found" >&2; exit 1; }
command -v claude >/dev/null 2>&1 || { echo "error: the claude CLI is not on PATH" >&2; exit 1; }
for f in $SCRIPTS settings_merge.py launchagents/dev.homehub.presence.plist.in launchagents/dev.homehub.usage.plist.in; do
  [ -f "$HERE/$f" ] || { echo "error: missing $HERE/$f" >&2; exit 1; }
done

STEP="checking Claude settings (read-only)"
if ! DIFF="$("$PY" "$HERE/settings_merge.py" --settings "$SETTINGS" --hook-cmd "$HOOK_CMD" --dry-run 2>&1)"; then
  echo "error: cannot safely merge into $SETTINGS:" >&2
  echo "$DIFF" >&2
  exit 1
fi

STEP="server URL"
URL="http://localhost:8000"
# Re-runs keep the server already configured, so pressing Enter never resets it to localhost.
if [ -f "$ENV_FILE" ]; then
  OLD_URL="$(sed -n 's/^HOMEHUB_URL=//p' "$ENV_FILE" | head -n 1)"
  [ -n "$OLD_URL" ] && URL="$OLD_URL"
fi
if [ -n "$URL_ARG" ]; then
  URL="$URL_ARG"
elif [ "$DRY" = 0 ]; then
  printf "Server URL [%s]: " "$URL"
  IN_URL=""
  read -r IN_URL || true
  [ -n "$IN_URL" ] && URL="$IN_URL"
  echo
fi
URL="${URL%/}"

STEP="reading shared secret"
SECRET=""
if [ "$DRY" = 1 ]; then
  if [ -f "$TOML" ]; then say "[dry-run] secret would be read from server/config.toml"; else say "[dry-run] secret would be prompted (hidden)"; fi
else
  if [ -f "$TOML" ]; then
    SECRET="$("$PY" - "$TOML" <<'PYEOF'
import re, sys
path = sys.argv[1]
def find(d):
    if isinstance(d, dict):
        if isinstance(d.get("shared_secret"), str):
            return d["shared_secret"]
        for v in d.values():
            r = find(v)
            if r:
                return r
    return None
out = None
try:
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib is not None:
        with open(path, "rb") as f:
            out = find(tomllib.load(f))
    else:
        with open(path) as f:
            m = re.search(r'^\s*shared_secret\s*=\s*(?:"([^"]*)"|\x27([^\x27]*)\x27)\s*(?:#.*)?$', f.read(), re.M)
        if m:
            out = m.group(1) if m.group(1) is not None else m.group(2)
            if "\\" in out:
                out = None
except Exception:
    out = None
sys.stdout.write(out or "")
PYEOF
)" || SECRET=""
    [ "$SECRET" = "CHANGE_ME" ] && SECRET=""
  fi
  if [ -z "$SECRET" ]; then
    printf "Shared secret (input hidden): "
    read -rs SECRET || true
    echo
  fi
  [ -n "$SECRET" ] || { echo "error: no shared secret available" >&2; exit 1; }
fi

# ---- mutation ----
MUTATING=1

STEP="copying scripts"
if act "copy scripts to $APP"; then
  mkdir -p "$APP" "$LOG_DIR"
  for f in $SCRIPTS; do
    cp "$HERE/$f" "$APP/$f"
    chmod 644 "$APP/$f"
  done
  say "copied scripts to $APP"
fi

STEP="writing helper.env"
if act "write $ENV_FILE (mode 0600)"; then
  mkdir -p "$CONF_DIR"
  chmod 700 "$CONF_DIR"
  ( umask 077; printf 'HOMEHUB_URL=%s\nHOMEHUB_SECRET=%s\n' "$URL" "$SECRET" > "$ENV_FILE" )
  chmod 600 "$ENV_FILE"
  say "wrote $ENV_FILE"
fi

for n in presence usage; do
  STEP="loading LaunchAgent dev.homehub.$n"
  PLIST="$LA_DIR/dev.homehub.$n.plist"
  if act "render $PLIST and load it with launchctl bootstrap $GUI"; then
    mkdir -p "$LA_DIR"
    sed -e "s|@PYTHON@|$PY|g" -e "s|@SCRIPT@|$APP/$n.py|g" -e "s|@LOGDIR@|$LOG_DIR|g" \
      "$HERE/launchagents/dev.homehub.$n.plist.in" > "$PLIST"
    chmod 644 "$PLIST"
    launchctl bootout "$GUI" "$PLIST" >/dev/null 2>&1 || true
    if ! launchctl bootstrap "$GUI" "$PLIST" 2>/dev/null; then
      # bootout is asynchronous; bootstrap straight after it can fail with "Bootstrap failed: 5"
      sleep "$RETRY_SLEEP"
      if ! launchctl bootstrap "$GUI" "$PLIST" 2>/dev/null; then
        echo "error: launchctl could not load dev.homehub.$n (tried twice)" >&2
        exit 1
      fi
    fi
    say "loaded dev.homehub.$n"
  fi
done

STEP="merging Claude hooks into settings.json"
say "Proposed change to $SETTINGS:"
echo "$DIFF"
if act "merge hooks into $SETTINGS (with backup)"; then
  APPLY=0
  if [ "$YES" = 1 ]; then
    APPLY=1
  else
    printf "Apply this change? [y/N] "
    ANS=""
    read -r ANS || true
    case "$ANS" in y|Y|yes|YES) APPLY=1 ;; esac
  fi
  if [ "$APPLY" = 1 ]; then
    "$PY" "$HERE/settings_merge.py" --settings "$SETTINGS" --hook-cmd "$HOOK_CMD" --apply
  else
    warn "Claude settings were NOT changed (you declined); hooks are not active"
  fi
fi

STEP="registering MCP server"
if act "register MCP server 'homehub' at $URL/mcp (claude mcp remove, then add)"; then
  claude mcp remove homehub -s user >/dev/null 2>&1 || true
  if claude mcp add --scope user --transport http homehub "$URL/mcp" \
      --header "Authorization: Bearer $SECRET" >/dev/null 2>&1; then
    say "registered MCP server homehub"
  else
    warn "'claude mcp add' failed; register the homehub MCP server manually"
  fi
fi

STEP="summary"
say ""
if [ "$DRY" = 1 ]; then
  say "Dry run complete; nothing was changed."
elif [ -n "$WARNINGS" ]; then
  say "Installed with warnings:"
  printf '%s' "$WARNINGS"
  say "Scripts: $APP | Config: $ENV_FILE | Logs: $LOG_DIR"
else
  say "Installed. Scripts: $APP"
  say "Config: $ENV_FILE (edit HOMEHUB_URL to change server)"
  say "Logs: $LOG_DIR"
fi
