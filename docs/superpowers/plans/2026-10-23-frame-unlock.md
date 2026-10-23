# Frame Unlock and Kiosk Runbook (Plan 3)

**Goal:** Take the Humblestead 10.1" frame from its stock vendor software to a locked-down kiosk showing the dashboard full screen, without breaking it.

**What the unit is:** confirmed on 2026-10-22.
- Model **PF1007L**, firmware string ending **`PF1007L-FL-AIMOR-OS.0.20260519`**, AiMOR 6.0.78. It has never been online ("Had not updated").
- USB-C only and no usable battery, so the cable powers it.
- It boots with a power-button hold while USB power is connected.

**Route:** Wes Bos's repo documents a no-flash route, T3c, that has worked on this exact firmware from an Apple-silicon Mac. It is reported in `docs/pf1007l-macos-20260519-t3c-report.md`, #123 and #214 in wesbos/photo-frame-dashboard. A temporary DNS redirect makes the vendor app's own remote-command channel switch on root network ADB. We then make access persistent over USB, back up, lock down the vendor app, and install the kiosk. **No partition is flashed.**

**Kind of plan:** this is a hands-on runbook, not a code plan. Alex has his hands on the frame and the router; Claude runs the Mac-side commands. Every step marked **[APPROVAL]** changes the frame and needs Alex's explicit "yes" to that specific action, per Wes's rule 1. Read-only steps don't. Stop at the first mismatch (a hash, model string, size or offset) and report it. Never edit a guard to make it pass.

**Sources** are in the upstream repo, cloned locally for reference: `docs/pf1007l-start-here.md` (test sequence T1–T8), `docs/aimor-remote-root-shell.md`, `docs/pf1007l-20260410-network-adb.md` (the T3c procedure), `docs/allwinner-a33-pf1007l.md` (post-root: backup, launcher, WebView, kiosk), `docs/pf1007l-boot-fixes.md`, `dashboard/kiosk/README.md` and the macOS reports. **Re-check upstream issues and PRs for this firmware at the start of the session.**

## Prerequisites

- **A USB-A to USB-C cable that carries data.** Both cables tried on 2026-10-22 (and the box cable) were charge-only or blocked by the hub: the frame never enumerated, not even as stock `1f3a:1000`. A data-capable 20 cm cable arrives on 2026-10-23. Pass condition for using it: with the frame booted, `ioreg -p IOUSB -l | grep -i 'idVendor" = 7994'` shows the frame (vendor 0x1f3a).
- `adb` (Homebrew `android-platform-tools`, installed).
- The upstream repo up to date in a scratch clone, so its helper scripts `scripts/aimor-network-adb/{server.py,dns.py,test-*.py}` can be used.
- The home server running on the Mac (`uv run homehub`), with the Mac on a known LAN IP (a DHCP reservation on the router is recommended).
- About 2 hours with Alex present.

## Privacy

- Dumps, backups and per-frame records go only under git-ignored `backups/`, `diagnostics/` and `frames/`.
- The frame's MAC address, Frame ID, serials, LAN IPs and whole-eMMC hashes never go into committed files.
- Firmware strings and boot-image hashes are fine to commit and to contribute upstream.

---

## Phase A — Prepare (read-only, no frame changes)

1. Update the scratch upstream clone. Check `gh issue list` and `gh pr list` on wesbos/photo-frame-dashboard for anything new on `20260519`, T3c or macOS. If something contradicts this runbook, stop and discuss.
2. Run the upstream self-tests:
   - `python3 scripts/aimor-network-adb/test-protocol.py` and `test-dns.py`;
   - `server.py --dry-run`, which should give a 73-byte packet with `network_contact=false`.

   Check that nothing else is listening on UDP/TCP 53 or TCP 7806 (`lsof -nP -iUDP:53 -iTCP:53 -iTCP:7806`).
3. **Choose the DNS approach for the redirect.** If the router can only change DNS for the whole LAN (no per-device override), note that upstream's `dns.py` answers only allow-listed clients, which would leave every other device in the house without DNS during the window. **Use a full forwarder instead.** Run `dnsmasq` on the Mac (`brew install dnsmasq`; it's only started for the window), with `address=/imsconnect.efercro.com/<mac-ip>` and `server=<isp dns>`. It answers the frame's vendor lookups with the Mac and forwards everything else, so the household keeps working. Test it with `dig @<mac-ip> imsconnect.efercro.com` (should give the Mac) and `dig @<mac-ip> example.com` (should give the public address).
4. Check the Mac's firewall allows incoming TCP 7806 (server.py) and UDP 53 (dnsmasq) while they run. Upstream reports that Apple's `/usr/bin/python3` was allowed where Homebrew Python was blocked.

