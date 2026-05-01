"""
Standalone Discord Rich Presence app for Hermes Agent.

Reads presence state from ~/.hermes/state/presence.json (written by Hermes)
and pushes activity to Discord via pypresence.

Cross-platform: works on Linux, macOS, Windows, and WSL2.

Usage:
    python -m hermes_presence.app

Requirements:
    pip install pypresence
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from pypresence import Presence, DiscordNotFound, PipeClosed
except ImportError:
    print("ERROR: pypresence not installed. Run: pip install pypresence")
    sys.exit(1)


# ── Configuration ──────────────────────────────────────────────────────────

# You MUST set this to your Discord Application's Client ID.
# Get one at: https://discord.com/developers/applications
DISCORD_CLIENT_ID = os.environ.get("HERMES_DISCORD_CLIENT_ID", "")

STATE_FILE = Path(os.environ.get("HERMES_PRESENCE_STATE",
    str(Path.home() / ".hermes" / "state" / "presence.json")))
POLL_INTERVAL = 5  # seconds between file checks
IDLE_TIMEOUT = 60  # seconds before showing as idle


# ── Discord Rich Presence ──────────────────────────────────────────────────

# Map of state -> Discord presence fields
# Format: (state_text, details_template, large_image, small_image)
ACTIVITY_MAP = {
    "starting":   ("Launching Hermes", "Starting session...", "hermes_logo", None),
    "thinking":   ("Thinking", "Processing...", "hermes_logo", None),
    "working":    ("Working", "{detail}", "hermes_logo", "status_working"),
    "idle":       ("Idle", "Waiting for input", "hermes_logo", "status_idle"),
    "error":      ("Error", "{detail}", "hermes_logo", "status_error"),
    "offline":    ("Offline", "Session ended", "hermes_logo", None),
}

# Tool-specific images for richer display
TOOL_IMAGES = {
    "terminal":       "status_working",
    "web_search":     "status_researching",
    "web_extract":    "status_researching",
    "read_file":      "status_working",
    "write_file":     "status_working",
    "patch":          "status_working",
    "browser_navigate": "status_researching",
    "delegate_task":  "status_working",
    "execute_code":   "status_working",
    "session_search": "status_researching",
    "memory":         "status_working",
}


class HermesPresence:
    """Manages Discord Rich Presence for a Hermes session."""

    def __init__(self, client_id: str):
        if not client_id:
            raise ValueError(
                "Discord Client ID is required. "
                "Set HERMES_DISCORD_CLIENT_ID env var or pass client_id=."
            )
        self.client_id = client_id
        self.rpc: Optional[Presence] = None
        self._last_state_hash: str = ""
        self._connected = False

    def connect(self) -> bool:
        """Connect to Discord. Retries silently."""
        try:
            self.rpc = Presence(self.client_id)
            self.rpc.connect()
            self._connected = True
            return True
        except DiscordNotFound:
            return False
        except Exception as e:
            print(f"Discord connection error: {e}")
            return False

    def disconnect(self):
        """Clean shutdown."""
        if self.rpc:
            try:
                self.rpc.close()
            except Exception:
                pass
            self.rpc = None
        self._connected = False

    def update(self, state: dict) -> bool:
        """Push presence state to Discord. Returns True if updated."""
        activity_state = state["activity"]["state"]
        detail = state["activity"]["detail"]
        tool = state["activity"].get("tool")
        session = state["session"]

        # Get activity template
        template = ACTIVITY_MAP.get(activity_state)
        if not template:
            return False

        state_text, details_template, large_image, small_image = template

        # Fill in detail
        details = details_template.format(detail=detail) if "{detail}" in details_template else details_template

        # Pick tool-specific small image
        if tool and tool in TOOL_IMAGES:
            small_image = TOOL_IMAGES[tool]

        # Build a hash to avoid redundant updates
        new_hash = f"{state_text}|{details}|{small_image}|{session['tool_calls_count']}"
        if new_hash == self._last_state_hash:
            return False
        self._last_state_hash = new_hash

        if not self._connected:
            return False

        try:
            self.rpc.update(
                state=state_text,
                details=details,
                large_image=large_image or "hermes_logo",
                large_text=f"Hermes Agent — {session['model'] or 'AI'}",
                small_image=small_image,
                small_text=tool or activity_state,
                start=int(datetime.fromisoformat(session["started_at"]).timestamp()),
                buttons=[
                    {"label": "Learn about Hermes", "url": "https://github.com/nousresearch/hermes-agent"}
                ],
            )
            return True
        except (PipeClosed, ConnectionError):
            self._connected = False
            return False
        except Exception as e:
            print(f"RPC update error: {e}")
            return False

    def clear(self):
        """Clear Discord presence."""
        if self.rpc and self._connected:
            try:
                self.rpc.clear()
            except Exception:
                pass


# ── State file reader ─────────────────────────────────────────────────────

def read_state() -> Optional[dict]:
    """Read and parse the presence state file."""
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── Main loop ─────────────────────────────────────────────────────────────

def main():
    client_id = DISCORD_CLIENT_ID
    if not client_id:
        print("ERROR: DISCORD_CLIENT_ID not set.")
        print("  1. Visit https://discord.com/developers/applications")
        print("  2. Create an application named 'Hermes AI'")
        print("  3. Copy the Application ID")
        print("  4. Set: export HERMES_DISCORD_CLIENT_ID=<your-id>")
        print("     or pass: python -m hermes_presence.app <client-id>")
        sys.exit(1)

    presence = HermesPresence(client_id)
    running = True

    def _shutdown(signum=None, frame=None):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(f"Hermes Presence v0.1.0")
    print(f"  State file: {STATE_FILE}")
    print(f"  Poll interval: {POLL_INTERVAL}s")
    print(f"  Connecting to Discord...")

    # Connect loop — retry every 5s until connected
    while running and not presence._connected:
        if presence.connect():
            print("  Connected to Discord ✓")
        else:
            print("  Discord not running — retrying in 5s...")
            for _ in range(5):
                if not running:
                    break
                time.sleep(1)

    # Main poll loop
    while running:
        state = read_state()

        if state:
            presence.update(state)
        else:
            presence.clear()

        time.sleep(POLL_INTERVAL)

    presence.clear()
    presence.disconnect()
    print("Shutdown complete.")


if __name__ == "__main__":
    # Accept client ID as CLI arg
    if len(sys.argv) > 1:
        DISCORD_CLIENT_ID = sys.argv[1]
    main()
