"""
State file writer for Hermes Discord Rich Presence.

Writes a JSON file to ~/.hermes/state/presence.json that the Discord
monitor polls. Enhanced for v3.0 with model, provider, error state,
cost tracking, session duration, and orchestrator/cron/kanban detection.

Thread-safe: uses atomic writes (write to temp + rename).
"""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .tool_icons import TOOL_ICONS

DEFAULT_STATE_FILE = Path.home() / ".hermes" / "state" / "presence.json"

# Mapping of tool names to presence display details


def _humanize_tool_name(tool_name: str) -> str:
    """Return a readable label for unknown tool names."""
    cleaned = str(tool_name or "tool").replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in cleaned.split()) or "Tool"


def _compact_command(command: str, max_len: int = 72) -> str:
    """Return a short, Discord-safe command preview."""
    compact = " ".join(str(command or "").split())
    if len(compact) > max_len:
        compact = compact[: max_len - 3].rstrip() + "..."
    return compact


def _terminal_detail(command: str) -> str:
    """Turn shell commands into an intuitive activity label."""
    cmd = " ".join(str(command or "").split())
    lower = cmd.lower()
    if not cmd:
        return "Running shell task"
    if "pytest" in lower or "vitest" in lower or "npm test" in lower or "pnpm test" in lower:
        return "Running tests"
    if "py_compile" in lower or "tsc" in lower or "typecheck" in lower or "lint" in lower:
        return "Checking code quality"
    if lower.startswith("git status") or " git status" in lower:
        return "Checking repository status"
    if lower.startswith("git diff") or " git diff" in lower:
        return "Reviewing code changes"
    if "hermes-presence update" in lower:
        return "Updating Discord presence"
    if "hermes-presence status" in lower:
        return "Checking Discord presence"
    if "powershell" in lower and "get-process" in lower:
        return "Checking Windows processes"
    return f"Shell: {_compact_command(cmd)}"


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

    def __init__(self, state_file: Optional[Path] = None, session_id: str = ""):
        self._state_file = state_file or DEFAULT_STATE_FILE
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id
        self._session_start = datetime.now(timezone.utc)
        self._tool_calls_count = 0
        self._files_modified = 0
        self._cost_usd = 0.0
        self._subagent_count = 0
        self._current_tool: Optional[str] = None
        self._current_model: str = "unknown"
        self._current_provider: str = "unknown"
        self._reasoning_effort: str = ""
        self._is_cron: bool = False
        self._is_orchestrator: bool = False
        self._kanban_phase: Optional[str] = None
        self._profile: str = "main"
        self._tool_started_at: Optional[str] = None
        self._error_msg: Optional[str] = None
        self._subagent_tasks: list[str] = []

    def _restore_from_state_file(self):
        """Restore model/provider and session stats from the existing state file.

        Each hook invocation runs as a separate process, so the writer starts
        fresh with _current_model='unknown'. Before writing a session-end summary,
        read the existing state to preserve this info.
        """
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            sess = data.get("session", {})
            model = sess.get("model", "")
            provider = sess.get("provider", "")
            reasoning_effort = sess.get("reasoning_effort", "")
            if model and model != "unknown":
                self._current_model = model
            if provider and provider != "unknown":
                self._current_provider = provider
            if reasoning_effort:
                self._reasoning_effort = str(reasoning_effort)
            # Also restore accumulated stats
            self._tool_calls_count = sess.get("tool_calls_count", 0)
            self._files_modified = sess.get("files_modified", 0)
            self._cost_usd = sess.get("cost_usd", 0.0)
            self._subagent_count = sess.get("subagent_count", 0)
            self._is_cron = sess.get("is_cron", False)
            self._is_orchestrator = sess.get("is_orchestrator", False)
            # Restore session start time if available
            started_at = sess.get("started_at")
            if started_at:
                try:
                    self._session_start = datetime.fromisoformat(started_at)
                except (ValueError, TypeError):
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    def _mirror_to_windows(self):
        """Mirror state file to Windows AppData if running under WSL.

        Per-session files eliminate contention between concurrent sessions:
          session → presence_{session_id}.json
          main    → hermes_presence.json (legacy, no session_id)
          profile → {profile}_presence.json (legacy, no session_id)
        """
        if not _is_wsl():
            return

        try:
            content = self._state_file.read_text(encoding="utf-8")

            windows_username = _get_windows_username()
            if not windows_username:
                return

            windows_appdata = Path("/mnt/c/Users") / windows_username / "AppData" / "Roaming"

            # Session-aware filename (primary)
            if self._session_id:
                filename = f"presence_{self._session_id}.json"
            elif self._profile == "main":
                filename = "hermes_presence.json"
            else:
                filename = f"{self._profile}_presence.json"

            windows_state = windows_appdata / filename
            windows_state.parent.mkdir(parents=True, exist_ok=True)

            # Safe encoding (avoid Unicode that breaks Windows cp1252 console)
            safe_content = content.replace("\u2014", "--").replace("\u2013", "-")

            with open(windows_state, "w", encoding="utf-8") as f:
                f.write(safe_content)

        except Exception:
            pass  # Silent -- mirror is best-effort

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
        reasoning_effort: str = "",
    ):
        """Called at session start with model/provider info."""
        self._current_model = model
        self._current_provider = provider
        if reasoning_effort:
            self._reasoning_effort = str(reasoning_effort)
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
        self._tool_started_at = datetime.now(timezone.utc).isoformat()

        icon = TOOL_ICONS.get(
            tool_name,
            {"detail": f"Using {_humanize_tool_name(tool_name)}", "large_image": "status_active"},
        )
        detail = icon["detail"]
        large_image = icon.get("large_image", "status_active")

        if tool_name == "terminal" and params:
            detail = _terminal_detail(str(params.get("command", "")))

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
                    task_goals = [t.get("goal", "")[:60] for t in params["tasks"] if isinstance(t, dict)]
                    self._subagent_tasks = task_goals
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
        """Signal that the model is composing the assistant reply."""
        self._write_state(
            state="thinking",
            detail="Composing reply",
            large_image="status_working",
        )

    def reviewing_tool_results(self, tool_name: str = ""):
        """Keep presence active after a fast tool call while Hermes reviews output."""
        self._current_tool = tool_name or self._current_tool
        if self._tool_started_at is None:
            self._tool_started_at = datetime.now(timezone.utc).isoformat()
        tool_label = _humanize_tool_name(self._current_tool or tool_name or "tool")
        reviewing_label = tool_label
        for prefix in ("Reading ", "Read ", "Editing ", "Edit ", "Searching ", "Search ", "Checking ", "Check ", "Browsing ", "Browse ", "Running ", "Run "):
            if reviewing_label.startswith(prefix):
                reviewing_label = reviewing_label[len(prefix):]
                break
        self._write_state(
            state="thinking",
            tool=self._current_tool,
            detail=f"Reviewing {reviewing_label.lower()} results",
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
        if self._subagent_count == 0:
            self._subagent_tasks = []

    def set_kanban(self, phase: Optional[str]):
        """Set current kanban phase (or None to clear)."""
        self._kanban_phase = phase

    def error(self, message: str = ""):
        """Signal an error state."""
        self._error_msg = message[:100] if message else "An error occurred"
        self._write_state(
            state="error",
            detail=message[:100] if message else "An error occurred",
            large_image="status_error",
        )

    def idle(self):
        """Clear to idle state. Shows orchestrating if sub-agents are active."""
        self._current_tool = None
        self._tool_started_at = None

        # If sub-agents are active, show orchestrating state instead of idle
        if self._subagent_count > 0:
            sub_detail = f"Monitoring {self._subagent_count} sub-agent(s)"
            if self._subagent_tasks:
                sub_detail = f"Monitoring {self._subagent_count} sub-agent(s): {self._subagent_tasks[0]}"
            self._write_state(
                state="orchestrating",
                tool=None,
                detail=sub_detail,
                large_image="status_monitoring",
            )
        else:
            self._write_state(
                state="idle",
                tool=None,
                detail="Waiting for input",
                large_image="status_idle",
            )

    def session_summary(self):
        """Write a rich session-end summary with stats before shutting down.

        Reads the existing state file to preserve model/provider/session stats
        from prior hook invocations (each hook runs as a separate process, so
        the writer instance starts fresh with no model info).
        """
        # Preserve model/provider and session stats from prior state file
        self._restore_from_state_file()

        session_seconds = int((datetime.now(timezone.utc) - self._session_start).total_seconds())
        minutes, seconds = divmod(session_seconds, 60)
        duration_str = f"{minutes}m {seconds}s"

        summary_parts = [
            f"Session ended | {duration_str}",
            f"{self._tool_calls_count} tools used",
        ]
        if self._files_modified > 0:
            summary_parts.append(f"{self._files_modified} files modified")
        if self._cost_usd > 0:
            summary_parts.append(f"${self._cost_usd:.4f} cost")
        if self._subagent_count > 0:
            summary_parts.append(f"{self._subagent_count} sub-agents")

        self._current_tool = None
        self._tool_started_at = None

        self._write_state(
            state="session_ended",
            tool=None,
            detail=" | ".join(summary_parts),
            large_image="status_idle",
        )

    def shutdown(self):
        """Write final shutdown state."""
        self._write_state(
            state="offline",
            detail="Hermes offline",
            large_image="status_standby",
        )

    def _write_state(
        self,
        state: str,
        tool: Optional[str] = None,
        detail: str = "",
        large_image: str = "status_idle",
    ):
        """Atomic write to state file."""

        session_seconds = int((datetime.now(timezone.utc) - self._session_start).total_seconds())

        # Preserve model/provider from existing state file if current is unknown.
        # Belt-and-suspenders: the bridge also restores, but this catches any
        # edge case where _write_state is reached with a fresh writer.
        model = self._current_model
        provider = self._current_provider
        reasoning_effort = self._reasoning_effort
        if (
            model == "unknown" or provider == "unknown" or not reasoning_effort
        ) and self._state_file.exists():
            try:
                existing = json.loads(self._state_file.read_text(encoding="utf-8"))
                sess = existing.get("session", {})
                if model == "unknown" and sess.get("model", "") not in ("", "unknown"):
                    model = sess["model"]
                if provider == "unknown" and sess.get("provider", "") not in (
                    "",
                    "unknown",
                ):
                    provider = sess["provider"]
                if not reasoning_effort and sess.get("reasoning_effort"):
                    reasoning_effort = str(sess["reasoning_effort"])
            except (json.JSONDecodeError, OSError):
                pass

        data = {
            "version": 3,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": self._profile,
            "activity": {
                "state": state,
                "tool": tool if tool is not None else self._current_tool,
                "detail": detail,
                "large_image": large_image,
                "kanban_phase": self._kanban_phase,
                "tool_started_at": self._tool_started_at,
                "is_error": state == "error",
                "error_msg": self._error_msg if state == "error" else None,
            },
            "session": {
                "id": self._session_start.strftime("%Y%m%d_%H%M%S"),
                "source": self._profile,
                "started_at": self._session_start.isoformat(),
                "duration_seconds": session_seconds,
                "model": model,
                "provider": provider,
                "reasoning_effort": reasoning_effort,
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

        # Mirror to Windows if running under WSL
        self._mirror_to_windows()

        # Webhook notification (best-effort, non-blocking)
        self._notify_webhook(state, data)

    def _notify_webhook(self, state: str, data: dict):
        """POST state change to configured webhook URL (best-effort)."""
        try:
            from .config import load_config

            cfg = load_config()
            url = cfg.notify.url.strip()
            if not url:
                return

            # Filter by events if configured
            events_filter = cfg.notify.events
            if events_filter and state not in events_filter:
                return

            import urllib.request

            payload = json.dumps(data, ensure_ascii=True).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # Silent — notifications are best-effort


# --- WSL to Windows mirror (module-level utility) ---


def _is_wsl() -> bool:
    """Detect if running under WSL (requires both kernel marker and Windows mount)."""
    try:
        content = Path("/proc/version").read_text().lower()
        return ("microsoft" in content or "wsl" in content) and Path("/mnt/c/Windows").exists()
    except Exception:
        return False


def _get_windows_username() -> str:
    """Get Windows username from WSL, handling Unicode correctly."""
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "[System.Environment]::UserName",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # Fallback: cmd.exe (fast, but may fail for Unicode names). Avoid shell
    # redirection here: under WSL, `2>nul` creates a literal ./nul file.
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo", "%USERNAME%"],
            capture_output=True,
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        username = result.stdout.strip()
        if username and username != "%USERNAME%":
            return username
    except Exception:
        pass

    # Fallback: scan /mnt/c/Users/
    try:
        users_dir = Path("/mnt/c/Users")
        for p in users_dir.iterdir():
            if p.is_dir() and (p / "AppData").exists():
                return p.name
    except Exception:
        pass

    return ""


# Singleton instance for the hook module
# Singleton instances for the hook module (keyed by state_file path)
_writers: dict[str, PresenceWriter] = {}


def get_writer(state_file: Optional[Path] = None, session_id: str = "") -> PresenceWriter:
    """Get or create the PresenceWriter for the given state file.

    The state file path alone is not enough on WSL: Windows mirroring uses the
    writer's session_id to choose the mirror filename. Without passing it here,
    per-session WSL files collapse back into the legacy hermes_presence.json
    mirror and the Windows monitor loses session-specific activity.
    """
    sf = Path(state_file) if state_file else DEFAULT_STATE_FILE
    key = str(sf)
    if key not in _writers:
        _writers[key] = PresenceWriter(sf, session_id=session_id)
    elif session_id and not _writers[key]._session_id:
        _writers[key]._session_id = session_id
    return _writers[key]
