# Mac helpers

Three small helpers that run on your Mac and tell the home dashboard what you are up to. They use only the Python 3 that ships with macOS (`/usr/bin/python3`), so there is nothing to install besides the helpers themselves.

## What each helper does

The presence helper runs every minute under a LaunchAgent. If you used the Mac within the last two minutes, it tells the server you are at your desk. If the Mac is idle, locked or asleep it sends nothing, and the server marks you as away after about half an hour.

The Claude hook forwarder is registered in `~/.claude/settings.json` for seven Claude Code events (session start and end, prompt submit, before and after tools, notifications and stop). It sends a reduced summary of each event to the server so the dashboard can show what Claude Code is doing. It never slows Claude Code down: it prints nothing, exits straight away and posts in the background.

The usage helper runs every five minutes. It reads your Claude Code login from the macOS Keychain, asks Anthropic how much of your plan you have used, and sends the percentages to the server. This relies on an unofficial endpoint and may stop working without notice; if it does, the dashboard simply shows usage as unavailable.

The installer also registers the server as a Claude Code MCP server called `homehub`.

## Privacy: what leaves the Mac

Only your home server receives anything, at the address in `helper.env`. Presence sends a timestamp. The hook forwarder sends the event name, session id, the working directory, the tool name and notification type, plus the message text for notification events only, cut to 200 characters. It never sends prompts, tool inputs, file contents or transcripts. The usage helper sends percentages, reset times and the plan name. The Claude login token stays in memory, is used only to call Anthropic over HTTPS, and is never sent to the home server or written to logs. The shared secret lives in `~/.config/homehub/helper.env` with permissions 0600 and is never printed or logged by these helpers. There is one exception you should know about: the installer registers the server with `claude mcp add --header`, which stores the shared secret in plain text in `~/.claude.json` (under the user-scope `mcpServers.homehub.headers`), and the secret is briefly visible in the argument list of that one `claude` process while it runs. The secret only protects your home network server, and you can rotate it by changing it in `helper.env` and in the server config, then re-running `mac/install.sh`.

## Install

From the repository root run `mac/install.sh`. Use `mac/install.sh --dry-run` first to see what would happen without changing anything. The installer asks for the server URL (default `http://localhost:8000`), takes the shared secret from `server/config.toml` if the repository is on this Mac (otherwise it asks, with the input hidden), copies the scripts to `~/Library/Application Support/homehub-mac/`, loads the two LaunchAgents, shows you the proposed change to `~/.claude/settings.json` and asks before applying it, and finally registers the MCP server. Before editing your Claude settings it saves a backup next to it called `settings.json.bak-homehub-<timestamp>`. Your existing hooks and status line are left alone, and running the installer again does not duplicate anything.

## Uninstall

Run `mac/uninstall.sh`. It unloads and deletes the LaunchAgents, removes only the hooks the installer added (with a fresh backup), removes the MCP server, and deletes the installed scripts and `helper.env`. Logs are left in place.

## Changing the server URL

Edit `~/.config/homehub/helper.env` and change `HOMEHUB_URL`, for example to `http://homehub.local` once the Pi is running. The helpers read the file each time they run, so there is nothing to reload. The MCP registration holds its own copy of the URL, so re-run `mac/install.sh` after changing it.

## Troubleshooting

Logs are in `~/Library/Logs/homehub-mac/`: `presence.log`, `usage.log`, `client.log` and `hook.log` hold short status lines, and the `*.out.log` and `*.err.log` files capture anything the LaunchAgents print. If a helper seems silent, check that `helper.env` exists with mode 0600 (`ls -l ~/.config/homehub/helper.env`); the helpers ignore a file that other users can read. Check the agents are loaded with `launchctl print gui/$(id -u)/dev.homehub.presence`. If usage stops updating, the Anthropic endpoint or your login has probably changed; the log will say so in one line.
