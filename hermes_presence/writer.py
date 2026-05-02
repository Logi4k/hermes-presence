"""
State file writer — hooks into a running Hermes Agent session and writes
presence state to ~/.hermes/state/presence.json.

This module is imported by Hermes (one-liner hook). The standalone
hermes-presence app reads the JSON file and pushes to Discord.

Usage (in Hermes cli.py or run_agent.py):
    from hermes_presence.writer import PresenceWriter
    writer = PresenceWriter()
    agent.tool_complete_callback = writer.on_tool_complete
"""

import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# State file contract — this is the format the standalone app reads.
# Keep it stable. Add fields, never remove or rename existing ones.

PRESENCE_VERSION = 2

STATE_FILE = Path.home() / ".hermes" / "state" / "presence.json"

# Tools that spawn sub-agents — increment/decrement subagent counter
SUBAGENT_TOOLS = {"delegate_task", "delegate_tasks"}


def _resolve_windows_state_file() -> Optional[Path]:
    """Resolve the Windows-accessible state file path when running in WSL2.

    Called at PresenceWriter init time (not module import) so env vars set
    after import are still picked up.
    """
    windows_user = os.environ.get("WINDOWS_USER", "").strip()
    if windows_user:
        return Path(f"/mnt/c/Users/{windows_user}/AppData/Roaming/hermes_presence.json")
    custom = os.environ.get("HERMES_PRESENCE_STATE", "").strip()
    if custom:
        return Path(custom)
    return None


class PresenceWriter:
    """Writes presence state to a JSON file on tool activity."""

    def __init__(
        self,
        state_file: Optional[Path] = None,
        session_id: str = "",
        source: str = "cli",
        model: str = "",
        provider: str = "",
        profile: str = "main",
    ):
        self._state_file = state_file or STATE_FILE
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._windows_state_file = _resolve_windows_state_file()
        self._lock = threading.Lock()
        self._session_id = session_id or f"session-{os.urandom(4).hex()}"
        self._source = source
        self._model = model
        self._provider = provider
        self._profile = profile
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._tool_calls_count = 0
        self._current_tool: Optional[str] = None
        self._last_detail: str = ""
        self._last_activity = self._started_at
        self._idle_since: Optional[float] = None
        self._subagent_count = 0
        self._tool_started_at: Optional[str] = None  # ISO timestamp when current tool started

        # Write initial state
        self._write_state(activity_state="starting")

    def _write_state(self, activity_state: str, detail: str = ""):
        """Atomically write the presence state file (and Windows mirror if applicable)."""
        state = {
            "version": PRESENCE_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": self._profile,
            "session": {
                "id": self._session_id,
                "source": self._source,
                "started_at": self._started_at,
                "model": self._model,
                "provider": self._provider,
                "tool_calls_count": self._tool_calls_count,
                "subagent_count": self._subagent_count,
            },
            "activity": {
                "state": activity_state,
                "detail": detail or self._last_detail or self._current_tool or "",
                "tool": self._current_tool,
                "idle_seconds": self._idle_seconds(),
                "tool_started_at": self._tool_started_at,
            },
        }

        payload = json.dumps(state, indent=2)

        # Primary: WSL/Linux/macOS state file
        tmp = self._state_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            f.write(payload)
        tmp.replace(self._state_file)

        # Mirror: Windows-accessible path (for WSL2 setups)
        if self._windows_state_file:
            try:
                self._windows_state_file.parent.mkdir(parents=True, exist_ok=True)
                wtmp = self._windows_state_file.with_suffix(".tmp")
                with open(wtmp, "w") as f:
                    f.write(payload)
                wtmp.replace(self._windows_state_file)
            except (OSError, PermissionError):
                pass  # Windows path not available — silently skip

    def _idle_seconds(self) -> int:
        """Seconds since last activity."""
        if self._idle_since is None:
            return 0
        return int(time.time() - self._idle_since)

    def on_tool_start(self, tool_name: str, tool_args: dict = None):
        """Called when a tool begins execution."""
        with self._lock:
            self._current_tool = tool_name
            self._idle_since = None
            self._tool_started_at = datetime.now(timezone.utc).isoformat()
            detail = _format_tool_detail(tool_name, tool_args)
            self._last_detail = detail

            # Track sub-agent spawns
            if tool_name in SUBAGENT_TOOLS:
                self._subagent_count += 1

            self._write_state("working", detail)

    def on_tool_complete(self, tool_call_id: str, tool_name: str, tool_args: dict, result: str):
        """Called when a tool finishes execution."""
        with self._lock:
            self._tool_calls_count += 1
            previous_tool = self._current_tool
            self._current_tool = None
            self._last_activity = datetime.now(timezone.utc).isoformat()
            self._idle_since = time.time()
            self._tool_started_at = None

            # Sub-agents complete when delegate_task returns
            if previous_tool in SUBAGENT_TOOLS:
                self._subagent_count = max(0, self._subagent_count - 1)

            # Keep _last_detail so thinking state shows what just finished
            self._write_state("thinking")

    def on_user_message(self):
        """Called when the user sends a message (Hermes starts thinking)."""
        with self._lock:
            self._idle_since = None
            self._tool_started_at = None
            self._write_state("thinking")

    def on_idle(self):
        """Called periodically to mark idle state."""
        with self._lock:
            idle_sec = self._idle_seconds()
            if idle_sec > 10:
                self._write_state("idle")

    def on_error(self, error_msg: str):
        """Called when an error occurs."""
        with self._lock:
            self._write_state("error", error_msg)

    def shutdown(self):
        """Called when Hermes session ends."""
        with self._lock:
            self._write_state("offline")

    # Alias for tool_complete_callback protocol
    def __call__(self, tool_call_id: str, tool_name: str, tool_args: dict, result: str):
        """Direct callable — works as agent.tool_complete_callback."""
        self.on_tool_complete(tool_call_id, tool_name, tool_args, result)


def _format_tool_detail(tool_name: str, args: dict = None) -> str:
    """Format a human-readable preview of what the tool is doing."""
    if not args:
        return f"Running {tool_name}..."

    if tool_name == "terminal":
        cmd = args.get("command", "")[:60]
        return f"$ {cmd}"
    elif tool_name == "web_search":
        query = args.get("query", "")[:60]
        return f"Searching: {query}"
    elif tool_name == "web_extract":
        urls = args.get("urls", [])
        preview = urls[0][:50] if urls else "..."
        return f"Reading: {preview}"
    elif tool_name == "read_file":
        path = args.get("path", "")[:50]
        return f"Reading: {path}"
    elif tool_name == "write_file":
        path = args.get("path", "")[:50]
        return f"Writing: {path}"
    elif tool_name == "patch":
        path = args.get("path", "")[:50]
        return f"Editing: {path}"
    elif tool_name == "browser_navigate":
        url = args.get("url", "")[:50]
        return f"Browsing: {url}"
    elif tool_name in ("delegate_task", "delegate_tasks"):
        goal = (args.get("goal") or "")[:60]
        return f"Delegating: {goal}"
    elif tool_name == "execute_code":
        return "Executing Python..."
    elif tool_name == "send_message":
        target = args.get("target", "")[:40]
        return f"Messaging: {target}"
    elif tool_name == "memory":
        return "Saving to memory..."
    elif tool_name == "skill_view":
        name = args.get("name", "")[:40]
        return f"Loading skill: {name}"
    else:
        return f"Running {tool_name}..."
