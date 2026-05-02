import json
import os
import sys
import time
import signal
from datetime import datetime, timezone
from pathlib import Path
from pypresence import Presence, DiscordNotFound, PipeClosed

CLIENT_ID = "1497983221697347614"
STATE_FILE = Path(os.environ.get("APPDATA", "")) / "hermes_presence.json"

# Try ALL pipes — maintain separate connections for stable + Canary
PIPES = [0, 1, 2, 3]

ACTIVITY_MAP = {
    "starting": ("Launching Hermes", "Starting session..."),
    "thinking": ("Thinking", "Processing..."),
    "typing": ("Preparing", "About to respond..."),
    "working": ("Working", None),
    "reading": ("Reading", None),
    "idle": ("Idle", "Waiting for input"),
    "error": ("Error", None),
    "offline": ("Offline", "Session ended"),
    "orchestrating": ("Orchestrating", None),
    "cron_job": ("Cron Job", None),
    "session_ended": ("Session Ended", None),
}

# Tool → small_image icon mapping (overrides state-based icon)
TOOL_ICON_MAP = {
    "terminal": "status_active",  # Console/terminal
    "web_search": "status_researching",  # Magnifying glass
    "web_extract": "status_researching",  # Reading web
    "browser_navigate": "status_monitoring",  # Globe/browser
    "browser_click": "status_monitoring",
    "browser_type": "status_monitoring",
    "browser_snapshot": "status_monitoring",
    "read_file": "status_researching",  # Reading
    "write_file": "status_working",  # Writing
    "patch": "status_working",  # Editing
    "execute_code": "status_active",  # Code running
    "delegate_task": "status_monitoring",  # Delegation
    "delegate_tasks": "status_monitoring",
    "send_message": "status_active",  # Outbound comms
    "memory": "status_standby",  # Background task
    "skill_view": "status_researching",  # Loading reference
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


def update_all(state_text, details, small_img, small_text, start_ts, buttons, party_size=None):
    """Push the same presence to every connected pipe."""
    dead = []
    for pipe_num, rpc in connections.items():
        try:
            kwargs = {
                "state": state_text,
                "details": details,
                "large_image": "hermes_logo",
                "large_text": "Hermes Agent",
                "small_image": small_img,
                "small_text": small_text,
                "start": start_ts,
                "buttons": buttons,
            }
            if party_size is not None and party_size > 1:
                kwargs["party_size"] = [party_size, party_size]

            rpc.update(**kwargs)
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


def _resolve_small_icon(tool_name, state_name):
    """Pick the best small_image icon for the current context.

    Priority: tool-specific icon > state-based icon > None.
    """
    if tool_name:
        # Check exact match first, then prefix match for browser_* family
        icon = TOOL_ICON_MAP.get(tool_name)
        if icon:
            return icon
        # Prefix fallback for browser_* and delegate_* families
        for prefix in ("browser_", "delegate_"):
            if tool_name.startswith(prefix):
                return TOOL_ICON_MAP.get(prefix.rstrip("_"), "status_active")

    # Fall back to state-based icon
    if state_name in ("working", "idle", "error"):
        return f"status_{state_name}"

    return None


def _format_model_label(model, provider):
    """Build a compact model label from session info."""
    if model:
        label = model
        # Shorten common model names
        for long, short in [
            ("claude-sonnet-4", "Claude Sonnet 4"),
            ("claude-opus-4", "Claude Opus 4"),
            ("deepseek-v4", "DeepSeek V4"),
            ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("gpt-4o", "GPT-4o"),
            ("gpt-5", "GPT-5"),
        ]:
            if long in model.lower():
                label = short
                break
        return label
    if provider:
        return provider.capitalize()
    return ""


print("[start] Multi-pipe monitor v2 (model + tool icons + subagents + timer)", flush=True)

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
            subagent_count = sess.get("subagent_count", 0)
            tool_started_at = act.get("tool_started_at")

            template = ACTIVITY_MAP.get(state_name, ("Active", None))
            state_text = template[0]
            details = detail or template[1] or ""
            if len(details) > 128:
                details = details[:125] + "..."

            # #2: Append model name to state text
            model_label = _format_model_label(sess.get("model", ""), sess.get("provider", ""))
            if model_label:
                state_text = f"{state_text} · {model_label}"

            # #4: Tool-specific small icon
            small_img = _resolve_small_icon(tool, state_name)
            small_text = tool or state_name

            # #6: Use tool_started_at as start timestamp (shows elapsed per-tool)
            #     Fall back to session start when no tool is running.
            if tool_started_at:
                start_ts = int(datetime.fromisoformat(tool_started_at).timestamp())
            else:
                start_ts = int(
                    datetime.fromisoformat(
                        sess.get("started_at", datetime.now(timezone.utc).isoformat())
                    ).timestamp()
                )

            new_hash = f"{state_text}|{details}|{tool}|{sess.get('tool_calls_count', 0)}|{subagent_count}|{tool_started_at}"
            if new_hash != last_hash:
                buttons = [
                    {
                        "label": "Hermes Agent",
                        "url": "https://github.com/NousResearch/hermes-agent",
                    },
                ]
                # Add second button for Nexus Dashboard when available
                # buttons.append({"label": "Nexus Dashboard", "url": "http://localhost:5173"})

                # #5: Sub-agent party size
                party = None
                if subagent_count > 0:
                    party = subagent_count + 1  # Hermes + sub-agents

                update_all(
                    state_text,
                    details,
                    small_img,
                    small_text,
                    start_ts,
                    buttons,
                    party_size=party,
                )
                last_hash = new_hash
                pipe_list = ",".join(str(p) for p in connections)
                extras = []
                if subagent_count > 0:
                    extras.append(f"{subagent_count} subs")
                if tool:
                    extras.append(f"icon={small_img}")
                extra_str = f" ({', '.join(extras)})" if extras else ""
                print(
                    f"[update → pipes {pipe_list}] {state_text}: {details}{extra_str}",
                    flush=True,
                )
        else:
            if last_hash:
                disconnect_all()
                last_hash = ""

    except Exception as e:
        print(f"[err] {e}", flush=True)

    time.sleep(5)
