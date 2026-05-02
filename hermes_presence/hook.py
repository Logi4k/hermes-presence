"""
Hermes hook — one-liner to enable Discord Rich Presence.

Add this line after AIAgent initialization in cli.py (around line 3606):

    from hermes_presence.hook import setup_presence
    _presence = setup_presence(agent, model=..., provider=..., source="cli")

Or use the lazy auto-detect version (recommended):
    from hermes_presence.hook import auto_setup
    _presence = auto_setup(agent)

For clinical-monitor profile:
    _presence = auto_setup(agent, profile="clinical")
    # This writes to ~/.hermes/state/presence-clinical.json
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _auto_detect_wsl():
    """Detect WSL2 and set WINDOWS_USER env var for cross-filesystem state output."""
    if os.environ.get("WINDOWS_USER"):
        return  # Already set
    try:
        with open("/proc/version", "r") as f:
            content = f.read().lower()
            if "microsoft" in content or "wsl" in content:
                # Running in WSL — discover Windows username from /mnt/c/Users/
                users_dir = "/mnt/c/Users"
                if os.path.isdir(users_dir):
                    for name in os.listdir(users_dir):
                        user_path = os.path.join(users_dir, name)
                        if os.path.isdir(user_path) and name not in ("Public", "Default", "Default User", "All Users", "desktop.ini"):
                            os.environ["WINDOWS_USER"] = name
                            logger.debug("Auto-detected WSL Windows user: %s", name)
                            return
    except Exception:
        pass


def _state_file_for_profile(profile: str) -> Path:
    """Return the state file path for a given profile.
    
    profile="main" → ~/.hermes/state/presence.json
    profile="clinical" → ~/.hermes/state/presence-clinical.json
    """
    if profile and profile != "main":
        return Path.home() / ".hermes" / "state" / f"presence-{profile}.json"
    return Path.home() / ".hermes" / "state" / "presence.json"


def setup_presence(
    agent,
    session_id: str = "",
    source: str = "cli",
    model: str = "",
    provider: str = "",
    profile: str = "main",
):
    """
    Hook presence writer into an AIAgent instance.

    Args:
        agent: AIAgent instance
        session_id: Hermes session ID
        source: 'cli', 'telegram', 'discord', etc.
        model: Model name
        provider: Provider name
        profile: 'main' (default) or 'clinical' — controls state file path
    """
    # Auto-detect WSL2 Windows user BEFORE importing writer.py,
    # because writer.py resolves WINDOWS_STATE_FILE at module level.
    _auto_detect_wsl()

    try:
        from hermes_presence.writer import PresenceWriter
    except ImportError:
        logger.debug("hermes-presence not installed, skipping")
        return None

    state_file = _state_file_for_profile(profile)

    writer = PresenceWriter(
        state_file=state_file,
        session_id=session_id or getattr(agent, "session_id", ""),
        source=source,
        model=model or getattr(agent, "model", ""),
        provider=provider or getattr(agent, "provider", ""),
        profile=profile,
    )

    # Chain (don't overwrite) tool callbacks so TUI callbacks survive.
    _orig_tool_start = getattr(agent, "tool_start_callback", None)
    _orig_tool_complete = getattr(agent, "tool_complete_callback", None)
    _orig_tool_progress = getattr(agent, "tool_progress_callback", None)

    def _chain_start(tc_id, name, args):
        writer.on_tool_start(name, args)
        if _orig_tool_start:
            _orig_tool_start(tc_id, name, args)

    def _chain_complete(tc_id, name, args, result):
        writer.on_tool_complete(tc_id, name, args, result)
        if _orig_tool_complete:
            _orig_tool_complete(tc_id, name, args, result)

    def _chain_progress(event_type, name=None, preview=None, args=None, **kwargs):
        if event_type == "tool.started" and name:
            writer.on_tool_start(name, args)
        if _orig_tool_progress:
            _orig_tool_progress(event_type, name, preview, args, **kwargs)

    agent.tool_start_callback = _chain_start
    agent.tool_complete_callback = _chain_complete
    agent.tool_progress_callback = _chain_progress

    logger.info("Hermes Presence writer hooked (session=%s, profile=%s)", writer._session_id, profile)
    return writer


def auto_setup(agent, profile: str = "main"):
    """Auto-detect settings from agent and enable presence."""
    return setup_presence(
        agent=agent,
        session_id=getattr(agent, "session_id", ""),
        source=getattr(agent, "platform", "cli"),
        model=getattr(agent, "model", ""),
        provider=getattr(agent, "provider", ""),
        profile=profile,
    )
