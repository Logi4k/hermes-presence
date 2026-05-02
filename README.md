# Hermes Presence

<!-- Badges -->
![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![PyPI Version](https://img.shields.io/badge/pypi-v3.1.0-orange)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows%20%7C%20WSL2-lightgrey)

**Cross-platform Discord Rich Presence for Hermes Agent — one-command install, all OSes supported.**

Monitors running Hermes sessions and displays live activity in Discord's "Playing" status area. Works on Linux, macOS, Windows, and WSL2 with zero configuration after install.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration Reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Features

### Core Presence
- **Multi-pipe Discord connections** — connects to all 4 Discord IPC pipes (stable + canary) simultaneously; auto-reconnects on pipe close
- **Cross-platform** — Linux (systemd), macOS (launchd), Windows (Task Scheduler), WSL2 (bridged via PowerShell)
- **WSL bridge** — hook running in WSL automatically mirrors state to Windows AppData so the Windows-side monitor can push to Discord without crossing the filesystem boundary

### Display Richness
- **Tool-specific icons** — every Hermes tool maps to a named Discord asset (`status_working`, `status_researching`, `status_monitoring`, `status_active`, `status_error`, `status_standby`)
- **Model + provider tracking** — displays current model (e.g. "DeepSeek V4 Pro") and provider in the presence detail line
- **Subagent party size** — when spawning sub-agents via `delegate_task`, Discord shows party size = subagents + 1
- **Per-tool elapsed timer** — Discord "elapsed time" reflects when the current tool started, not session start
- **Error state detection** — tool failures surface as a distinct `error` state with the error message in the detail field
- **Cron / orchestrator detection** — environment variable markers (`HERMES_CRON_JOB_ID`, `HERMES_ORCHESTRATOR`) switch to monitoring icons and labels
- **Kanban phase tracking** — external systems can signal current phase (e.g. plan/execute/review) via the `on_kanban_phase` hook

### Session Tracking
- **Session tracking** — session ID, start time, and total duration exposed in the state file
- **Cost tracking** — cumulative session cost in USD written by `set_cost()` / `add_cost()`
- **Files modified counter** — incremented on `write_file`, `patch`, and `skill_manage` tool completions
- **Tool call counter** — total tool calls per session

### Profiles
- **Named profiles** — `hermes-presence config set profile <name>`; the `main` and `clinical-monitor` profiles are examples
- **Profile inheritance** — all session fields tagged with source profile name

### Reliability
- **Watchdog resilience** — monitor polls state file every 5 s (configurable); if the file disappears it clears Discord presence cleanly
- **Atomic writes** — writer uses write-to-temp + rename to avoid corrupted JSON if interrupted
- **Graceful degradation** — if Discord is not running the monitor waits silently, no crash
- **atexit session summary** — on shutdown, writes a final `offline` state before exiting

---

## Architecture

```
Hermes Agent (Linux / macOS / WSL2)
│
│  hermes_presence.hook
│  on_session_start / on_tool_start / on_tool_end / ...
│
│  PresenceWriter
│  writes to ~/.hermes/state/presence.json  (atomic write)
│
├── WSL detected? ──► mirrors to %APPDATA%/hermes_presence.json
│
└─────────────────────────────── Windows AppData ────────────────────┐
                                                                        │
                                               hermes_presence_monitor.py │
                                               (Windows-side, auto-start)  │
                                               reads AppData mirror file   │
                                               polls every 5 s             │
                                               UnifiedMonitor               │
                                               connects pipes 0-3           │
                                               pushes to Discord ───────────┘
```

**Data flow**

1. Hermes fires an event (tool start, tool end, thinking, etc.)
2. `hermes_presence.hook` calls `PresenceWriter` methods
3. `PresenceWriter` atomically writes `~/.hermes/state/presence.json`
4. If running under WSL, the writer simultaneously mirrors the file to `C:\Users\<user>\AppData\Roaming\hermes_presence.json`
5. The platform-specific monitor (`UnifiedMonitor` on Linux/macOS, `hermes_presence_monitor.py` on Windows/WSL2) polls the state file
6. On change, the monitor calls `pypresence Presence.update()` on all available Discord IPC pipes

**Platform auto-start**

| Platform | Mechanism |
|---|---|
| Linux | `systemd` user unit (`~/.config/systemd/user/hermes-presence.service`) |
| macOS | `launchd` plist (stub — platform module present) |
| Windows | Windows Task Scheduler (`HermesPresence` task at logon) + `shell:startup` .bat fallback |
| WSL2 | Same as Windows — monitor always runs on the Windows host, not inside WSL |

---

## Installation

### Prerequisites

- Python **3.9+**
- [pypresence](https://pypi.org/project/pypresence/) >= 4.3.0
- A **Discord Application** with Rich Presence enabled and art assets uploaded (see below)

### Discord App Setup (one-time)

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** — name it "Hermes AI" (or any name you prefer)
3. Copy the **Application ID** (the long number on the General Information page)
4. Navigate to **Rich Presence > Art Assets**
5. Upload the 8 PNG images from the `assets/` directory in this repo, naming them exactly:

```
hermes_logo        status_active       status_error
status_idle        status_monitoring   status_researching
status_standby     status_working
```

All assets should be 512x512 px or smaller (Discord limit: 512KB each).

### Install Hermes Presence

```bash
# Install from GitHub
pip install git+https://github.com/Logi4k/hermes-presence.git

# Run the one-command installer (prompts for Discord Client ID)
hermes-presence install
```

The installer will:
- Ask for your Discord Application Client ID (or pass it directly):
  ```bash
  hermes-presence install --client-id YOUR_CLIENT_ID
  ```
- Detect your OS and set up platform-specific auto-start
- Start the monitor

### Reinstall / Force

```bash
hermes-presence install --force --client-id YOUR_CLIENT_ID
```

---

## Usage

```bash
hermes-presence install    # Full one-command setup
hermes-presence status     # Show current state and monitor status
hermes-presence config     # Show current configuration
hermes-presence config set discord.client_id YOUR_CLIENT_ID  # Set client ID
hermes-presence config set display.show_provider false       # Hide provider
hermes-presence disable    # Temporarily hide presence
hermes-presence enable     # Re-enable after disable
hermes-presence run        # Run monitor in foreground (debug mode)
hermes-presence uninstall  # Remove auto-start and config
```

### Programmatic Integration

```python
from hermes_presence import auto_setup, get_writer

# In your Hermes agent startup:
writer = auto_setup(agent=my_agent)
# auto_setup() reads HERMES_MODEL / HERMES_PROVIDER env vars automatically

# During tool execution:
writer.tool_call("terminal", {"command": "npm run build"})
writer.thinking()          # model streaming
writer.idle()              # tool done, waiting

# Error handling:
writer.error("Connection refused on port 3000")

# Session metadata:
writer.set_cost(0.042)     # cumulative USD cost
writer.file_modified()     # increment files-modified counter

# Shutdown:
writer.shutdown()
```

### Hook Callbacks (for Hermes plugin system)

```python
from hermes_presence.hook import _load_hermes_hook

hooks = _load_hermes_hook()
# Returns: {
#   "on_session_start": fn,
#   "on_tool_start": fn,
#   "on_tool_end": fn,
#   "on_tool_error": fn,
#   "on_thinking": fn,
#   "on_model_info": fn,
#   "on_subagent_change": fn,
#   "on_kanban_phase": fn,
#   "on_session_end": fn,
#   "on_shutdown": fn,
# }
```

---

## Configuration Reference

Config file: `~/.hermes/presence.toml`

All settings can also be overridden by environment variables (env vars take highest priority).

```toml
[discord]
client_id = ""                    # Discord Application ID (required)

[display]
show_model    = true             # Show model name in presence
show_provider = true             # Show provider name in presence
idle_timeout  = 10               # Seconds before idle state is pushed
large_image   = "hermes_logo"    # Large Discord asset name
large_text    = "Hermes Agent"   # Hover text for large image

[windows]
force_windows_ipc   = false      # Force Windows IPC even from WSL
state_file_mirror   = true       # Mirror state to Windows AppData on WSL

[tools]
exclude = []                      # Tool names to hide from presence

[buttons]
hermes_github    = true           # Show "Hermes Agent" button linking to GitHub
nexus_dashboard  = false          # Show "Nexus Dashboard" button (localhost:5173)
custom_urls = []                 # List of {label, url} dicts (max 2 buttons total)

[advanced]
poll_interval       = 5         # Seconds between state file polls
pipe_connect_retry   = 3         # Seconds to wait when no Discord pipe available
```

### Environment Variable Overrides

| Variable | Equivalent |
|---|---|
| `HERMES_DISCORD_CLIENT_ID` | `discord.client_id` |
| `HERMES_PRESENCE_STATE` | state file path |
| `HERMES_MODEL` | model name (auto-populated by Hermes) |
| `HERMES_PROVIDER` | provider name (auto-populated by Hermes) |
| `HERMES_PROFILE` | profile name (default: `main`) |
| `HERMES_CRON_JOB_ID` | cron job marker (any non-empty value) |
| `HERMES_ORCHESTRATOR=1` | orchestrator mode marker |

---

## Troubleshooting

### Discord shows "Playing a game" but no presence updates

1. **Verify Client ID is set correctly**:
   ```bash
   hermes-presence config
   # Should show client_id = [SET]
   ```

2. **Check the monitor is running**:
   ```bash
   hermes-presence status
   # Running: Yes / No
   ```

3. **Run in foreground to see debug output**:
   ```bash
   hermes-presence run
   # Watch for [update -> pipes 0,1,2...] lines
   ```

4. **Verify Discord Rich Presence is enabled**:
   - Discord Settings > Activity Status > "Display current activity as a status message" must be ON

### WSL2: Presence updates on Windows side stop after a while

- The monitor runs on the **Windows host**, not inside WSL. If the Windows Python process dies, the WSL mirror continues writing but nothing pushes to Discord.
- Re-run: `hermes-presence install --force`

### No Discord pipes found / "Discord does not appear to be running"

- Ensure Discord is fully launched (not minimized to tray only — open the main window)
- Try restarting Discord: right-click tray icon > Quit Discord, then relaunch
- Canary and stable Discord can run simultaneously — the monitor connects to all pipes

### Config changes not taking effect

- The monitor reads the config file at startup only. Restart it:
  ```bash
  hermes-presence install --force  # reinstalls + restarts
  # or on Linux:
  systemctl --user restart hermes-presence
  ```

### Permission denied on systemd unit (Linux)

```bash
systemctl --user daemon-reload
systemctl --user enable hermes-presence
systemctl --user start hermes-presence
```

### State file location

- **Linux/macOS/WSL hook side**: `~/.hermes/state/presence.json`
- **Windows monitor side**: `%APPDATA%\hermes_presence.json`

To check what the monitor is seeing from the Windows side:

```powershell
Get-Content $env:APPDATA/hermes_presence.json | python -m json.tool
```

### Presence shows "Waiting for input" even when Hermes is active

- The presence is driven by events from the Hermes hook. If Hermes was not started with the hook wired up, the state file stays in idle.
- Ensure `auto_setup()` or `setup_presence()` is called in your Hermes startup code.

---

## Contributing

Contributions are welcome. Please follow the existing code style and ensure all tests pass before opening a PR.

### Development Setup

```bash
git clone https://github.com/Logi4k/hermes-presence.git
cd hermes-presence

# Create venv
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS/WSL
# .venv\Scripts\activate    # Windows

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

### Adding New Tool Icons

Edit `TOOL_ICONS` in `hermes_presence/writer.py` and the `TOOL_ICON_MAP` in `hermes_presence/monitor.py`:

```python
TOOL_ICONS = {
    "my_new_tool": {
        "detail": "Doing something",   # f-string template (params injected)
        "large_image": "status_active", # Discord asset name
    },
}
```

Upload the corresponding asset to your Discord application's Rich Presence Art Assets page.

### Adding Platform Support

1. Create a new module in `hermes_presence/platforms/` inheriting from `PlatformLauncher`
2. Implement: `install()`, `uninstall()`, `is_installed()`, `start()`, `stop()`, `status()`
3. Register it in `hermes_presence/installer.py`'s `_install_platform()` and `hermes_presence/app.py`'s `_cmd_status()`

---

## License

MIT License — see [LICENSE](LICENSE) file.

---

## Links

- **Repository**: [github.com/Logi4k/hermes-presence](https://github.com/Logi4k/hermes-presence)
- **PyPI**: [pypi.org/project/hermes-presence](https://pypi.org/project/hermes-presence) (pending)
- **Hermes Agent**: [github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- **pypresence**: [pypi.org/project/pypresence](https://pypi.org/project/pypresence)
