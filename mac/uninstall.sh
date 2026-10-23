#!/bin/bash
# Remove everything install.sh added. Leaves logs. Flags: --dry-run, --yes.
# Keeps going past a failing step and reports all failures at the end.
set -uo pipefail

DRY=0
YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/usr/bin/python3
APP="$HOME/Library/Application Support/homehub-mac"
ENV_FILE="$HOME/.config/homehub/helper.env"
LA_DIR="$HOME/Library/LaunchAgents"
SETTINGS="$HOME/.claude/settings.json"
GUI="gui/$(id -u)"
FAILS=""
fail() { FAILS="${FAILS}  - $*"$'\n'; }
act() { if [ "$DRY" = 1 ]; then echo "[dry-run] would: $*"; return 1; fi; return 0; }

if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
  printf "Remove the homehub Mac helpers? [y/N] "
  ANS=""
  read -r ANS || true
  case "$ANS" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 0 ;; esac
fi

for n in presence usage; do
  PLIST="$LA_DIR/dev.homehub.$n.plist"
  if act "unload and delete $PLIST"; then
    launchctl bootout "$GUI" "$PLIST" >/dev/null 2>&1 || true
    rm -f "$PLIST" || fail "could not delete $PLIST"
  fi
done

if [ -f "$SETTINGS" ]; then
  if [ "$DRY" = 1 ]; then
    "$PY" "$HERE/settings_merge.py" --settings "$SETTINGS" --unmerge --dry-run || fail "could not preview hook removal in $SETTINGS"
  else
    "$PY" "$HERE/settings_merge.py" --settings "$SETTINGS" --unmerge --apply || fail "could not remove hooks from $SETTINGS"
  fi
fi

if act "claude mcp remove homehub"; then
  if command -v claude >/dev/null 2>&1; then
    claude mcp remove homehub -s user >/dev/null 2>&1 || true  # fails harmlessly when not registered
  else
    fail "claude CLI not found; remove the homehub MCP server manually"
  fi
fi

if act "delete $APP and $ENV_FILE"; then
  rm -rf "$APP" || fail "could not delete $APP"
  rm -f "$ENV_FILE" || fail "could not delete $ENV_FILE"
  rmdir "$(dirname "$ENV_FILE")" 2>/dev/null || true
fi

if [ -n "$FAILS" ]; then
  echo "Uninstall finished with problems:" >&2
  printf '%s' "$FAILS" >&2
  exit 1
fi
echo "Uninstalled. Logs in ~/Library/Logs/homehub-mac were left in place."
