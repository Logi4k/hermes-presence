# Hermes Presence v3.0 — Architecture

## Overview

Production-grade cross-platform Discord Rich Presence for Hermes Agent.
Global-release ready. One-command install, all platforms supported, user configurable.

## Target Project Structure

```
hermes-presence/
├── hermes_presence/
│   ├── __init__.py              # Package init, version exports
│   ├── writer.py                # State file writer (Hermes side hook)
│   ├── hook.py                  # Auto-setup + WSL detect + callback chaining
│   ├── monitor.py               # UNIFIED cross-platform Discord RPC monitor
│   ├── config.py                # Config file read/write (~/.hermes/presence.toml)
│   ├── installer.py             # One-command installer (platform detection)
│   ├── app.py                   # Entry point: CLI + monitor launch
│   └── platforms/
│       ├── __init__.py
│       ├── base.py              # Abstract base class for platform launchers
│       ├── linux.py             # systemd user unit template + install
│       ├── macos.py             # launchd plist template + install
│       └── windows.py           # Scheduled Task + .bat startup + %APPDATA% copy
├── scripts/
│   └── run_presence.py          # Quick run script for Windows
├── assets/
│   ├── hermes_logo.png
│   ├── status_active.png
│   ├── status_idle.png
│   ├── status_error.png
│   ├── status_monitoring.png
│   ├── status_researching.png
│   ├── status_standby.png
│   └── status_working.png
├── RunHermesPresence.ps1        # [LEGACY] PowerShell launcher
├── RunHermesPresence.bat        # [LEGACY] Batch launcher
├── start_presence.bat           # [LEGACY]
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
└── LICENSE
```

## Module Design

### config.py — Configuration System

File: `~/.hermes/presence.toml`

```toml
[discord]
client_id = ""                    # REQUIRED — set by user

[display]
show_model = true                 # "Working · DeepSeek V4 Pro"
show_provider = true              # "...via OpenRouter"
idle_timeout = 10                 # Seconds before switching to idle
large_image = "hermes_logo"       # Discord art asset name
large_text = "Hermes Agent"       # Hover text

[windows]
# Force Windows-style IPC — auto-detected, override for WSL2
force_windows_ipc = false
state_file_mirror = true          # Mirror state to %APPDATA%

[tools]
exclude = []                      # Tools to never show in Discord
# Example: exclude = ["memory", "read_file"]

[buttons]
hermes_github = true              # Show Hermes Agent GitHub button
nexus_dashboard = false           # Show Nexus Dashboard button
custom_urls = []                  # Extra button URLs

[advanced]
poll_interval = 5                 # State file poll interval (seconds)
pipe_connect_retry = 3            # Seconds between pipe reconnect attempts
```

### monitor.py — Unified Monitor

- Single codebase, all platforms
- Auto-detects OS and IPC mechanism:
  - **Linux/macOS:** pypresence connects via Unix socket at `$XDG_RUNTIME_DIR/discord-ipc-*`
  - **Windows:** pypresence connects via Windows named pipes
  - **WSL2:** Reads from `%APPDATA%/hermes_presence.json` mirror (needs Windows-side runner)
