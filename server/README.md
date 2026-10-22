# Home hub

FastAPI server implementing `docs/api-contract.md` for the family dashboard. It pulls
the calendar, weather, photos, shopping list, plugs and speaker into one `GET /api/state`
and accepts the dashboard's actions. A source that is not configured is skipped, and a
source that fails never breaks the others: its section keeps the last good value.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 for you).
- Node.js 22.12 or later (or 20.19+) with npm, to build the dashboard: run `npm ci` once in `dashboard/`
  before `npm run build` or `npm run dev:server`.
- On the Raspberry Pi: **Raspberry Pi OS Lite 64-bit (Bookworm or later)**. The 32-bit
  (armv7) image will not work: pillow and pillow-heif publish no armv7 wheels, so the
  install would try to compile them on the Pi and fail.

## First-time setup

Everything below is run from the `server/` directory and is a one-off. Secrets live only
in `config.toml` and `secrets/`, both git-ignored; never paste them into a commit, an issue
or a chat. Sections you do not need can simply be left out of the config.

1. Install dependencies and create your config. Run `uv sync`, then `cp config.example.toml
   config.toml` and `chmod 600 config.toml`. Open `config.toml` in an editor and work down
   it with the steps below. Set `[location]` to the coordinates and place name the weather
   should use, and give each `[[people]]` and `[[calendars]]` entry the private iCal address
   of that calendar (in Google Calendar: Settings, the calendar, "Integrate calendar",
   "Secret address in iCal format"). Edit `[[routines]]` to match the family's weekly
   outings, or delete them.

2. Generate the shared secret. Run `python -c "import secrets;print(secrets.token_urlsafe(32))"`
   and paste the output over `CHANGE_ME` in `shared_secret`. The helper endpoints (Claude
   hooks, presence, the MCP tool endpoint) require it as a bearer token, and the server
   refuses to start while it is still `CHANGE_ME`.

3. Set up the photo folder (Google Drive). In the Google Cloud console create a project,
   then under "APIs & Services" enable the Google Drive API. Under "IAM & Admin", "Service
   Accounts", create a service account (no roles are needed), open it, choose "Keys", "Add
   key", "Create new key", type JSON, and save the downloaded file as `secrets/drive-sa.json`
   (run `chmod 600 secrets/drive-sa.json`). Copy the service account's email address from
   the same page, open the photo folder in Google Drive, choose Share, paste that email
   address and give it the Viewer role. The folder id is the last part of the folder's
   address: in `https://drive.google.com/drive/folders/<folder id>` it is everything after
   `folders/`. Then add this to `config.toml`:

       [drive]
       folder_id = "<folder id>"
       service_account_file = "secrets/drive-sa.json"

   Subfolders are included. Photos are downloaded once, resized, stripped of location and
   camera metadata and cached under `secrets/photos`.

4. Set up the shopping list (Google Keep). The server signs in as the dedicated frame
   Google account. To use the family's existing list, open it in Keep with your own
   account, choose the collaborator icon and add the frame account's email address; the
   list then appears in the frame account too, and both stay in sync. (Or create a new
   checklist note in the frame account.) Set `list_title` to the list's title (case and
   surrounding spaces are ignored) and add:

       [keep]
       list_title = "Shopping"
       email = "<the frame account's email address>"

   Then run `uv run python scripts/keep_token.py`. It asks for the account email and an
   `oauth_token` cookie, neither of which is echoed. To get the cookie, follow the flow
   from the gkeepapi documentation: in a desktop browser sign in at
   `https://accounts.google.com/EmbeddedSetup` with the frame account and accept the
   prompts (the page may then show a blank or loading screen). Open the browser developer
   tools, go to Application (Chrome) or Storage (Firefox), then Cookies, and copy the value
   of the cookie named `oauth_token`, which starts with `oauth2_4/`. It can only be used
   once, so paste it straight in. The script writes a master token to `secrets/keep-token`
   with mode 0600 and never prints it. If Google ever rejects the token, repeat this step.

5. Set up the smart plugs (TP-Link Tapo). In the Tapo app, open each plug's settings and
   turn on "Third-Party Compatibility" (Me, Third-Party Services); without it the server
   cannot control them. Note each plug's IP address (Tapo app, device settings, or your
   router's device list). Strongly recommended: give each plug a DHCP reservation in the
   router so its address never changes, because the config refers to plugs by address.
   Then add your Tapo account login and one block per plug:

       [tapo]
       username = "<Tapo account email address>"
       password = "<Tapo account password>"

       [[plugs]]
       host = "<plug IP address>"
       name = "Lamp"
       room = "Living room"
       confirm = false   # true makes the dashboard ask before turning it off
       hidden = false    # true marks the plug as hidden from the dashboard

6. Set up the speaker. Add `[speaker]` with `name` set to the speaker's friendly name
   exactly as it appears in the Google Home app, for example `name = "Kitchen speaker"`.
   The server finds it on the local network, so the Mac or Pi must be on the same network
   as the speaker. If it is not found it retries every few minutes.

7. Check everything. Run `uv run homehub --check`. It performs one refresh of each
   provider and prints one line each, for example `OK   calendar  (27 events)`,
   `SKIP speaker  (not configured)` or `FAIL keep  (Keep is not set up)`. It prints counts
   and short reasons only, never titles, names, addresses or links, so the output is safe to
   share. Each provider has 45 seconds; photos are only listed, not downloaded. The exit
   code is 0 unless something shows FAIL. Every provider should be OK or a deliberate SKIP
   before you carry on.

## Screen on and off

The frame's screen follows presence reports from the Mac helper (plan 4). Until that helper
is installed nothing reports presence, so `screen.mode` is `off` during the day as well as
at night, and the frame only lights up for `wake_minutes` after a tap. Until then, raise
`wake_minutes` in `[screen]` (for example to 120) if you want it to stay on longer after a
tap; `idle_minutes` only matters once presence reports arrive.

## Run

Start the server with `uv run homehub`; it listens on `0.0.0.0:8000`. To use the dashboard
with live reload, leave the server running and in a second terminal run
`cd ../dashboard && npm run dev:server`. To serve the dashboard from the server instead,
run `cd ../dashboard && npm ci && npm run build` once and open `http://localhost:8000`. The first
photo sync can take several minutes on a large folder; photos appear as they arrive.

Set `HOMEHUB_CONFIG` to use another config path and `HOMEHUB_DIST` to serve a different
dashboard build (default `../dashboard/dist`). Refresh intervals (seconds, at least 5) can
be tuned in the `[intervals]` table: `events` (default 300), `weather` (1800), `photos`
(21600), `shopping` (60), `tasks` (60), `plugs` (15), `speaker` (10), `claude` (15) and
`screen` (15). Any other key is a config error.

## Develop

    uv run pytest -q
    uv run ruff check
