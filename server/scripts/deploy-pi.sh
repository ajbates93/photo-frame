#!/usr/bin/env bash
# Deploy homehub to the Raspberry Pi as a systemd user service.
#
# Usage: server/scripts/deploy-pi.sh <user@host>      e.g. alex@homehub.local
#
# 1. Builds the dashboard.
# 2. Copies server/ (without .venv, secrets or config.toml) and dashboard/dist to ~/homehub.
# 3. First run only: copies config.toml and secrets/ (mode 0600, folders 0700).
#    Later runs never overwrite them, so the Pi's tasks and tokens stay put.
#    Stop any other homehub (e.g. on the Mac) first, so state.db is copied at rest.
# 4. Installs uv if missing, then runs `uv sync --frozen --no-dev`.
# 5. Installs and restarts the homehub user service, then waits for /api/health.
#
# One-time root setup on the Pi (the script checks and prints these if missing):
#   sudo loginctl enable-linger $USER
#   echo net.ipv4.ip_unprivileged_port_start=80 | sudo tee /etc/sysctl.d/90-homehub.conf
#   sudo sysctl --system
set -euo pipefail

HOST="${1:?usage: deploy-pi.sh <user@host>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH=(ssh -o BatchMode=yes "$HOST")

say() { printf '\n==> %s\n' "$*"; }

say "Checking the Pi's one-time setup"
"${SSH[@]}" 'set -e
missing=0
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]; then
  echo "    missing: sudo loginctl enable-linger $USER"; missing=1
fi
port_start="$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start 2>/dev/null || echo 1024)"
if ! [ "$port_start" -le 80 ] 2>/dev/null; then
  echo "    missing: echo net.ipv4.ip_unprivileged_port_start=80 | sudo tee /etc/sysctl.d/90-homehub.conf && sudo sysctl --system"
  missing=1
fi
[ $missing -eq 0 ] || { echo "    Run the missing commands on the Pi (they need your password), then deploy again."; exit 1; }
echo "    ok"'

say "Building the dashboard"
(cd "$ROOT/dashboard" && npm run build)

say "Copying the server and dashboard"
"${SSH[@]}" 'mkdir -p ~/homehub/server ~/homehub/dashboard/dist'
rsync -az --delete \
  --exclude .venv --exclude secrets --exclude config.toml \
  --exclude __pycache__ --exclude .pytest_cache \
  "$ROOT/server/" "$HOST:homehub/server/"
rsync -az --delete "$ROOT/dashboard/dist/" "$HOST:homehub/dashboard/dist/"

if "${SSH[@]}" 'test -f ~/homehub/server/config.toml'; then
  say "Keeping the Pi's own config.toml and secrets"
else
  say "First run: copying config.toml and secrets"
  [ -f "$ROOT/server/config.toml" ] || { echo "    server/config.toml not found" >&2; exit 1; }
  # macOS's built-in rsync has no --chmod, so tighten the modes on the Pi before and after.
  "${SSH[@]}" 'umask 077; mkdir -p ~/homehub/server/secrets'
  rsync -a "$ROOT/server/secrets/" "$HOST:homehub/server/secrets/"
  rsync -a "$ROOT/server/config.toml" "$HOST:homehub/server/config.toml"
fi
# Every run, so a first run that stopped half way never leaves the secret readable.
"${SSH[@]}" 'cd ~/homehub/server && chmod 600 config.toml && chmod 700 secrets &&
  find secrets -type d -exec chmod 700 {} + && find secrets -type f -exec chmod 600 {} +'

say "Installing Python packages"
"${SSH[@]}" 'set -e
if [ ! -x ~/.local/bin/uv ]; then
  echo "    installing uv (astral.sh official installer) into ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --no-modify-path >/dev/null
fi
cd ~/homehub/server && ~/.local/bin/uv sync --frozen --no-dev'

say "Installing and restarting the service"
"${SSH[@]}" 'set -e
mkdir -p ~/.config/systemd/user
cp ~/homehub/server/scripts/homehub.service ~/.config/systemd/user/homehub.service
systemctl --user daemon-reload
systemctl --user enable homehub.service >/dev/null 2>&1
systemctl --user restart homehub.service
for i in $(seq 1 60); do
  if curl -fs -o /dev/null http://localhost/api/health; then echo "    healthy after ${i}s"; exit 0; fi
  sleep 1
done
echo "    not healthy after 60 s; last log lines:"
journalctl --user -u homehub -n 30 --no-pager
exit 1'

say "Deployed: http://${HOST#*@}/"
