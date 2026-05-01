# RunHermesPresence.ps1
# Windows launcher for hermes-presence.
# Install: pip install pypresence, then run this script.
#
# To auto-start with Windows:
#   Copy RunHermesPresence.bat to shell:startup

param(
    [string]$ClientId = "1497983221697347614",
    [string]$StateFile = "$env:APPDATA\hermes_presence.json"
)

$env:HERMES_DISCORD_CLIENT_ID = $ClientId
$env:HERMES_PRESENCE_STATE = $StateFile

Write-Host "Hermes Presence — launching monitor..." -ForegroundColor Cyan
Write-Host "  Discord Client ID: $ClientId" -ForegroundColor DarkGray
Write-Host "  State file: $StateFile" -ForegroundColor DarkGray
Write-Host ""

# Check pypresence
python -c "import pypresence" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] pypresence not installed. Installing..." -ForegroundColor Yellow
    pip install pypresence
}

# Run the Python app directly inline since it's a single-file monitor
$script = @'
import json, os, sys, time, signal
from datetime import datetime, timezone
from pathlib import Path
from pypresence import Presence, DiscordNotFound, PipeClosed

CLIENT_ID = os.environ.get("HERMES_DISCORD_CLIENT_ID", "")
STATE_FILE = Path(os.environ.get("HERMES_PRESENCE_STATE", Path.home() / ".hermes" / "state" / "presence.json"))
POLL_INTERVAL = 5

ACTIVITY_MAP = {
    "starting":   ("Launching Hermes", "Starting session..."),
    "thinking":   ("Thinking", "Processing..."),
    "working":    ("Working", None),
    "idle":       ("Idle", "Waiting for input"),
    "error":      ("Error", None),
    "offline":    ("Offline", "Session ended"),
}

if not CLIENT_ID:
    print("ERROR: HERMES_DISCORD_CLIENT_ID not set")
    sys.exit(1)

rpc = Presence(CLIENT_ID)
connected = False
last_hash = ""

def connect():
    global connected
    try:
        rpc.connect()
        connected = True
        print(f"[connect] Connected to Discord IPC")
        return True
    except DiscordNotFound:
        return False
    except Exception as e:
        print(f"[connect] Error: {e}")
        return False

def shutdown(*args):
    global connected
    try:
        if connected:
            rpc.clear()
            rpc.close()
    except: pass
    print("[shutdown] Clean exit")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

print(f"[start] Polling: {STATE_FILE}")
print(f"[start] Interval: {POLL_INTERVAL}s")

while True:
    if not connected:
        if connect():
            pass
        else:
            time.sleep(POLL_INTERVAL)
            continue

    try:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text())
            act = state.get("activity", {})
            sess = state.get("session", {})
            state_name = act.get("state", "thinking")
            detail = act.get("detail", "")
            tool = act.get("tool", "")

            template = ACTIVITY_MAP.get(state_name, ("Active", None))
            state_text = template[0]
            details = detail or template[1] or ""
            if len(details) > 128:
                details = details[:125] + "..."

            # Small image based on state
            small_img = None
            if state_name in ("working", "idle", "error"):
                small_img = f"status_{state_name}"

            # Hash to skip redundant updates
            new_hash = f"{state_text}|{details}|{tool}|{sess.get('tool_calls_count',0)}"
            if new_hash != last_hash:
                rpc.update(
                    state=state_text,
                    details=details,
                    large_image="hermes_logo",
                    large_text=f"Hermes Agent — {sess.get('model', 'AI')}",
                    small_image=small_img,
                    small_text=tool or state_name,
                    start=int(datetime.fromisoformat(sess.get("started_at", datetime.now(timezone.utc).isoformat())).timestamp()),
                    buttons=[{"label": "Hermes Agent", "url": "https://github.com/NousResearch/hermes-agent"}],
                )
                last_hash = new_hash
        else:
            if last_hash:
                rpc.clear()
                last_hash = ""

    except (PipeClosed, ConnectionError):
        print("[rpc] Connection lost — reconnecting...")
        connected = False
    except Exception as e:
        print(f"[rpc] Error: {e}")

    time.sleep(POLL_INTERVAL)
'@

python -c $script
