# Hermes Presence

[![CI](https://github.com/Logi4k/hermes-presence/actions/workflows/ci.yml/badge.svg)](https://github.com/Logi4k/hermes-presence/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-3.1.1-blue)](https://github.com/Logi4k/hermes-presence)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

Cross-platform Discord Rich Presence for Hermes Agent. Shows what Hermes is doing in real time on Discord: active tool, current model, provider, session cost, and sub-agent count.

## Screenshot

```
Discord Profile
  Playing Hermes Agent
  Running tools: 1276 · Model: deepseek-v4 · $0.0834 · 2 subs
```

## Features

- **Real-time Discord presence**: Tool name, model, provider, session metrics, cost tracking
- **Multi-profile support**: Run separate presences for main, clinical-monitor, or any custom Hermes profile (`--profile apollo`)
- **Cross-platform**: Linux (systemd), macOS (launchd), Windows (scheduled task), WSL2 (Windows-side process)
- **WSL-to-Windows mirroring**: Profile-aware state file copied to `%APPDATA%/<profile>_presence.json` for native apps
- **Session metrics**: Tool call count, sub-agent count, files modified, cost in USD
- **Webhook notifications**: POST state changes to any HTTP endpoint (Telegram bot, Slack, etc.)
- **Self-update**: `hermes-presence update` pulls latest from GitHub and reinstalls
- **Rich CLI**: `status --json`, `restart`, `validate`, `config set`, `run --profile`
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

### For clinical-monitor or other profiles

```bash
hermes-presence install --profile apollo --client-id YOUR_APOLLO_CLIENT_ID
hermes-presence status   # checks main profile
# State file: ~/.hermes/state/apollo_presence.json
```

## Architecture

```
Hermes Agent (post_llm_call hook)
    │
    ▼
StateFileWriter ──► ~/.hermes/state/presence.json   ← main profile
    │                 ~/.hermes/state/apollo_presence.json  ← apollo profile
    │
    ├──► UnifiedMonitor (reads state → Discord RPC)
    │
    └──► Windows mirror: %APPDATA%/hermes_presence.json
                          %APPDATA%/apollo_presence.json  ← WSL2 only
```

The hook fires after every LLM call: extracts model, provider, and tool info, writes a JSON state file. A background monitor process polls the state file and updates Discord Rich Presence.

**Single-presence architecture**: One monitor process handles one profile's state file. Run multiple monitors for multiple profiles with different `--profile` values. Each profile tracks its own Discord client ID, state file, and session metrics.

## CLI Reference

| Command | Description |
|---|---|
| `hermes-presence install` | One-command setup: check deps, get client ID, install background service |
| `hermes-presence install --profile apollo` | Install for a specific Hermes profile |
| `hermes-presence uninstall` | Stop and remove the background service |
| `hermes-presence status` | Show human-readable status |
| `hermes-presence status --json` | Machine-readable JSON output (for scripts/dashboards) |
| `hermes-presence enable` | Re-enable after disable |
| `hermes-presence disable` | Temporarily stop presence without uninstalling |
| `hermes-presence validate` | Run diagnostic checks (pip, Discord, WSL bridge) |
| `hermes-presence config` | Show current configuration |
| `hermes-presence config set <key> <value>` | Update config (e.g., `display.idle_timeout 20`) |
| `hermes-presence run` | Run monitor in foreground for debugging |
| `hermes-presence update` | Self-update from GitHub |
| `hermes-presence restart` | Restart the background monitor |
| `hermes-presence version` | Show version |
| `hermes-presence help` | Show full help |

## Configuration

Config is stored at `~/.hermes/presence.toml`. All values have sensible defaults.

```toml
[discord]
client_id = "1497983221697347614"

[display]
show_model = true
show_provider = true
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
ruff check hermes_presence/
ruff format --check hermes_presence/
mypy hermes_presence/ --ignore-missing-imports
```

CI runs these same checks on every push.

### Debugging

```bash
# Run monitor in foreground (see all output)
hermes-presence run --log-file /tmp/presence-debug.log

# Check what the monitor sees
hermes-presence status --json | python -m json.tool
```

## Profiles

| Profile | State file | Discord app | Monitor |
|---|---|---|---|
| `main` (default) | `~/.hermes/state/presence.json` | Main Hermes (client_id) | `hermes-presence` service |
| `apollo` | `~/.hermes/state/apollo_presence.json` | Clinical monitor (client_id) | Separate `install --profile apollo` |
| `custom` | `~/.hermes/state/{profile}_presence.json` | Any client_id | Separate `install --profile {name}` |

## License

MIT
