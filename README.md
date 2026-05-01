# Hermes Presence

Cross-platform Discord Rich Presence for [Hermes Agent](https://github.com/nousresearch/hermes-agent).

Displays live Hermes activity in Discord — what tool is running, idle state, session info — regardless of your OS.

## How It Works

```
┌─────────────┐  writes   ┌─────────────────────┐  reads   ┌──────────────┐
│   Hermes    │ ────────> │  presence.json      │ <─────── │   Hermes     │
│   (WSL)     │    │      │  (dual-path:         │          │   Presence   │──> Discord
└─────────────┘    │      │   ~/.hermes/state/   │          │   (Windows)  │
                   │      │   + %APPDATA%/)      │          └──────────────┘
                   │      └──────────────────────┘
                   └── Windows mirror (auto-detected when running in WSL2)
```

1. Hermes writes activity state to `~/.hermes/state/presence.json` **and** mirrors it to `%APPDATA%/hermes_presence.json` on Windows (auto-detected in WSL2)
2. The presence app (running natively on Windows) polls the state file and pushes to Discord via RPC

No modification to Hermes core code. A single import hook connects the writer.

## Quick Start

### 1. Create a Discord Application

1. Go to https://discord.com/developers/applications
2. Click "New Application", name it "Hermes AI"
3. Copy the **Application ID** (shown under the name)
4. Go to Rich Presence > Art Assets and upload the 8 PNGs from `assets/`

### 2. Install

```bash
# On Windows (where Discord runs)
pip install pypresence
```

```bash
# In WSL (where Hermes runs)
cd /mnt/e/hermes-projects/hermes-presence
pip install -e .
```

### 3. Hook Into Hermes

Already done — `cli.py` has the hook at line ~3606. If you need to re-add it:

```python
from hermes_presence.hook import auto_setup
_presence = auto_setup(agent)
```

The hook auto-detects WSL2 and sets `WINDOWS_USER` so state is written to both paths.

### 4. Run the Presence App (on Windows)

```powershell
# From the project directory
.\RunHermesPresence.ps1
```

Or double-click `RunHermesPresence.bat` (can be placed in `shell:startup` for auto-start).

The app polls `%APPDATA%/hermes_presence.json` and pushes to Discord every 5 seconds.

## WSL2 Architecture

Since Discord runs on Windows and Hermes runs in WSL2, the state file is written to **both** locations:

| Path | Written by | Read by |
|------|-----------|---------|
| `~/.hermes/state/presence.json` | Hermes (WSL) | Fallback/same-OS apps |
| `%APPDATA%/hermes_presence.json` | Hermes (WSL, via WSL bridge) | hermes-presence (Windows) |

The hook auto-detects WSL2 by reading `/proc/version` for "microsoft" or "wsl".

## States

| State | Discord Display | When |
|-------|----------------|------|
| `starting` | "Launching Hermes" | Session begins |
| `thinking` | "Thinking" | Processing between tool calls |
| `working` | "Tool: X" | Tool is running (terminal, search, etc.) |
| `idle` | "Idle" | No activity for 10+ seconds |
| `error` | "Error" | Tool execution failed |
| `offline` | "Offline" | Session ended |

## Assets

| Asset | Type | Dimensions |
|-------|------|-----------|
| `hermes_logo` | Large image | 1024x1024 |
| `status_working` | Small overlay | 256x256 |
| `status_researching` | Small overlay | 256x256 |
| `status_idle` | Small overlay | 256x256 |
| `status_error` | Small overlay | 256x256 |
| `status_active` | Small overlay | 256x256 |
| `status_standby` | Small overlay | 256x256 |
| `status_monitoring` | Small overlay | 256x256 |

Upload all 8 to your Discord Application's Rich Presence Art Assets with these exact names.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_DISCORD_CLIENT_ID` | `1497983221697347614` | Discord Application ID |
| `HERMES_PRESENCE_STATE` | `%APPDATA%/hermes_presence.json` | State file path (Windows side) |
| `WINDOWS_USER` | auto-detected | Windows username for WSL bridge path |

## License

MIT — see [LICENSE](LICENSE)
