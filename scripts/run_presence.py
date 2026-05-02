import json, os, sys, time, signal
from datetime import datetime, timezone
from pathlib import Path
from pypresence import Presence, DiscordNotFound, PipeClosed

CLIENT_ID = "1497983221697347614"
STATE_FILE = Path(os.environ.get("APPDATA", "")) / "hermes_presence.json"

# Try all pipes on reconnect — Discord may grab a different pipe after restart.
# On first connect, prefer pipe 1 (often stable when Canary owns pipe 0).
FIRST_RUN_PIPES = [int(os.environ.get("DISCORD_PIPE", 1)), 0, 2, 3]
ALL_PIPES = [0, 1, 2, 3]

ACTIVITY_MAP = {
    "starting":   ("Launching Hermes", "Starting session..."),
    "thinking":   ("Thinking", "Processing..."),
    "working":    ("Working", None),
    "idle":       ("Idle", "Waiting for input"),
    "error":      ("Error", None),
    "offline":    ("Offline", "Session ended"),
}

print(f"STATE_FILE: {STATE_FILE}", flush=True)

rpc = None
connected = False
active_pipe = None
last_hash = ""
first_connect = True

def _try_pipes(pipe_list):
    global rpc
    for pipe_num in pipe_list:
        try:
            rpc = Presence(CLIENT_ID, pipe=pipe_num)
            rpc.connect()
            print(f"[OK] Connected to Discord on pipe {pipe_num}", flush=True)
            return pipe_num
        except DiscordNotFound:
            continue
        except Exception as e:
            print(f"[pipe {pipe_num}] {e}", flush=True)
            continue
    return None

def connect():
    global connected, active_pipe, rpc, first_connect
    pipes = FIRST_RUN_PIPES if first_connect else ALL_PIPES
    first_connect = False

    result = _try_pipes(pipes)
    if result is not None:
        connected = True
        active_pipe = result
        return True

    print("[ERR] No Discord pipe available", flush=True)
    return False

def shutdown(*args):
    try:
        if connected and rpc:
            rpc.clear()
            rpc.close()
    except: pass
    print("[END]", flush=True)
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

print("[start] Polling...", flush=True)

while True:
    if not connected:
        print(f"[reconnect] Trying pipes...", flush=True)
        time.sleep(2)  # Brief delay — Discord may still be restarting
        if connect():
            pass
        else:
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
                print(f"[update] {state_text}: {details}", flush=True)
        else:
            if last_hash:
                rpc.clear()
                last_hash = ""

    except (PipeClosed, ConnectionError, OSError):
        print("[rpc] Lost connection — will reconnect", flush=True)
        connected = False
        rpc = None
        active_pipe = None
    except Exception as e:
        print(f"[rpc] Error: {e}", flush=True)
        # Don't disconnect on unknown errors — might be transient

    time.sleep(5)
