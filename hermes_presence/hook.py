"""
Hermes CLI hook for Discord Rich Presence.

Integrates with Hermes event system to write presence state
at every tool call. Enhanced for v3.0 with:
- Model/provider detection
- Error state callbacks
- Thinking/streaming indicator
- Cron job detection
- Orchestrator detection
- Kanban phase tracking
- WSL-to-Windows state mirroring

Install: `hermes plugin add hermes-presence`
Or manual: add hook to config.yaml
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from .config import get_state_file_path, is_disabled
from .writer import get_writer

# Check for cron markers
_IS_CRON = any(
    os.environ.get(v, "").strip()
    for v in [
        "HERMES_CRON_JOB_ID",
        "CRON_JOB_ID",
        "HERMES_SCHEDULED",
    ]
)

# Check for orchestrator
_IS_ORCHESTRATOR = os.environ.get("HERMES_ORCHESTRATOR", "").strip() == "1"

# Check for profile
_PROFILE = os.environ.get("HERMES_PROFILE", "main")

# Profile-specific state file path
_STATE_FILE = get_state_file_path(_PROFILE)


def on_session_start(context: dict):
    """
    Called when a Hermes conversation session starts (or user sends first message).

    context contains:
        model: str        - model name (e.g., "deepseek-v4-pro")
        provider: str     - provider name (e.g., "deepseek")
        profile: str      - Hermes profile name
        thinking: bool    - whether model is streaming
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    model = context.get("model", os.environ.get("HERMES_MODEL", "unknown"))
    provider = context.get("provider", os.environ.get("HERMES_PROVIDER", "unknown"))
    thinking = context.get("thinking", False)

    writer.set_session(
        model=model,
        provider=provider,
        thinking=thinking,
        is_cron=_IS_CRON,
        is_orchestrator=_IS_ORCHESTRATOR,
        profile=_PROFILE,
    )

    _mirror_to_windows_if_wsl()


def on_tool_start(context: dict):
    """
    Called when a tool execution begins.

    context contains:
        tool_name: str
        params: dict
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    tool_name = context.get("tool_name", "unknown")
    params = context.get("params", {})

    writer.tool_call(tool_name, params)

    _mirror_to_windows_if_wsl()


def on_tool_end(context: dict):
    """
    Called when a tool execution completes.
    Returns to idle if no other tool is active.
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    # If successful, go back to idle
    error = context.get("error")
    if error:
        error_msg = str(error)[:100] if error else "Tool error"
        writer.error(error_msg)
    else:
        writer.idle()

    # Track files modified
    tool_name = context.get("tool_name", "")
    if tool_name in ("write_file", "patch", "skill_manage"):
        writer.file_modified()

    _mirror_to_windows_if_wsl()


def on_tool_error(context: dict):
    """
    Called when a tool execution fails with an error.
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    error_msg = str(context.get("error", "") or "Unknown error")[:100]
    writer.error(error_msg)

    _mirror_to_windows_if_wsl()


def on_thinking(context: dict):
    """
    Called when the model begins streaming/thinking.

    This is triggered during the generation phase before the
    assistant's response is sent.
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)
    writer.thinking()

    _mirror_to_windows_if_wsl()


def on_model_info(context: dict):
    """
    Called when model/provider info becomes available.

    context contains:
        model: str
        provider: str
        cost_usd: float (optional)
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    model = context.get("model", "")
    provider = context.get("provider", "")
    cost = context.get("cost_usd")

    if model or provider:
        writer.set_session(
            model=model or writer._current_model,
            provider=provider or writer._current_provider,
            is_cron=_IS_CRON,
            is_orchestrator=_IS_ORCHESTRATOR,
        )

    if cost is not None:
        writer.add_cost(cost)

    _mirror_to_windows_if_wsl()


def on_subagent_change(context: dict):
    """
    Called when sub-agent count changes (spawned or completed).

    context contains:
        count: int      - current subagent count
        delta: int      - change (+1 for spawn, -1 for complete)
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    count = context.get("count", 0)
    writer.set_subagent_count(count)

    # If currently idle, refresh state to show orchestrating/idle
    if not writer._current_tool:
        if count > 0:
            writer._write_state(
                state="orchestrating",
                detail=f"Monitoring {count} sub-agent(s)",
                large_image="status_monitoring",
            )
        else:
            writer.idle()

    _mirror_to_windows_if_wsl()


def on_kanban_phase(context: dict):
    """
    Called when the kanban phase changes.

    context contains:
        phase: str | None   - current phase or None to clear
    """
    if is_disabled():
        return

    writer = get_writer(_STATE_FILE)

    phase = context.get("phase")
    writer.set_kanban(phase)

    _mirror_to_windows_if_wsl()


def on_session_end(context: dict):
    """
    Called when the session ends.
    Writes a rich summary with session stats (tools used, files modified, cost, duration).
    """
    writer = get_writer(_STATE_FILE)
    writer.session_summary()
    _mirror_to_windows_if_wsl()


