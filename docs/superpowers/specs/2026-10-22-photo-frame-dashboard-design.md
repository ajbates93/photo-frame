# Photo frame family dashboard: design

**Date:** 22 October 2026
**Owner:** Alex Bates
**Status:** Ready for Alex's review (builder check done)

## TL;DR

We are turning a £50 Humblestead 10.1" Android photo frame into a wall dashboard for Alex's office, later possibly a shared room. The frame shows a single full-screen web page and holds no passwords. A Raspberry Pi 3A+ on the home network does the real work: it reads Google Calendar, two-way syncs a Google Keep shopping list, stores a family task list, serves photos from a Google Drive folder, switches the Tapo smart plugs on the household's lamps, controls a Nest speaker, and shows the status of Alex's Claude Code sessions. Everything runs inside the house in v1. The design starts from Wes Bos's open-source [photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard) (MIT), which provides the unlock guides, a kiosk app and a mock-data dashboard, but none of the real data connections.

## 1. Intent

Alex likes the family dashboard Wes Bos built on a hacked photo frame (video: <https://www.youtube.com/watch?v=ZLycoUMltNI>) and wants his own version, wired to the services the household already uses rather than to mock data. The frame should be useful at a glance from across the room: what's next, what the day and tomorrow look like, the weather, what needs buying, what needs doing, and whether Claude is waiting on him. It should also feel like a photo frame, not a monitor: warm, calm and quiet when nobody is looking at it.

The household is Alex and Vicky. Both add events to a **"Family" calendar** in Google Calendar. It is a secondary calendar owned by Alex's personal Google account and shared with their Google family group, so it is not a separate Google account. They use Notion Calendar as their calendar app, but Notion Calendar is only a front end over Google Calendar; the events live in Google. They share a Google Keep shopping list. Vicky does not use Claude. Alex mostly works from his laptop, at a desk near where the frame will hang at first.

## 2. Goals, non-goals and anti-goals

**Goals (v1)**

- A glanceable "command centre" home screen, plus a full screen for each area, as described in section 5.
- Real data from Google Calendar, Google Keep, Google Drive, Tapo, the Nest speaker and Claude Code.
- Two-way shopping list: items added or ticked on the frame show up in Google Keep and vice versa.
- A family task board that Alex can add to by telling Claude Code in plain English ("add a task to pick up the Vinted order from the garage after work today"), and that Vicky can use from the touchscreen.
- A day theme and a night theme that switch automatically, and a screen that turns itself off when nobody is around.

**Non-goals (v1)**

- Access from outside the house. Adding tasks from the Claude phone app or claude.ai needs the Pi to be reachable from the internet; that is **v2**, via a Cloudflare Tunnel.
- Home Assistant. The Pi controls the plugs and speaker directly.
- Full Google Assistant control of the Nest speaker. Media controls only.
- API spend tracking for Claude. Alex uses a subscription plan, not the API.
- Pi-hole. Planned for later on the same Pi, after the dashboard has proved stable for a week or two (see section 10).

**Anti-goals: things that would make this a failure even if it works**

- **The frame becomes a security hole on the home network.** The stock AiMOR app gives the vendor's server a root shell over an unencrypted connection (see [aimor-remote-root-shell.md](https://github.com/wesbos/photo-frame-dashboard/blob/main/docs/aimor-remote-root-shell.md)). It must be removed or disabled and its server blocked before the frame stays online, and no temporary open root-ADB port may be left running.
- **Secrets on the frame.** No calendar links, tokens, passwords or API keys on the frame or in the page it loads. Anyone with ADB access to the frame could read them.
- **Bricking the frame.** No write to the frame happens without a verified backup and Alex's explicit approval of that specific write (the rules in Wes's README, which this project adopts).
- **A slow, janky screen.** The frame has 1 GB of RAM and an old browser engine. A dashboard that stutters, leaks memory or needs a daily reboot is a failure.
- **Fragile family plumbing.** Nothing here should be able to knock the household offline or lose items from the real shopping list.

## 3. The hardware

### The frame

