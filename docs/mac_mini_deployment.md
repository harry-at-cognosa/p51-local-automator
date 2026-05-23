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

### 3a. The nvm/PATH gotcha

The MCP servers are spawned by the backend via `npx`, so `node`/`npx` must be
on the PATH of the launchd process. **launchd does not source `~/.zshrc`**, so
the nvm shims are not active. You must put the node bin directory on the
LaunchAgent's PATH explicitly.

Find your node bin dir:

```bash
source ~/.nvm/nvm.sh && nvm use >/dev/null 2>&1 && dirname "$(which node)"
# e.g. /Users/harryatmac/.nvm/versions/node/v25.4.0/bin
```

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
> `127.0.0.1`. The `.nvmrc` version (currently `v25.4.0`) is baked into the
> PATH above — update it if you bump the pinned node version.

### 3c. Load it

```bash
mkdir -p /Users/harryatmac/p51-local-automator/logs
launchctl load -w ~/Library/LaunchAgents/net.cognosa.p51.plist
```

`-w` marks it enabled persistently. To stop/reload after editing the plist:

```bash
launchctl unload ~/Library/LaunchAgents/net.cognosa.p51.plist
launchctl load   -w ~/Library/LaunchAgents/net.cognosa.p51.plist
```

(On newer macOS you may prefer the `launchctl bootstrap gui/$(id -u) <plist>`
/ `bootout` syntax; `load`/`unload` still work.)

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

## 6. Automation permissions (one-time, interactive)

The first time the backend's MCP subprocess drives Mail.app or Calendar.app,
macOS shows an **Automation** permission prompt. If the process is running
headless under launchd, the prompt may appear at the next GUI interaction or
the AppleScript call silently fails until granted.

Grant it once, interactively, while logged in:

- System Settings → Privacy & Security → **Automation** → enable the entries
  that let the p51 process (or its parent, e.g., the terminal/launchd context)
  control **Mail** and **Calendar**.
- Also check **Privacy & Security → Full Disk Access** if Mail database reads
  are blocked.

The cleanest way to trigger the prompts is to run one Type 1 (email) and one
Type 3 (calendar) workflow manually via the UI right after first install, while
sitting at the machine, and approve each prompt as it appears.

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
