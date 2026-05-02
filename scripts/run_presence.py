import json, os, sys, time, signal
from datetime import datetime, timezone
from pathlib import Path
from pypresence import Presence, DiscordNotFound, PipeClosed

CLIENT_ID = "1497983221697347614"
STATE_FILE = Path(os.environ.get("APPDATA", "")) / "hermes_presence.json"

# Try ALL pipes — maintain separate connections for stable + Canary
PIPES = [0, 1, 2, 3]

ACTIVITY_MAP = {
    "starting":   ("Launching Hermes", "Starting session..."),
    "thinking":   ("Thinking", "Processing..."),
    "working":    ("Working", None),
    "idle":       ("Idle", "Waiting for input"),
    "error":      ("Error", None),
    "offline":    ("Offline", "Session ended"),
}

print(f"STATE_FILE: {STATE_FILE}", flush=True)

# connections[pipe_num] = Presence instance
connections: dict[int, Presence] = {}
last_hash = ""

def connect_all():
    """Connect to every available Discord pipe simultaneously."""
    global connections
    for pipe_num in PIPES:
        if pipe_num in connections:
            continue  # Already connected
        try:
            rpc = Presence(CLIENT_ID, pipe=pipe_num)
            rpc.connect()
            connections[pipe_num] = rpc
            print(f"[OK] Pipe {pipe_num} connected", flush=True)
        except DiscordNotFound:
            continue
        except Exception as e:
            print(f"[pipe {pipe_num}] {e}", flush=True)
            continue

    return len(connections) > 0

def disconnect_all():
    """Clear and close all connections."""
    global connections
    for pipe_num, rpc in list(connections.items()):
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass
    connections.clear()

def update_all(state_text, details, small_img, small_text, start_ts, buttons):
    """Push the same presence to every connected pipe."""
    dead = []
    for pipe_num, rpc in connections.items():
        try:
            rpc.update(
                state=state_text,
                details=details,
                large_image="hermes_logo",
                large_text="Hermes Agent",
                small_image=small_img,
                small_text=small_text,
                start=start_ts,
                buttons=buttons,
            )
        except (PipeClosed, ConnectionError, OSError):
            print(f"[pipe {pipe_num}] Disconnected", flush=True)
            dead.append(pipe_num)
        except Exception as e:
            print(f"[pipe {pipe_num}] Error: {e}", flush=True)

    for pipe_num in dead:
        try:
            connections[pipe_num].close()
        except Exception:
            pass
        del connections[pipe_num]

def shutdown(*args):
    disconnect_all()
    print("[END]", flush=True)
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

print("[start] Multi-pipe monitor (headless-ready)", flush=True)

while True:
    # Connect to any new pipes
    connect_all()

    if not connections:
        print("[wait] No Discord pipes available", flush=True)
        time.sleep(5)
        continue

    try:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
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

            small_img = None
            if state_name in ("working", "idle", "error"):
                small_img = f"status_{state_name}"

            new_hash = f"{state_text}|{details}|{tool}|{sess.get('tool_calls_count',0)}"
            if new_hash != last_hash:
                buttons = [{"label": "Hermes Agent", "url": "https://github.com/NousResearch/hermes-agent"}]
                start_ts = int(datetime.fromisoformat(sess.get("started_at", datetime.now(timezone.utc).isoformat())).timestamp())

                update_all(state_text, details, small_img, tool or state_name, start_ts, buttons)
                last_hash = new_hash
                pipe_list = ",".join(str(p) for p in connections)
                print(f"[update → pipes {pipe_list}] {state_text}: {details}", flush=True)
        else:
            if last_hash:
                disconnect_all()
                last_hash = ""

    except Exception as e:
        print(f"[err] {e}", flush=True)

    time.sleep(5)