The Amazon listing is [B0GGB7LWX8](https://www.amazon.co.uk/dp/B0GGB7LWX8) (Humblestead 10.1"). Wes's repo lists this exact listing as a confirmed working frame with the **PF1007L** board. Expect, but confirm on arrival:

| Item | Expected |
| --- | --- |
| Board / chip | PF1007L, Allwinner A33 |
| Android | 6.0.1, SDK 23, `armeabi-v7a` |
| RAM / screen | 1 GiB / 1280 × 800, density 160 |
| Stock app | AiMOR (`com.efercro.os.aimor`), the home screen and the remote root shell |
| Stock WebView | 44, which must be upgraded to WebView 106 per Wes's PF1007L guide |
| Touch | `gslX680` panel: two-finger gestures need fingers about 2.5 cm apart |
| Sensors | Accelerometer; light sensor listed but unverified; **no camera, motion or proximity sensor** |
| Navigation | No SystemUI on some units; an invisible overlay can swallow taps in the bottom ~64 px |
| USB | Needs a **USB-A to USB-C** data cable (Alex has one). C-to-C gives no power or data |

### The Pi

A **Raspberry Pi 3A+** (4-core 64-bit, 512 MB RAM, Wi-Fi, one USB-A port, no Ethernet), set up headless with Raspberry Pi OS Lite, Wi-Fi and SSH configured in Raspberry Pi Imager. It sits near the router and runs on Wi-Fi. Alex is buying the board, the official power supply and a case from The Pi Hut, plus a SanDisk Ultra 32 GB twin pack and a USB card reader from Amazon.

### Home network

Specific router and network details are kept in a private, git-ignored note (`private/network.md`), because this repo is public. Only what matters for the design is recorded here:

- **Wi-Fi networks:** an ISP-supplied router with a main network (WPA2/WPA3), a separate **legacy** network for older devices, and range extenders. The guest network is off.
- **No inbound connections:** the connection is behind **carrier-grade NAT**, so nothing can be port-forwarded into the house. The v2 remote access **must** use an outbound tunnel such as Cloudflare Tunnel. That was already the plan.
- **Requirement:** the frame, Pi, plugs and Nest speaker must all be on the same local network. Local Tapo control and Cast discovery don't cross a guest or isolated network. The legacy network is believed to be the same LAN; confirm this on the router's client list.
- **My call:** put the frame on the **legacy** network. Its Android 6 Wi-Fi is old and may not cope with WPA3 transition mode. The Pi 3A+ can use either network.
- **Unknown:** whether this router supports local DNS overrides (needed for the T3c unlock route and for blocking the AiMOR server) and DHCP reservations. Check its advanced settings before starting T3c. If it has no DNS override, the options are, in order: a static DNS server set in the frame's own Wi-Fi settings, if its Wi-Fi screen offers one; blocking on the frame itself after root (hosts file and firewall); or the card-based unlock routes.

### Alex's Mac

The Mac is where Alex works and where the unlock work happens. It also runs two small helpers (section 7).

### Shopping status

Alex has the A-to-C cable. The microSD cards are coming with the Pi order; one is for the Pi and one is a spare in case the frame needs the card-based unlock route.

## 4. How it fits together

```
 ┌──────────────── Alex's Mac ────────────────┐
 │ activity helper ──► "last input" pings      │
 │ Claude Code hooks ─► session status         │
 │ Claude Code ──────► tasks tool (MCP)        │
 └───────────────┬─────────────────────────────┘
                 │ home network
 ┌───────────────▼──────── Raspberry Pi 3A+ ─────────────────────────┐
 │ dashboard server: serves the page + a JSON/live-update API        │
 │  ├─ Google Calendar (secret iCal links)                           │
 │  ├─ Google Keep (gkeepapi, two-way)                               │
 │  ├─ Google Drive photo folder (Drive API, read-only)              │
 │  ├─ Weather + sunrise/sunset                                      │
 │  ├─ Tapo plugs (python-kasa, local)                               │
 │  ├─ Nest speaker (Google Cast, local)                             │
 │  ├─ Tasks store                                                   │
 │  └─ secrets live here only                                        │
 └───────────────┬───────────────────────────────────────────────────┘
                 │ home network
 ┌───────────────▼──────── Frame ───────┐
 │ kiosk app (full-screen WebView)       │
 │ loads http://<pi>/ — no secrets       │
 └───────────────────────────────────────┘
```

**Decided by Alex:** the Pi is the server; v1 stays entirely inside the house; adding tasks from anywhere is a v2 Cloudflare Tunnel.

**My calls (open to challenge):**

- **Server language: Python.** The two libraries that matter most, `python-kasa` (Tapo) and `gkeepapi` (Keep), are Python, as is `pychromecast`. One language on the Pi keeps it simple.
- **Front end: start from Wes's `dashboard/`** (vanilla JS views, Vite, MIT licence), replacing `data.js` mock data with live data from the Pi. Keep its build targets: JS `chrome106`, CSS `chrome61` (the frame's WebView rejects some modern CSS colour syntax).
- **Kiosk: start from Wes's kiosk app** (`dashboard/kiosk/`), with its saved URL pointed at the Pi. It will need extending for backlight control (section 6).
- **The frame reaches the Pi by a fixed address** (a DHCP reservation on the router, or `<name>.local` if mDNS works from Android 6; builder to confirm).