def on_shutdown(context: dict):
    """
    Called when Hermes shuts down.
    """
    writer = get_writer(_STATE_FILE)
    writer.shutdown()
    _mirror_to_windows_if_wsl()


# --- WSL to Windows Bridge ---


def _mirror_to_windows_if_wsl():
    """Mirror state file to Windows side if running on WSL."""
    if not _is_wsl():
        return

    try:
        state_file = _STATE_FILE
        if not state_file.exists():
            return

        # Read state
        content = state_file.read_text(encoding="utf-8")

        # Write to Windows appdata via /mnt/c/
        windows_username = _get_windows_username()
        if not windows_username:
            return

        windows_appdata = Path("/mnt/c/Users") / windows_username / "AppData" / "Roaming"
        # Profile-specific Windows mirror path
        if _PROFILE == "main":
            mirror_name = "hermes_presence.json"
        else:
            mirror_name = f"{_PROFILE}_presence.json"
        windows_state = windows_appdata / mirror_name
        windows_state.parent.mkdir(parents=True, exist_ok=True)

        # Write with safe encoding (avoid em dash)
        safe_content = content.replace("\u2014", "--").replace("\u2013", "-")

        with open(windows_state, "w", encoding="utf-8") as f:
            f.write(safe_content)

    except Exception:
        pass  # Silent fail — mirror is best-effort


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

    # Fallback: cmd.exe (fast, but may fail for Unicode names)
    try:
        username = os.popen("cmd.exe /c echo %USERNAME% 2>nul").read().strip()
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


def _load_hermes_hook():
    """
    Compatibility shim for Hermes CLI's hook loading mechanism.

    Hermes calls this function when loading the plugin.
    Returns a dict of hook_name -> callable.
    """
    return {
        "on_session_start": on_session_start,
        "on_tool_start": on_tool_start,
        "on_tool_end": on_tool_end,
        "on_tool_error": on_tool_error,
        "on_thinking": on_thinking,
        "on_model_info": on_model_info,
        "on_subagent_change": on_subagent_change,
        "on_kanban_phase": on_kanban_phase,
        "on_session_end": on_session_end,
        "on_shutdown": on_shutdown,
    }


# Standalone entry — auto-setup
def auto_setup(agent=None):
    """Detect environment and wire up hooks automatically.

    Args:
        agent: AIAgent instance (optional). If provided, extracts model/provider
               and registers tool-call hooks via monkey-patching.
    Returns:
        PresenceWriter instance or None if disabled.
    """
    if is_disabled():
        return None

    writer = get_writer(_STATE_FILE)

    # Extract model/provider from agent if available
    model = os.environ.get("HERMES_MODEL", "unknown")
    provider = os.environ.get("HERMES_PROVIDER", "unknown")

    if agent is not None:
        try:
            model = getattr(agent, "model", model) or model
            provider = getattr(agent, "provider", provider) or provider
        except Exception:
            pass

    writer.set_session(
        model=model,
        provider=provider,
        is_cron=_IS_CRON,
        is_orchestrator=_IS_ORCHESTRATOR,
        profile=_PROFILE,
    )
    writer.idle()
    _mirror_to_windows_if_wsl()

    return writer


def register_cli_hooks(writer, callbacks: dict):
    """Wrap CLI callbacks to send presence updates on tool calls.

    Args:
        writer: PresenceWriter instance from auto_setup()
        callbacks: dict with optional keys:
            'tool_start': callable(tool_name, args)
            'tool_complete': callable(tool_name, success, error_msg)
            'tool_progress': callable(...)
            'thinking': callable()
    Returns:
        dict of wrapped callbacks (same keys). Use these in place of originals.
    """
    from typing import Any

    wrapped: dict[str, Any] = {}

    orig_start = callbacks.get("tool_start")
    orig_complete = callbacks.get("tool_complete")
    orig_thinking = callbacks.get("thinking")

    def _wrapped_tool_start(tool_name, args=None):
        writer.tool_call(tool_name, args)
        if orig_start:
            orig_start(tool_name, args)

    def _wrapped_tool_complete(tool_name, success=True, error_msg=None):
        if success:
            writer.idle()
        else:
            writer.error(error_msg or f"Tool {tool_name} failed")
        if orig_complete:
            orig_complete(tool_name, success, error_msg)

    def _wrapped_thinking():
        writer.thinking()
        if orig_thinking:
            orig_thinking()

    if orig_start:
        wrapped["tool_start"] = _wrapped_tool_start
    if orig_complete:
        wrapped["tool_complete"] = _wrapped_tool_complete
    if orig_thinking:
        wrapped["thinking"] = _wrapped_thinking

    return wrapped


def setup_presence(config_path: Optional[Path] = None):
    """
    Legacy setup function — deprecated, use auto_setup().

    Kept for backward compatibility with existing configurations.
    """
    auto_setup()
