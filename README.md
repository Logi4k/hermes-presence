# Hermes Presence

[![CI](https://github.com/Logi4k/hermes-presence/actions/workflows/ci.yml/badge.svg)](https://github.com/Logi4k/hermes-presence/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-3.2.0-blue)](https://github.com/Logi4k/hermes-presence)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

Cross-platform Discord Rich Presence for Hermes Agent. Shows what Hermes is doing in real time on Discord: active tool, current model, provider, reasoning level, privacy-safe mode, session cost, and sub-agent count.

## Screenshot

```
Discord Profile
  Playing Hermes Agent
  Working | GPT-5.5 (Codex) | R: high · Tool calls: 1276 · 2 subs
```

## Features

- **Real-time Discord presence**: Tool name, model, provider, session metrics, cost tracking
- **Multi-profile support**: Run separate presences for different Hermes profiles (`--profile research` or `--profile custom-name`)
- **Cross-platform**: Linux (systemd), macOS (launchd), Windows hidden Startup launcher via `wscript`/`pythonw.exe`, WSL2 (Windows-side process)
- **WSL-to-Windows mirroring**: Profile-aware state file copied to `%APPDATA%/<profile>_presence.json` for native apps
- **Session metrics**: Tool call count, sub-agent count, files modified, cost in USD
- **Webhook notifications**: POST state changes to any HTTP endpoint (Telegram bot, Slack, etc.)
- **Self-update**: `hermes-presence update --restart` pulls latest from GitHub and restarts the monitor
- **Privacy controls**: hide reasoning labels or run in privacy mode to avoid leaking filenames/tools
- **Startup doctor**: `doctor --fix` detects visible `.bat` launchers, stale scheduled tasks, and legacy pollers
- **Rich CLI**: `status --json`, `status --verbose`, `restart`, `validate`, `doctor`, `cleanup-profiles`, `config set`, `run --profile`
- **Hermes hook integration**: `post_llm_call` hook intercepts model info for "unknown model" fix

## Quick Start

```bash
# 1. Install from GitHub
pip install git+https://github.com/Logi4k/hermes-presence.git@main

# 2. Set your Discord Application Client ID
hermes-presence config set discord.client_id YOUR_CLIENT_ID

# 3. Install as a system service
hermes-presence install

# 4. Verify it's working
hermes-presence status
```

### Get a Discord Client ID

1. Go to https://discord.com/developers/applications
2. Create a "New Application" (name it `Hermes Agent`)
3. Copy the "Application ID" from the General Information page
4. (Optional) Upload an icon and set Rich Presence art assets

### For additional Hermes profiles

```bash
hermes-presence install --profile research --client-id YOUR_RESEARCH_CLIENT_ID
hermes-presence status --profile research
# State file: ~/.hermes/state/research_presence.json
```

## Architecture

```
Hermes Agent (post_llm_call hook)
    │
    ▼
StateFileWriter ──► ~/.hermes/state/presence.json   ← default profile
    │                 ~/.hermes/state/research_presence.json  ← research profile
    │
    ├──► UnifiedMonitor (reads state → Discord RPC)
    │
    └──► Windows mirror: %APPDATA%/hermes_presence.json
                          %APPDATA%/research_presence.json  ← WSL2 only
```

The hook fires after every LLM call: extracts model, provider, reasoning effort, and tool info, writes a JSON state file. A background monitor process polls the state file and updates Discord Rich Presence.

**Single-presence architecture**: One monitor process handles one profile's state file. Run multiple monitors for multiple profiles with different `--profile` values. Each profile tracks its own Discord client ID, state file, and session metrics.

## CLI Reference

| Command | Description |
|---|---|
| `hermes-presence install` | One-command setup: check deps, get client ID, install background service |
| `hermes-presence install --profile research` | Install for a specific Hermes profile |
| `hermes-presence uninstall` | Stop and remove the background service |
| `hermes-presence status` | Show human-readable status |
| `hermes-presence status --json` | Machine-readable JSON output including model/provider/reasoning |
| `hermes-presence status --verbose` | Show launcher paths, process names, and startup details |
| `hermes-presence enable` | Re-enable after disable |
| `hermes-presence disable` | Temporarily stop presence without uninstalling |
| `hermes-presence validate` | Run diagnostic checks (pip, Discord, WSL bridge) |
| `hermes-presence doctor --fix` | Diagnose and safely clean visible Windows startup launchers and old tasks |
| `hermes-presence cleanup-profiles clinical` | Remove stale Windows launchers/monitors for a named profile |
| `hermes-presence config` | Show current configuration |
| `hermes-presence config set <key> <value>` | Update config (e.g., `display.idle_timeout 20`) |
| `hermes-presence run` | Run monitor in foreground for debugging |
| `hermes-presence update --restart` | Self-update from GitHub and restart the monitor |
| `hermes-presence restart` | Restart the background monitor |
| `hermes-presence version` | Show version |
| `hermes-presence help` | Show full help |

## Configuration

Config is stored at `~/.hermes/presence.toml`. All values have sensible defaults.

```toml
[discord]
client_id = "YOUR_CLIENT_ID_HERE"

[display]
show_model = true
show_provider = true
show_reasoning = true
privacy_mode = false
idle_timeout = 10
large_image = "hermes_logo"
large_text = "Hermes Agent"

[windows]
force_windows_ipc = false
state_file_mirror = true

[tools]
exclude = []

[buttons]
hermes_github = true
nexus_dashboard = false
custom_urls = []

[advanced]
poll_interval = 5
pipe_connect_retry = 3
log_file = ""

[notify]
url = ""
events = []
```

### Webhook notifications (`[notify]`)

Set `notify.url` to a webhook endpoint. Every state change is POSTed as JSON. Filter by event type with `notify.events`:

```bash
hermes-presence config set notify.url https://your-webhook.example.com/hook
hermes-presence config set notify.events error,session_ended
```

The POST body is the full state file JSON. Event types: `idle`, `running`, `thinking`, `error`, `session_ended`.

### Environment variables

```bash
export HERMES_DISCORD_CLIENT_ID=...     # Override client_id (highest priority)
export HERMES_PRESENCE_STATE=...        # Custom state file path
export WINDOWS_USER=Philips             # WSL2: Windows username for mirror path
```

## Development

```bash
git clone https://github.com/Logi4k/hermes-presence.git
cd hermes-presence
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running checks

```bash
make ci
```

This runs the same gates as GitHub Actions via `scripts/ci-check.sh`:

```bash
ruff check hermes_presence/ --select I,F,E,W
mypy hermes_presence/ --ignore-missing-imports
pytest tests/ -v
```

Use focused targets while developing:

```bash
make lint
make typecheck
make test
```

CI calls the same script on every push, so local and GitHub checks stay aligned.

### Debugging

```bash
# Run monitor in foreground (see all output)
hermes-presence run --log-file /tmp/presence-debug.log

# Check what the monitor sees
hermes-presence status --json | python -m json.tool
```

## Profiles

| Profile | State file | Discord app | Monitor |
|---|---|---|---|---|
| `main` (default) | `~/.hermes/state/presence.json` | Default Hermes (client_id) | `hermes-presence` service |
| `research` | `~/.hermes/state/research_presence.json` | Research profile (client_id) | Separate `install --profile research` |
| `custom` | `~/.hermes/state/{profile}_presence.json` | Any client_id | Separate `install --profile {name}` |

## License

MIT