## 5. What's on the screen

### Home screen: "command centre"

Alex picked the command-centre layout and approved the mockup. The approved mockup is [mockups/2026-10-22-home-command-centre.html](mockups/2026-10-22-home-command-centre.html). It is a fragment from the brainstorming tool, so it renders unstyled around the edges if opened directly, but the three themed 1280 × 800 screens render correctly. It uses a three-column grid:

| Left column | Middle column | Right column |
| --- | --- | --- |
| Clock and date | "Next up" card: event title, time, place, a countdown and a "leave by" pill when travel applies | Rotating photo with caption ("1 year ago" / "On this day", place name) |
| Weather: now, high/low, a one-line summary, an hourly strip | Calendar: **Today and Tomorrow** side by side on a time grid | Plug toggles (four Tapo plugs) |
| Tasks count + next task; shopping count + first items | (calendar continues) | Claude tile: session and weekly usage meters, "Needs you" badge |

Calendar details Alex asked for specifically: visible **hour gridlines** with fainter half-hour lines, a **stronger divider between days**, a red **"now" line**, past events greyed out, and short events shown on one line so they never clip. All-day events sit in a strip at the top of their day. Each calendar has its own colour (Alex's blue, family orange in the mockup).

Tapping a tile opens that area's full screen.

### Full screens

These follow Wes's equivalents unless noted. The detailed layout of each is left to the builder, in the same visual language as the home screen.

- **Calendar:** a larger view (a week, or several days) with the same gridlines and colours.
- **Shopping:** the Keep list, with tick-off, quick add, and a list of frequently bought items.
- **Tasks:** one column per person (Alex, Vicky, Anyone), showing due times; add and tick off on the touchscreen.
- **Photos:** full-screen slideshow with captions.
- **Home control:** the four plugs (on/off) and the Nest speaker (what's playing, play/pause, volume).
- **Claude:** usage meters plus a list of live Claude Code sessions and their state.

## 6. Look and behaviour

### Themes

- **Warm paper** by day: cream background, soft borderless cards, serif headings (closest to Wes's look).
- **Night** after sunset: dark background, the same layout. **Decided by Alex:** switch automatically at sunset and sunrise (times from the weather data), fading over a few seconds rather than snapping. A tap can override until the next switch.
- **My call:** Night uses the same serif headings as Warm paper, so the switch reads as "the same dashboard, dimmed", not a different app. The mockup's Night version used sans-serif headings; change that.

### Screen on/off

Decided by Alex:

| When | What happens |
| --- | --- |
| Evening | Dims right down |
| 23:00 | Switches off |
| 07:00 | Switches back on |
| Daytime, no Mac activity for 20–30 min | Switches off |
| Mac activity, or a tap on the screen | Wakes within a few seconds |

**My calls:** "evening" means dimming from 22:00 (an hour before switch-off); the daytime idle timeout defaults to 30 minutes. Both should be easy to change in config.

**How "off" works (important):** Android must stay awake. "Off" means the page goes black and the backlight goes to zero, so the touch panel keeps working and a tap can wake it. Putting Android to sleep (like pressing a phone's power button) usually disables touch, so it must not be used. **Unverified:** whether this panel's backlight goes fully dark at zero; check on the device. The fallback is a black page at minimum brightness.

Backlight control needs root on the frame. The page itself cannot set brightness, so the kiosk app (or a small root helper on the frame) must expose it. Wes's kiosk has no JavaScript bridge today. The builder picks the mechanism.

## 7. Data sources and integrations

### Calendar

- Source: each Google calendar's **secret address in iCal format** (Google Calendar → Settings → the calendar → Integrate calendar). Read-only; no OAuth.
- v1 calendars: **Alex's** and the **family** calendar. Vicky's is added later, so calendars are a list in config (link, label, colour), not hard-coded.
- The secret links are stored only on the Pi. Alex will paste them straight into the Pi's config or secrets file, not into chat or the repo.
- The Pi fetches every few minutes. It must handle recurring events (RRULE, exceptions), all-day and multi-day events, and the `Europe/London` timezone including the clock changes.
- "Leave by": shown when an event has a location away from home. How to estimate travel time is left to the builder; a fixed buffer is acceptable for v1.

### Shopping list: Google Keep (two-way)

- Keep's official API only works for Google Workspace business accounts, not personal Gmail. Alex accepted the unofficial **`gkeepapi`** library, knowing it can break when Google changes things.
- It authenticates with a **master token**, which grants broad access to whichever Google account it belongs to, and it can't be narrowed. **Decided by Alex:** to contain that risk, the token belongs to a **dedicated Gmail account created only for the frame**. That account holds nothing of its own. Alex shares the shopping list note with it as a Keep collaborator, and Alex and Vicky keep using Keep on their phones as normal. If the Pi were compromised, the exposure is that one shared list, not Alex's Gmail, Drive or photos. The dedicated account has a strong unique password and 2-step verification, and its address goes in private config, never in the repo.
- Trade-off accepted: items added from the frame show in Keep as added by the frame account.
- The token lives on the Pi only, with tight file permissions.
- Two-way: items added or ticked on the frame are written to Keep; changes made in Keep appear on the frame within a minute or two.
- Keep is the source of truth. If sync fails, the frame shows the last known list and a small "out of sync" marker, and never deletes items from Keep because of a sync error.

### Tasks

- Tasks live on the Pi (a small database). They don't sync to another service.
- Fields: title, who it's for (Alex / Vicky / Anyone), optional due date and time, done/not done.
- Vicky adds and ticks off tasks on the touchscreen.
- Alex adds tasks from **Claude Code on his laptop** via a small tool on the Pi (an MCP server on the home network) with *add*, *list*, *complete* and *delete*. Claude turns plain English ("after work today") into a title, person and due time.
- **v2:** a Cloudflare Tunnel with authentication, so the same tool works from the Claude phone app and claude.ai.

### Photos: Google Drive folder

- Google stopped letting apps read Google Photos libraries and shared albums in March 2025, so photos come from a **Google Drive folder** instead. Alex agreed.
- The Pi scans the folder **including any sub-folders**, so it can be kept flat or organised without breaking anything.
- The Drive API's photo metadata gives the date taken and GPS position. Captions:
  - "1 year ago", "3 years ago", and "On this day" when the month and day match.
  - A place name from the GPS position via a reverse-geocoding lookup (cached; respect the provider's rate limits).
  - If the date or location is missing (screenshots, WhatsApp images), show no caption. Alex is fine with that.
- The Pi resizes photos to the frame's resolution and caches them. Full-size phone photos must never reach the frame.
- Access, **my call:** a Google Cloud **service account** with read-only Drive access, and the photo folder shared with it. It can see that one folder and nothing else in Alex's account. It also avoids OAuth refresh tokens, which expire after 7 days while a Cloud project is in testing mode. (Sharing the folder with the dedicated frame account and using OAuth is the fallback if a service account proves awkward.)

### Weather

- Location: Alex's home town, set in private config (not in the repo).
- Provider: builder's choice (Open-Meteo needs no key). Must supply current conditions, high and low, hourly forecast, rain timing, and **sunrise and sunset** for the theme switch.

### Smart home

- **Tapo smart plugs**, controlled locally with `python-kasa` using Alex's Tapo account credentials (stored on the Pi). It must keep working when Tapo's cloud is down. Today there are four, **all lamps**: two in the living room, one in the office and one in the bedroom. More are coming, so plugs are discovered on the network (or listed in config), not hard-coded, and they're labelled and grouped by room. Because they're all lamps, one tap toggles them with no confirm step. A per-plug "confirm" or "hidden" option in config is worth having for future plugs that power something important.
- **Kitchen Nest speaker** via the Google Cast protocol (`pychromecast`): now playing, play/pause, volume.
- Changes made elsewhere (the Tapo app, voice) should show up on the frame within a short poll interval.

### Claude

- **Session status (reliable):** Claude Code **hooks** on Alex's Mac post session events to the Pi: working, finished, and **waiting for input**. The home tile shows a "Needs you" badge whenever any session is waiting; the Claude screen lists sessions by project, state and time in that state.
- **Plan usage (best effort):** session and weekly usage meters with reset countdowns. Anthropic doesn't publish an official way to read subscription limits, so this uses an unofficial route. **Alex accepts that it may break** after a Claude Code update. When it does, the meters show "unavailable" and nothing else breaks.
- Alex uses Claude models only. No other AI providers.

### Mac activity helper

A small background helper on Alex's Mac (a LaunchAgent) reports "last keyboard or mouse input" to the Pi every minute or so, plus "going to sleep" when possible. The Pi turns that into screen on/off for the frame (section 6). If the Mac is asleep, off or out of the house (no reports arriving), the Pi treats that as idle, which is right: Alex isn't at his desk. A tap still wakes the frame.

The Mac is Alex's personal machine with no device management, so LaunchAgents, global Claude Code hooks and an MCP server pointing at the home network are all fine. **My call:** the hooks endpoint accepts reports from any machine that has the shared secret, so Claude Code sessions elsewhere can be added later just by installing the hooks there.

## 8. Security and privacy

- The frame holds no secrets. All tokens, links and credentials live on the Pi, outside the repo.
- The AiMOR vendor app must not reach its server while it is still installed: block `imsconnect.efercro.com` and port 7806, and disable the vendor updaters before the frame stays online (Wes's PF1007L guide, steps T3b, T3c and T8).
- If the no-card unlock route (T3c) is used, it leaves **root ADB with no key check on port 5555, open to the whole network**. Finish the lock-down in the same session.
- The Pi's dashboard API is reachable only on the home network in v1. The tasks tool should still require a shared secret, so other devices on the network can't add tasks.
- Firmware backups, dumps and diagnostics stay private and out of git (`backups/`, `diagnostics/`, `frames/`, as in Wes's repo).
- This repo will be pushed to Alex's GitHub. Secrets and personal identifiers (calendar links, tokens, serials, MAC addresses) must never be committed.

## 9. Order of work

This is a suggested order. The builder plans the details.

1. **Before the frame is unlocked:** build the dashboard on the Mac against mock data shaped like the real data, at 1280 × 800, targeting Chrome 106. Nothing here depends on hardware.
2. **Unlock the frame**, following Wes's [pf1007l-start-here.md](https://github.com/wesbos/photo-frame-dashboard/blob/main/docs/pf1007l-start-here.md): identify the firmware, try ADB over USB, then over the network, then T3c (no card), and only then the card routes. Back up, lock down AiMOR, upgrade WebView to 106, install the kiosk, and prove there's a way back to Android Settings before disabling anything. Every write needs Alex's approval. Check Wes's repo issues and PRs for this firmware first.
3. **Set up the Pi** headless and run the dashboard server.
4. **Connect the data sources** one at a time: calendar, weather, photos, plugs and speaker, Keep, tasks.
5. **Mac helpers:** Claude Code hooks, the activity helper, the tasks tool.
6. **Screen behaviour:** themes, dimming, off/on, wake on tap.
7. **Later:** v2 Cloudflare Tunnel; Pi-hole.

## 10. Later: Pi-hole on the same Pi

Agreed in principle. Pi-hole is light enough to share the 3A+. It must not clash with the dashboard's ports. Add it only after the Pi has been stable for a week or two, because once the router hands it out as DNS, a Pi problem takes the whole house offline. Pi-hole can also permanently block the AiMOR vendor domains network-wide. A USB Ethernet adapter is optional.

## 11. Left to the builder

- The detailed design of each full screen, in the approved visual language.
- The server framework, how the page gets live updates (polling or a push connection), storage choices, and the config file format.
- How the kiosk exposes backlight control to the page.
- The weather and reverse-geocoding providers.
- How the frame finds the Pi (DHCP reservation or `.local`).
- The travel-time estimate for "leave by".
- The unofficial route for Claude plan usage.

## 12. Decisions log

**Alex decided:** the frame and the PF1007L route; holding off on the microSD card until it's needed (the card has since been ordered with the Pi); a Pi 3A+ as the home server; v1 stays at home, with the tunnel in v2; calendars for Alex and family now, Vicky later; Keep two-way via the unofficial library, through a dedicated frame-only Gmail account; no router or location details in this public repo; photos from a Google Drive folder with sub-folders allowed, GPS place names, and no caption when data is missing; the Tapo plugs and Nest speaker; the Claude screen with usage meters (breakage accepted) and session status with "Needs you", no API spend; a tasks board, adding tasks via Claude Code in v1; the command-centre layout; calendar gridlines; Warm paper by day and Night after sunset; off at 23:00, on at 07:00; off after inactivity based on Mac activity; wake on tap; Pi-hole later.

**My calls (check these):** Python on the Pi; building from Wes's dashboard and kiosk code; serif headings in both themes; dimming from 22:00; a 30-minute idle default; a shared secret on the tasks tool; a Drive service account for photos; the frame on the legacy Wi-Fi network; the Claude hooks endpoint accepting any machine that has the secret; the weather location kept in private config.
