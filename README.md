# Hermes Presence v3.0

Cross-platform Discord Rich Presence for Hermes Agent.

See what your AI is doing in real time, right in your Discord profile.
One command to install, works on every platform.

![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20WSL2-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-green)
![Version](https://img.shields.io/badge/version-3.0.0-black)

---

## What It Shows

- **Activity state**: idle, working, thinking, researching, monitoring, error
- **Current tool**: what Hermes is doing right now (reading files, searching web, running terminal, spawning sub-agents...)
- **Model and provider**: which model is active (DeepSeek V4, Claude, GPT...)
- **Session stats**: tool calls, sub-agents, files modified, cost
- **Party size**: shows when sub-agents are running
- **Session duration**: how long this session has been active
- **Configurable buttons**: GitHub, Nexus Dashboard, custom URLs

## Features

**Tier 1 — Blockers (production-ready)**
- One-command installer (`hermes-presence install`)
- Cross-platform: Linux (systemd), macOS (launchd), Windows (Task Scheduler), WSL2
- Per-user Discord Application Client ID
- Config file (`~/.hermes/presence.toml`) with env var overrides

**Tier 2 — Quality of Life**
- Model and provider display in Discord
- Streaming/thinking indicator during generation
- CLI commands: `status`, `enable`, `disable`, `config`, `run`
- Start-on-boot (systemd user unit, launchd plist, Windows Scheduled Task)
- One-command toggle disable
- Unicode-safe output

**Tier 3 — Polish**
- Configurable idle timeout
- Tool name exclusion/filter
- Profile-aware (main, clinical-monitor, etc.)
- Error state with icon
- Graceful degradation (works even when Discord isn't running)
- Session duration tracking

**Tier 4 — Advanced**
- Cost tracking (USD)
- Files modified counter
- Kanban phase display
- Cron job detection
- Orchestrator (Cursor/Codex/Droid) activity display

## Quick Start

### Prerequisites

- Python 3.9 or later
- Discord desktop app (not browser)
- A Discord Application (you'll create one during install)

### Install

```bash
# Install the package
cd /path/to/hermes-presence
pip install .

# One-command setup — creates Discord app, configures auto-start
hermes-presence install
```

The installer walks you through:
1. Creating a Discord Application (or using an existing one)
2. Saving your Client ID to `~/.hermes/presence.toml`
3. Setting up auto-start for your platform
4. Starting the monitor immediately

### Or use environment variables

```bash
export HERMES_DISCORD_CLIENT_ID=1234567890123456789

# Then install (skips the setup wizard)
hermes-presence install --client-id $HERMES_DISCORD_CLIENT_ID
```

### Verify

```bash
hermes-presence status
```

If everything is working, your Discord profile will show:
```
Playing Hermes AI
Status: Waiting for input...
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `hermes-presence install` | Full one-command setup |
| `hermes-presence install --force` | Reinstall (overwrite existing config) |
| `hermes-presence uninstall` | Remove auto-start and monitor |
| `hermes-presence status` | Show current status, activity, session stats |
| `hermes-presence enable` | Re-enable after disabling |
| `hermes-presence disable` | Temporarily hide presence |
| `hermes-presence config` | View current config |
| `hermes-presence config set <key> <value>` | Update a config value |
| `hermes-presence run` | Run monitor in foreground (debug) |
| `hermes-presence --version` | Show version |

### Config Keys

```bash
hermes-presence config set discord.client_id 1234567890
hermes-presence config set display.show_model false
hermes-presence config set display.show_provider true
hermes-presence config set display.idle_timeout 15
hermes-presence config set tools.exclude memory,read_file
hermes-presence config set buttons.hermes_github false
hermes-presence config set buttons.custom_urls "https://example.com,My App"
```

## Configuration File

`~/.hermes/presence.toml` — created automatically on install.

```toml
[discord]
# Your Discord Application Client ID (required)
client_id = "1234567890123456789"

[display]
# Show model name in hover text
show_model = true
# Show provider name in hover text
show_provider = true
# Seconds of inactivity before showing idle
idle_timeout = 10
# Custom large image key (set in Discord Developer Portal > Rich Presence > Art Assets)
large_image = "hermes_logo"
# Hover text for the large image
large_text = "Hermes AI Assistant"

[tools]
# Tools to hide from Discord display
exclude = []

[buttons]
# Show Hermes GitHub link button
hermes_github = true
# Show Nexus Dashboard link button (Philips only)
nexus_dashboard = false
# Custom URL buttons — format: "url,label"
custom_urls = []

[windows]
# Force Windows IPC mode even on WSL2
force_windows_ipc = false
# Mirror state file to Windows %APPDATA%
state_file_mirror = true

[advanced]
# How often to poll the state file (seconds)
poll_interval = 1.0
# Retry interval for pipe connection (seconds)
pipe_connect_retry = 5
```

### Environment Variable Overrides

| Variable | Overrides |
|----------|-----------|
| `HERMES_DISCORD_CLIENT_ID` | `discord.client_id` |
| `HERMES_PRESENCE_STATE` | State file path |
| `HERMES_PRESENCE_DISABLE` | `true` to disable |
| `HERMES_MODEL` | Model name |
| `HERMES_PROVIDER` | Provider name |
| `HERMES_PROFILE` | Profile name |
| `HERMES_ORCHESTRATOR` | `1` if running as orchestrator |
| `HERMES_CRON_JOB_ID` | Set when running as cron job |

## Platform-Specific Details

### Linux

Uses a **systemd user unit**:
- `~/.config/systemd/user/hermes-presence.service`
- Auto-starts on login
- Restarts on failure
- `journalctl --user -u hermes-presence` to view logs

### macOS

Uses a **launchd agent**:
- `~/Library/LaunchAgents/com.hermes.presence.plist`
- Loads at login
- `~/Library/Logs/hermes-presence/` for logs

### Windows

Uses a **Windows Scheduled Task**:
- Task name: `HermesPresence`
- Triggers at user logon with 30-second delay
- Script deployed to `%APPDATA%\hermes_presence_monitor.py`
- **IPC**: Connects directly to Discord via named pipes

### WSL2

Same as Windows — the monitor runs on the Windows side:
- State file is mirrored from WSL to Windows via `state_file_mirror`
- Windows Scheduled Task handles the actual Discord connection
- This avoids WSL's lack of named pipe support

## How It Works

```
Hermes CLI (WSL/Linux/macOS/Windows)
    |
    | writes to ~/.hermes/state/presence.json on every tool call
    v
Presence Monitor (runs in same OS as Discord)
    |
    | polls state file every second
    | connects to Discord IPC pipe
    | updates Rich Presence
    v
Discord Desktop App
    |
    | displays activity to your friends
    v
```

## Integration with Hermes CLI

Add to your Hermes config:

```yaml
# In ~/.hermes/config.yaml
plugins:
  hooks:
    - hermes_presence.hook

# Or use the CLI
hermes plugin add hermes-presence
```

The hook automatically:
- Detects model and provider at session start
- Writes `tool_start` events on every tool call
- Updates state on `tool_end`, `tool_error`, `session_end`, `shutdown`
- Mirrors state to Windows when on WSL2
- Detects cron jobs, orchestrator mode, and kanban phases

## Troubleshooting

### Discord doesn't show my activity

1. Check the monitor is running: `hermes-presence status`
2. Start manually: `hermes-presence run` (watch for errors)
3. Ensure Discord desktop app is running (not browser)
4. Verify your Client ID: `hermes-presence config`

### "Discord Not Found" error

- Discord desktop app must be running BEFORE the monitor
- On Linux, Discord must support Rich Presence (some Flatpak versions don't)
- Try restarting Discord, then `hermes-presence install --force`

### WSL2: No activity showing

- The Windows Scheduled Task must be created: `hermes-presence install`
- State file mirror must be working — check `%APPDATA%\hermes_presence.json`
- Run `hermes-presence run` to debug (shows all output)

### Client ID not set

```bash
# Option 1: Environment variable (persist in .bashrc/.zshrc)
export HERMES_DISCORD_CLIENT_ID=your_client_id_here

# Option 2: Config file
hermes-presence config set discord.client_id your_client_id_here

# Option 3: Reinstall
hermes-presence install
```

## Development

### Project Structure

```
hermes-presence/
  hermes_presence/
    __init__.py          # Package init, exports
    app.py               # CLI entry point
    config.py            # Config system (TOML + env vars)
    hook.py              # Hermes event hooks
    installer.py         # One-command installer
    monitor.py           # Unified cross-platform monitor
    writer.py            # State file writer
    platforms/           # OS-specific launchers
      __init__.py         # Abstract base class
      linux.py            # systemd user unit
      macos.py            # launchd plist
      windows.py          # Task Scheduler
  pyproject.toml         # Package metadata
  README.md              # This file
  ARCHITECTURE.md        # Detailed architecture
```

### Install in dev mode

```bash
cd /path/to/hermes-presence
pip install -e .[dev]
```

### Run tests

```bash
pytest
```

## License

MIT — see `pyproject.toml`.

## Related

- [Hermes Agent](https://github.com/nousresearch/hermes-agent)
- [pypresence](https://github.com/qwertyquerty/pypresence) — Discord Rich Presence Python library
- [Discord Developer Portal](https://discord.com/developers/applications)
