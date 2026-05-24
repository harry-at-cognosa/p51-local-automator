# Mac Mini Deployment — Unattended Scheduled Runs

**Goal:** Run p51-local-automator on a Mac Mini as an always-on server so the
in-process scheduler reliably fires daily workflows (e.g., a 6–7 AM window)
with no human present.

This document covers the four things that have to be true for that to work,
plus power-failure recovery, automation permissions, and verification. Read
the **Why it matters** notes — several of these are load-bearing, not optional.

---

## The core problem

The scheduler is **APScheduler running in-process** inside the uvicorn/FastAPI
backend. For a job to fire at 6 AM, all of the following must hold at 6 AM:

1. The Mac is **awake** (not asleep).
2. The **uvicorn process is running** (survived crashes, logouts, reboots).
3. The **user is logged into a GUI session** (Apple Mail / Calendar workflows
   drive those apps via AppleScript automation, which needs an Aqua session).
4. The **scheduler is started** (it auto-starts on boot when
   `AUTO_START_SCHEDULER=true`, the default).

Miss any one and the job silently does not run. Critically, **there is no
catch-up for missed fires** beyond a 5-minute grace window — a slept-through
or process-down 6 AM slot is skipped entirely until the next day. So these
settings are about guaranteeing the four conditions, not nice-to-haves.

> Throughout, the example paths assume the repo is at
> `/Users/harryatmac/p51-local-automator` and the account is `harryatmac`.
> **Adjust both for the actual Mac Mini user and clone location.**

---

## 1. Prevent system sleep (display sleep is fine)

The display can turn off to save the panel — that's *display sleep* and is
harmless. What you must prevent is *system sleep*, which pauses the APScheduler
timer.

```bash
sudo pmset -c sleep 0          # never system-sleep on AC power
sudo pmset -c displaysleep 10  # screen may turn off after 10 min (cosmetic only)
sudo pmset -c disksleep 0      # keep disks spun up
```

`-c` = "on AC power / charger," which is always the case for a Mac Mini.

**GUI equivalent:** System Settings → Energy → enable *"Prevent automatic
sleeping when the display is off."*

**Verify:**

```bash
pmset -g
# Look for: sleep 0, and 'SleepDisabled' behavior. displaysleep can be nonzero.
```

**Why `caffeinate` is the wrong tool here:** `caffeinate -s` works, but it only
holds sleep off while that specific process (and its terminal/parent) stays
alive. Close the terminal, log out, or reboot, and the assertion drops. `pmset`
settings persist across reboots and aren't tied to a session. Use `caffeinate`
only for ad-hoc "keep it awake while I run this one thing" cases, never for a
permanent server.

---

## 2. Keep the user logged in + auto-login on boot

The Apple Mail and Apple Calendar workflows run through MCP servers that drive
Mail.app and Calendar.app via AppleScript. AppleScript GUI automation requires
a **live GUI login session** — it cannot run from a headless background daemon.

So the server account must stay logged in, and must log back in automatically
after a reboot:

- **System Settings → Users & Groups → Automatic login → [the server account].**
  After a reboot or power restoration, the Mac returns to that user's logged-in
  desktop with no password prompt.
- Do **not** log out. The screen may lock or turn off (the session stays
  active), but logging out tears down the GUI session and breaks the Apple
  automation.

### FileVault caveat (important)

If **FileVault** disk encryption is enabled, automatic login is effectively
impossible: macOS demands the disk-unlock password at the boot screen *before*
the OS — and therefore before any auto-login — can proceed. For a truly
unattended server you have two choices:

- **Disable FileVault** (System Settings → Privacy & Security → FileVault →
  Turn Off). Trades at-rest disk encryption for unattended reboots. Reasonable
  on a physically secured server; not on a stealable laptop.
- **Keep FileVault on** and accept that every reboot (including after a power
  blackout) needs a human to type the unlock password before the scheduler
  comes back.

Pick deliberately based on the physical security of the Mac Mini.

### Screen lock

A locked screen does **not** log you out, so background AppleScript generally
still works. But to avoid surprises with GUI automation, consider relaxing the
lock:

- System Settings → Lock Screen → "Require password after screen saver begins
  or display is turned off" → set to a long delay or **Never** (server context).

---

## 3. Run the backend as a LaunchAgent (not uvicorn in a terminal)

A terminal-launched `uvicorn` dies when the terminal closes and won't restart
after a crash or reboot. A **LaunchAgent** starts the backend on login,
respawns it on crash (`KeepAlive`), and writes logs to a file.