- Features:
  - Multi-pipe connection (stable + canary)
  - Auto-reconnect on pipe drop with 2s cooldown
  - Graceful degradation (no crash if Discord not running)
  - Unicode-safe console output
  - Tool-specific icons with prefix matching
  - Sub-agent party size tracking
  - Per-tool timer (resets each tool call)
  - Model + provider display in state line
  - Configurable idle timeout
  - Tool exclude filter
  - Error state on tool failure
  - Profiles: default, research, custom (reads from state file's `profile` field)

### installer.py — One-Command Installer

```
$ hermes-presence install
```

Flow:
1. Detect OS (Linux/macOS/Windows/WSL2)
2. Check dependencies (pypresence installed?)
3. Walk through Discord App ID setup:
   - Open browser to discord.com/developers (optional)
   - Prompt for Client ID
   - Save to `~/.hermes/presence.toml`
4. Platform-specific launcher setup:
   - **Linux:** Create `~/.config/systemd/user/hermes-presence.service`, enable
   - **macOS:** Create `~/Library/LaunchAgents/com.hermes.presence.plist`, load
   - **Windows:** Create Scheduled Task (TR2, AtLogon), copy .bat to `shell:startup`
   - **WSL2:** Copy monitor to `%APPDATA%`, create Scheduled Task on Windows side
5. Upload rich presence art assets to Discord (instructions + check)
6. Start the monitor
7. Verify connection

### app.py — CLI Entry Point

```
$ hermes-presence status       # Show current connection state
$ hermes-presence enable       # Re-enable if disabled
$ hermes-presence disable      # Disable temporarily (creates marker file)
$ hermes-presence config       # Read current config
$ hermes-presence config set discord.client_id 12345...
$ hermes-presence install      # Full setup
$ hermes-presence uninstall    # Remove scheduled task/unit, clean config
$ hermes-presence run          # Run monitor in foreground (debug)
$ hermes-presence --version    # Show version
```

### State File Contract (v3)

Adds new fields. Backward-compatible.

```json
{
  "version": 3,
  "timestamp": "2026-05-02T00:00:00Z",
  "profile": "default",
  "session": {
    "id": "session-abc12345",
    "source": "cli",
    "started_at": "2026-05-02T00:00:00Z",
    "model": "deepseek-v4-pro",
    "provider": "deepseek",
    "tool_calls_count": 42,
    "subagent_count": 0,
    "files_modified": 5,
    "cost_usd": 0.0423
  },
  "activity": {
    "state": "working",
    "detail": "$ pytest tests/",
    "tool": "terminal",
    "idle_seconds": 0,
    "tool_started_at": "2026-05-02T00:05:00Z",
    "error_msg": null,
    "is_error": false
  },
  "orchestrator": {
    "active_agents": 0,
    "agent_names": []
  },
  "cron": {
    "active_jobs": 0,
    "last_job": null
  }
}
```

## Tier Implementation Map

### Tier 1 — Blockers (Files to create/modify)

| Feature | Files |
|---------|-------|
| 1.1 Installer | `installer.py`, `platforms/*.py`, `app.py` |
| 1.2 Cross-platform | `monitor.py` (unified), removes need for separate Windows/Linux scripts |
| 1.3 User config | `config.py`, `~/.hermes/presence.toml` |
| 1.4 Config file | `config.py` |

### Tier 2 — QOL

| Feature | Files |
|---------|-------|
| 2.5 Model display | `monitor.py` (enhance _format_model_label), `writer.py` (add to state) |
| 2.6 Streaming/thinking | `writer.py`, `hook.py` (trigger on_user_message between turns) |
| 2.7 CLI commands | `app.py` |
| 2.8 Start-on-boot | `platforms/*.py`, `installer.py` |
| 2.9 Toggle disable | `config.py` (marker file), `monitor.py` (check), `app.py` (enable/disable) |
| 2.10 Unicode fix | `monitor.py` (→ to -> in print) |

### Tier 3 — Polish

| Feature | Files |
|---------|-------|
| 3.11 Provider display | `monitor.py` (append provider to model line) |
| 3.12 Session duration | `monitor.py` (add elapsed time to presence) |
| 3.13 Error state | `writer.py`, `hook.py` (hook error callbacks) |
| 3.14 Graceful degrade | `monitor.py` (detect Discord process, don't crash) |
| 3.15 Idle timeout | `config.py`, `writer.py` (read from config), `monitor.py` |
| 3.16 Tool filter | `config.py`, `writer.py` (suppress excluded tools) |
| 3.17 Profile-aware | Already partially done in `hook.py` — enhance `monitor.py` to read profile from state |
| 3.18 README | `README.md` |

### Tier 4 — Nice-to-have

| Feature | Files |
|---------|-------|
| 4.19 Cost tracking | `writer.py` (add cost_usd), `hook.py` (capture cost from agent) |
| 4.20 File count | `writer.py` (track files_modified) |
| 4.21 Kanban | `monitor.py` (read kanban state from state file) |
| 4.22 Cron indicator | `monitor.py` (read cron state) |
| 4.23 Orchestrator | `monitor.py` (read orchestrator state) |
