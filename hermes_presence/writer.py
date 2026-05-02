"""
State file writer for Hermes Discord Rich Presence.

Writes a JSON file to ~/.hermes/state/presence.json that the Discord
monitor polls. Enhanced for v3.0 with model, provider, error state,
cost tracking, session duration, and orchestrator/cron/kanban detection.

Thread-safe: uses atomic writes (write to temp + rename).
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_STATE_FILE = Path.home() / ".hermes" / "state" / "presence.json"

# Mapping of tool names to presence display details
TOOL_ICONS: dict[str, dict[str, str]] = {
    "delegate_task": {"detail": "Orchestrating sub-agents", "large_image": "status_monitoring"},
    "read_file": {"detail": "Reading {path}", "large_image": "status_active"},
    "write_file": {"detail": "Writing {path}", "large_image": "status_active"},
    "patch": {"detail": "Editing {path}", "large_image": "status_active"},
    "terminal": {"detail": "Running command", "large_image": "status_working"},
    "execute_code": {"detail": "Executing Python", "large_image": "status_working"},
    "web_search": {"detail": "Searching the web", "large_image": "status_researching"},
    "web_extract": {"detail": "Extracting web content", "large_image": "status_researching"},
    "browser_navigate": {"detail": "Browsing the web", "large_image": "status_researching"},
    "browser_click": {"detail": "Interacting with page", "large_image": "status_researching"},
    "browser_type": {"detail": "Filling form fields", "large_image": "status_researching"},
    "browser_snapshot": {"detail": "Inspecting page", "large_image": "status_researching"},
    "browser_console": {"detail": "Checking browser console", "large_image": "status_researching"},
    "browser_vision": {"detail": "Taking screenshot", "large_image": "status_researching"},
    "memory": {"detail": "Storing memory", "large_image": "status_active"},
    "send_message": {"detail": "Sending message", "large_image": "status_active"},
    "skill_view": {"detail": "Loading skill", "large_image": "status_researching"},
    "skill_manage": {"detail": "Managing skill", "large_image": "status_active"},
    "vision_analyze": {"detail": "Analyzing image", "large_image": "status_researching"},
    "image_generate": {"detail": "Generating image", "large_image": "status_working"},
    "text_to_speech": {"detail": "Generating speech", "large_image": "status_working"},
    "session_search": {"detail": "Searching memory", "large_image": "status_researching"},
    "clarify": {"detail": "Asking for clarification", "large_image": "status_active"},
    "search_files": {"detail": "Searching files", "large_image": "status_active"},
    "todo": {"detail": "Managing task list", "large_image": "status_active"},
    "cronjob": {"detail": "Managing cron jobs", "large_image": "status_working"},
}


class PresenceWriter:
    """Writes state updates to presence.json for Discord monitor consumption.

    Usage:
        writer = PresenceWriter()
        writer.tool_call("terminal", {"command": "npm run build"})
        writer.set_session("deepseek-v4-pro", "deepseek", thinking=True)
        writer.error("Connection refused on port 3000")
        writer.set_cost(0.042)
        writer.file_modified()
        writer.idle()
    """

    def __init__(self, state_file: Optional[Path] = None):
        self._state_file = state_file or DEFAULT_STATE_FILE
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now(timezone.utc)
        self._tool_calls_count = 0
        self._files_modified = 0
        self._cost_usd = 0.0
        self._subagent_count = 0
        self._current_tool: Optional[str] = None
        self._current_model: str = "unknown"
        self._current_provider: str = "unknown"
        self._is_cron: bool = False
        self._is_orchestrator: bool = False
        self._kanban_phase: Optional[str] = None
        self._profile: str = "main"

    def set_profile(self, profile: str):
        """Set the active Hermes profile name."""
        self._profile = profile

    def set_session(
        self,
        model: str,
        provider: str,
        thinking: bool = False,
        is_cron: bool = False,
        is_orchestrator: bool = False,
        profile: Optional[str] = None,
    ):
        """Called at session start with model/provider info."""
        self._current_model = model
        self._current_provider = provider
        self._is_cron = is_cron
        self._is_orchestrator = is_orchestrator
        if profile:
            self._profile = profile

        self._session_start = datetime.now(timezone.utc)
        self._tool_calls_count = 0
        self._files_modified = 0
        self._cost_usd = 0.0
        self._subagent_count = 0

        state = "thinking" if thinking else "typing"
        large_image = "status_standby"

        if is_cron:
            large_image = "status_monitoring"
            state = "cron_job"
        elif is_orchestrator:
            large_image = "status_monitoring"
            state = "orchestrating"

        self._write_state(
            state=state,
            detail=f"Session started with {provider}/{model}",
            large_image=large_image,
        )

    def tool_call(self, tool_name: str, params: Optional[dict] = None):
        """Record a tool call in progress."""
        self._current_tool = tool_name
        self._tool_calls_count += 1

        icon = TOOL_ICONS.get(
            tool_name,
            {"detail": f"Using {tool_name}", "large_image": "status_active"},
        )
        detail = icon["detail"]
        large_image = icon.get("large_image", "status_active")

        # Substitute path if available
        if "{path}" in detail and params:
            path_val = params.get("path", params.get("command", ""))
            if path_val:
                # Truncate long paths
                if isinstance(path_val, str) and len(path_val) > 40:
                    path_val = "..." + path_val[-37:]
                detail = detail.format(path=path_val)

        # Detect sub-agent spawning
        if tool_name == "delegate_task" and params:
            try:
                if params.get("tasks"):
                    task_count = len(params["tasks"])
                    detail = f"Spawning {task_count} sub-agent(s)"
                    self._subagent_count += task_count
                else:
                    detail = "Spawning sub-agent"
                    self._subagent_count += 1
            except Exception:
                pass

        self._write_state(
            state="working",
            tool=tool_name,
            detail=detail,
            large_image=large_image,
        )

    def thinking(self):
        """Signal that the model is streaming/generating a response."""
        self._write_state(
            state="thinking",
            detail="Generating response...",
            large_image="status_working",
        )

    def reading(self, path: str = ""):
        """Signal file reading activity."""
        self._write_state(
            state="reading",
            tool="read_file",
            detail=f"Reading {path}" if path else "Reading file",
            large_image="status_active",
        )

    def file_modified(self, count: int = 1):
        """Increment the files modified counter."""
        self._files_modified += count

    def set_cost(self, cost_usd: float):
        """Set the current session cost."""
        self._cost_usd = cost_usd

    def add_cost(self, cost_usd: float):
        """Add to the session cost."""
        self._cost_usd += cost_usd

    def set_subagent_count(self, count: int):
        """Set subagent count directly (for sync from orchestrator)."""
        self._subagent_count = max(0, count)

    def set_kanban(self, phase: Optional[str]):
        """Set current kanban phase (or None to clear)."""
        self._kanban_phase = phase

    def error(self, message: str = ""):
        """Signal an error state."""
        self._write_state(
            state="error",
            detail=message[:100] if message else "An error occurred",
            large_image="status_error",
        )

    def idle(self):
        """Clear to idle state."""
        self._current_tool = None
        self._write_state(
            state="idle",
            tool=None,
            detail="Waiting for input",
            large_image="status_idle",
        )

    def shutdown(self):
        """Write final shutdown state."""
        self._write_state(
            state="offline",
            detail="Hermes offline",
            large_image="status_standby",
        )

    def _write_state(self, state: str, tool: Optional[str] = None,
                     detail: str = "", large_image: str = "status_idle"):
        """Atomic write to state file."""

        session_seconds = int((datetime.now(timezone.utc) - self._session_start).total_seconds())

        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": self._profile,
            "activity": {
                "state": state,
                "tool": tool or self._current_tool,
                "detail": detail,
                "large_image": large_image,
                "kanban_phase": self._kanban_phase,
            },
            "session": {
                "started": self._session_start.isoformat(),
                "duration_seconds": session_seconds,
                "model": self._current_model,
                "provider": self._current_provider,
                "tool_calls_count": self._tool_calls_count,
                "subagent_count": self._subagent_count,
                "files_modified": self._files_modified,
                "cost_usd": round(self._cost_usd, 6),
                "is_cron": self._is_cron,
                "is_orchestrator": self._is_orchestrator,
            },
        }

        # Atomic write: write to temp, rename
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._state_file.parent,
            delete=False,
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=True, indent=2)
            tmp_path = tmp.name

        try:
            Path(tmp_path).rename(self._state_file)
        except OSError:
            # Fall back to direct write if rename fails (cross-filesystem)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


# Singleton instance for the hook module
_writer: Optional[PresenceWriter] = None


def get_writer(state_file: Optional[Path] = None) -> PresenceWriter:
    """Get or create the singleton PresenceWriter."""
    global _writer
    if _writer is None:
        _writer = PresenceWriter(state_file)
    return _writer