Use a **LaunchAgent** (runs in the user's GUI session) rather than a
LaunchDaemon (runs headless at boot) — because of the Apple automation
requirement from §2.

### 3a. The node/PATH gotcha

The MCP servers are spawned by the backend via `npx`, so `node`/`npx` must be
on the PATH of the launchd process. **launchd does not source `~/.zshrc` or
`~/.zprofile`**, so whatever makes node available in your interactive shell —
nvm shims, Homebrew, an official-installer entry — is *not* active here. You
must put the node bin directory on the LaunchAgent's PATH explicitly.

Find your node bin dir (works regardless of how node was installed):

```bash
dirname "$(command -v node)"
# Homebrew install →  /opt/homebrew/bin
# nvm install      →  /Users/<user>/.nvm/versions/node/v25.4.0/bin
```

> If node came from **Homebrew** (`/opt/homebrew/bin`), that directory is
> already in the example PATH below, so you don't need a separate node segment —
> just delete the `~/.nvm/...` entry from it. If node came from **nvm**, keep
> the versioned `.nvm/.../bin` path and update it whenever you bump the pinned
> node version. (There is no `~/.nvm/nvm.sh` on a Homebrew-node machine — that's
> expected, not a missed step.)

### 3b. The plist

Create `~/Library/LaunchAgents/net.cognosa.p51.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>net.cognosa.p51</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/harryatmac/p51-local-automator/venv/bin/python3</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>backend.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/harryatmac/p51-local-automator</string>

    <key>EnvironmentVariables</key>
    <dict>
        <!-- node bin (for npx/MCP) + homebrew + venv + system paths -->
        <key>PATH</key>
        <string>/Users/harryatmac/.nvm/versions/node/v25.4.0/bin:/opt/homebrew/bin:/Users/harryatmac/p51-local-automator/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <!-- Don't hammer-respawn if it crashes on startup -->
    <key>ThrottleInterval</key>
    <integer>15</integer>

    <key>StandardOutPath</key>
    <string>/Users/harryatmac/p51-local-automator/logs/uvicorn.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/harryatmac/p51-local-automator/logs/uvicorn.err.log</string>
</dict>
</plist>
```

> `--host 0.0.0.0` exposes the backend on the LAN (so other machines on the
> network can reach it). If the Mac Mini should serve only itself, use
> `127.0.0.1`. The example PATH above shows the **nvm** node segment
> (`.nvm/.../v25.4.0/bin`); on a **Homebrew** node install that segment is
> unnecessary because `/opt/homebrew/bin` (already present) holds node — see
> §3a. Either way, keep the node path in sync with your actual install.

### 3c. Load it

```bash
mkdir -p /Users/harryatmac/p51-local-automator/logs
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.cognosa.p51.plist
launchctl list | grep p51    # expect: <PID>  0  net.cognosa.p51
```

A per-user LaunchAgent is bootstrapped into **your own GUI domain**
(`gui/$(id -u)`) — run it **as yourself, never with `sudo`**. `sudo` runs as
root, which can't reach your GUI session's domain and fails with
`Bootstrap failed: 5: Input/output error` (launchctl will even suggest re-running
as root "for richer errors" — ignore that, root is the wrong direction here).

To reload after editing the plist:

```bash
# If you only changed runtime behavior, a restart of the running job is enough:
launchctl kickstart -k gui/$(id -u)/net.cognosa.p51

# If you changed load-time keys (ProgramArguments, PATH, file paths), re-bootstrap:
launchctl bootout   gui/$(id -u)/net.cognosa.p51
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.cognosa.p51.plist
```

> **Gotcha (learned the hard way):** the legacy `launchctl load -w` / `unload`
> commands **silently no-op** when a job with that label is already registered —
> `load` says nothing and never re-reads your edited plist, so you keep running
> the *stale* definition. Symptom: `launchctl list | grep p51` shows the job
> stuck (PID `-`, nonzero exit) and a fresh `bootout`/`bootstrap` returns
> `5: Input/output error` because the label is still registered. Clear it with
> the legacy remover, confirm it's gone, then bootstrap fresh:
>
> ```bash
> launchctl remove net.cognosa.p51            # clears a legacy-loaded registration
> launchctl list | grep p51                   # must print NOTHING before continuing
> launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.cognosa.p51.plist
> ```

### 3d. Verify it's running

```bash
launchctl list | grep p51        # shows the job + last exit code
curl -fsS http://localhost:8000/docs >/dev/null && echo "backend up"
tail -f /Users/harryatmac/p51-local-automator/logs/uvicorn.err.log
# Look for: app_version, scheduler_autostart
```

---

## 4. Recover from power failure

So a blackout self-heals (reboot → auto-login → LaunchAgent → scheduler):

```bash
sudo pmset -c autorestart 1
```

**GUI equivalent:** System Settings → Energy → *"Start up automatically after a
power failure."*

Combined with §2's auto-login and §3's LaunchAgent, the full chain after a
blackout is: power returns → Mac boots → server account auto-logs-in → GUI
session starts → LaunchAgent launches uvicorn → `AUTO_START_SCHEDULER=true`
starts the scheduler. No human needed (unless FileVault is on — see §2).

---

## 5. Optional belt-and-suspenders: scheduled wake

Even with sleep disabled, you can *guarantee* the box is awake before the
morning window by scheduling a daily wake:

```bash
# Wake (or power on) at 5:55 AM every day, ahead of a 6 AM job window
sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00
```

Check / clear:

```bash
pmset -g sched          # show scheduled events
sudo pmset repeat cancel
```

This is insurance against a misconfigured sleep setting — if something does put
the Mac to sleep, it wakes itself before 6 AM.

---

## 6. Automation permissions (one-time, interactive) — Apple Mail/Calendar only

This applies **only** to workflows whose `service` is `apple_mail` or
`apple_calendar` — they drive Mail.app / Calendar.app via AppleScript, which
macOS gates behind an **Automation** permission. Workflows on `gmail` or
`google_calendar` talk to Google over HTTPS with OAuth and need **no** TCC
permission at all (only a valid OAuth token).

**Who the grant is attributed to.** macOS ties an Automation grant to the
*process that sends the Apple events*. Under the LaunchAgent that's the
backend's **python** interpreter — NOT Terminal. So a grant that shows up under
"Terminal" (from running something in a shell) does **not** cover the scheduled
run; you need it under **python**. In System Settings → Privacy & Security →
**Automation**, grants are grouped by the requesting app — expand the **python**
entry and you'll find the per-target toggles for **Mail** and **Calendar**.
(This is why a grant can be "not where you expected" but the workflow still
runs: it's filed under python, not the app you were looking at.)

**The catch with 6 AM:** an Automation prompt can only be answered by a human at
the keyboard. If the grant isn't already established when the scheduler fires
unattended, the AppleScript fails — usually *silently* (look for
`errAEEventNotPermitted` / `-1743` in `logs/uvicorn.err.log`, or a digest that
comes back empty).

**So establish the grant the right way, once:** while sitting at the machine,
run one `apple_mail` (Type 1) and one `apple_calendar` (Type 3) workflow **from
the web UI at `:8000/app`** — that UI is served by the launchd backend, so the
prompt is for the *same python* that fires at 6 AM. Approve each. The grant
persists, and every scheduled run thereafter works with no one present.
(Triggering the workflow from a Terminal instead grants Terminal, not the
launchd python — the classic reason Apple automation "works when I test it but
not on the schedule.")

- Also check **Privacy & Security → Full Disk Access** if Mail *database* reads
  are blocked.
- Grants can be wiped by a macOS update or by re-signing/replacing the python
  binary; afterward the next unattended run fails silently until you re-approve.
  Re-run the manual UI test after any such change.

---

## 7. Verification checklist (do this once, then trust it)

1. `pmset -g` shows `sleep 0` and `autorestart 1`.
2. `launchctl list | grep p51` shows the job with exit code `0`.
3. `curl -fsS http://localhost:8000/docs` returns 200.
4. Dashboard → Scheduler tile reads **On** (auto-started).
5. Schedule a one-time workflow ~3 minutes out; confirm it fires (run appears
   in Run History, badge goes Active → Running → Completed).
6. **The real test:** schedule something for tomorrow 6 AM, leave the Mac
   alone overnight (lid/peripherals as they'll normally be), and confirm the
   run appears in the morning.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Scheduler tile reads "Off" after reboot | `AUTO_START_SCHEDULER` not true, or backend didn't start | Check `.env`; check `launchctl list \| grep p51` and the err log |
| Job didn't fire overnight | Mac slept | `pmset -g` → confirm `sleep 0`; add the §5 scheduled wake |
| Job didn't fire, Mac was awake | uvicorn wasn't running | Check LaunchAgent loaded + err log for a crash loop |
| Email/calendar workflows fail but SQL/data ones work | No GUI session, or Automation perms missing | Confirm auto-login + logged-in session; grant Automation perms (§6) |
| `npx`/MCP "command not found" in logs | launchd PATH lacks node | Fix the `PATH` in the plist EnvironmentVariables (§3a) |
| Nothing comes back after a blackout | FileVault prompting for unlock at boot | Disable FileVault, or accept manual unlock (§2 caveat) |

---

## Summary — the minimum durable setup

```bash
# 1. Power
sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c autorestart 1
sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00   # optional insurance

# 2. Auto-login: System Settings → Users & Groups (GUI; mind FileVault)

# 3. Backend as a service
mkdir -p ~/p51-local-automator/logs
# ...create ~/Library/LaunchAgents/net.cognosa.p51.plist (see §3b)...
launchctl load -w ~/Library/LaunchAgents/net.cognosa.p51.plist

# 4. Grant Automation perms by running one email + one calendar workflow (§6)
```

Get those right and a 6 AM daily job fires while you're asleep.