**Pass:** the self-tests pass, and the forwarder answers both lookups correctly.

## Phase B — USB check, T3 (read-only)

1. Connect the frame with the data cable, through the hub if needed. Boot it (hold power 5–8 s), and allow the accessory on the Mac.
2. Run `ioreg … idVendor 7994` and `adb devices -l`. Interpret per upstream T3:
   - `device` → go straight to Phase D;
   - `unauthorized` → accept the prompt on screen;
   - `1f3a:1000` with no ADB → continue to Phase C. This is expected on 20260519.
3. Record this in `frames/humblestead-1.md` (git-ignored): the firmware string, ports, USB IDs seen and the cable.

## Phase C — T3c: temporary root network ADB (controlled window)

The session takes about 15 minutes. Only the two **[APPROVAL]** steps change anything.

1. Start upstream `server.py --bind <mac-ip> --seconds 900`. The frame IP isn't known yet; get it from the first AiMOR connection or the router's lease table, then re-arm with `--frame-ip`. Then start dnsmasq.
2. **Router:** point the frame's DNS (or the LAN's, per `private/network.md`) at the Mac's IP. The window opens.
3. On the frame, join Wi-Fi. AiMOR connects to "imsconnect", which is now the Mac. If server.py wasn't armed for its IP yet, AiMOR shows "error code 002", which is harmless and retries. **Do not toggle Wi-Fi after the command is sent.**
4. **[APPROVAL] Send the single vendor command** `setprop service.adb.tcp.port 5555; stop adbd; start adbd` (server.py does this once, only to the frame's IP).
5. Run `adb connect <frame-ip>:5555` (`adb kill-server` first if macOS says "No route to host"). Identity checks:
   - `id` must be `uid=0`;
   - `getprop ro.build.display.id` must match the firmware;
   - `ro.hardware=sun8i`;
   - `ro.build.version.release=6.0.1`.

   **Stop on any mismatch.**
6. **[APPROVAL] Make USB ADB persistent** with `setprop persist.sys.usb.config mass_storage,adb`, straight away, because one unit lost Wi-Fi ADB after about a minute. Check that `sys.usb.state` is now `mass_storage,adb`. Undo is `setprop persist.sys.usb.config mass_storage`. **Do not** set `persist.adb.tcp.port`, which would leave key-less root ADB open on the LAN at every boot.
7. While still in the window, apply the **in-memory firewall** blocking vendor ports (7806, 10546–10550, 3478) on the frame. This is upstream's T8 step 2, and it lasts until reboot. **[APPROVAL]**
8. **Close the window.** The router goes back to DHCP DNS first, then stop dnsmasq and server.py. Devices pick up the normal DNS on their next DHCP renew; reconnecting the Mac's Wi-Fi speeds this up.

**Pass:** root ADB (uid 0) over Wi-Fi, `sys.usb.state=mass_storage,adb`, and the router restored.

## Phase D — Prove persistent USB access

1. Unplug the frame, wait 15 s, then replug it on the data cable and boot it. `adb devices -l` should list it as `device` (USB ID `1f3a:1002`), with `adb -d shell id` showing uid=0 and `sys.boot_completed=1`.
2. Repeat after a full power cut. Upstream had it survive a 15 s power cut and full power cycles on this firmware.

**Pass:** USB root ADB survives a cold boot. **Until this passes, do not disable AiMOR** (upstream lockout warning).

## Phase E — Backups (read-only on the frame)

Everything goes over USB into `backups/` (git-ignored). Follow upstream rule 2: exact byte counts, SHA-256 on both the frame side and the Mac side, gzip readback, a check for `0xCC` filler, and independent re-reads that match.

1. List the partitions: `ls -l /dev/block/by-name; cat /proc/partitions; cat /sys/block/mmcblk0/size`.
2. Back up the static partitions with two independent reads each, compared byte for byte: `bootloader`, `env`, `boot`, `misc`, `recovery` and `system`. Check the boot image at sector 172032 (31,028 sectors) against upstream's table: for 20260519 the prefix should be `9a6e2456`. **A mismatch is a stop condition.**
3. Back up the stock WebView tree (`/system/app/webview`) as a tar.
4. Take a full eMMC image in 512 MiB chunks with `/sbin/busybox dd`. Stock `dd` silently returns 0 bytes past 2 GiB on this board. **Check each chunk's byte count**, and compare a frame-side `busybox sha256sum` with the host for each chunk. Over USB this takes about an hour.
5. Record the sizes and hashes in `frames/humblestead-1.md` (private).

**Pass:** all static partitions have matching double reads, the boot hash matches the table, and every chunk's size and hash match.

## Phase F — Lock down the vendor app (T8)

1. **[APPROVAL]** Install Rootless Launcher 3.9.1 from F-Droid, pinned by SHA-256 `7fa44d560dc4577374d45176220de2c0b00a71e09d6d148cdea4e0a52d38404a`. Set it as Home.
2. **By hand on the panel**, Alex confirms that the launcher shows and that he can reach **Settings → Apps** from it. Screenshots over ADB don't count, because the panel can differ.
3. **[APPROVAL]** Run `pm disable` on `com.efercro.os.aimor`, `com.yhk.qeota` and `com.DeviceTest`. Check `enabled="2"` in `/data/system/users/0/package-restrictions.xml`, and wait for the write before rebooting.
4. Forget any factory or test Wi-Fi networks saved on the frame.
5. Power-cycle, then run `netstat -an | grep :7806`. **No output = pass.** Set Home again if the "Always" choice was cleared.

**Undo:** `pm enable` each package.

## Phase G — Modern browser engine (WebView 106)

**[APPROVAL] (writes `/system`).** Follow upstream `allwinner-a33-pf1007l.md` §6 exactly:
- Use the LineageOS WebView 106.0.5249.126 ARM APK, SHA-256 `e2edc1f89ec1608b169da9e7ffc037190b70c7825f0be29694f4cae719980580`, and extract every `armeabi-v7a` library.
- Stage it in `/data/local/tmp`.
- Remount `/system` read-write and build `/system/homehq-new-webview`.
- Read every staged file back and compare it.
- Move the stock tree to `/system/homehq-stock-webview` and the new one into place. Run each `mv` exactly once.
- Read back, `sync`, remount read-only, reboot.

**Verify:**
- `dumpsys package com.android.webview` shows `versionName=106.0.5249.126`;
- there's no `dlopen failed` in logcat;
- a test page renders.

Don't launch the kiosk before this reboot. **Undo** is in upstream §6.

## Phase H — Kiosk (Home HQ) showing the dashboard

1. Build `dashboard/kiosk` from the upstream repo. It needs JDK 17, Android build-tools 34 and platform android-34, installed via Homebrew `temurin@17` and `android-commandlinetools`, plus `sdkmanager`. **[APPROVAL]** `adb install`.
2. Set the URL to `http://<mac-ip>:8000/` for now (the Pi takes over on Monday): `adb shell am start -n com.wesbos.homehq/.MainActivity --es url http://<mac-ip>:8000/`.
3. Make it Home: `--ez home true`, then choose **Always** in the chooser. Android 6 has no `set-home-activity`.
4. Set the time zone and time:
   - `settings put global auto_time_zone 0`;
   - `setprop persist.sys.timezone Europe/London`;
   - make sure time comes from NTP.
5. **[APPROVAL]** Apply the upstream `pf1007l-boot-fixes` (`scripts/pf1007l-boot`). They cover the clock after a power cut, pinning one Wi-Fi MAC (needed before a DHCP reservation for the frame can work), no freeze at Wi-Fi start, and fast DHCP. Then add a **DHCP reservation for the frame** on the router.
6. Connect the frame to the home Wi-Fi permanently. Use a 2.4 GHz compatibility network if the main one is unreliable.

**Pass:** after a cold boot the frame shows the live dashboard by itself.

## Phase I — On-device checks (from plan 1 and the reviews)

Check each of these on the real panel:
- dim and off overlays, and that a tap wakes the frame without pressing anything underneath;
- tasks long-press and the add sheet;
- whether an on-screen keyboard appears for the shopping and task fields;
- nothing important sits in the bottom 64 px dead zone;
- the clock's thin strokes are legible across the room;
- photo slideshow memory: no stutter after an hour;
- WebView 106 renders the fonts.

Record the results privately. Turn any failures into dashboard follow-ups.

## Phase J — Contribute back (optional, later)

Draft a unit report for the upstream PF1007L doc using its report template: firmware string, route, cable lesson, what worked and what failed. Also confirm the Amazon **UK** listing ships the PF1007L. **Show Alex the diff before any PR**, because it goes out under his account. Remove MACs, serials, IPs and whole-disk hashes.

## Out of scope (v2)

- Real backlight off (needs a kiosk JS bridge or a root helper).
- Moving the kiosk URL to the Pi. That's one `am start --es url http://<pi-ip>/`, done in plan 2 Task 13.
- LAN access control.
