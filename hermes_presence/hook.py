"""
Hermes hook — one-liner to enable Discord Rich Presence.

Add this line after AIAgent initialization in cli.py (around line 3606):

    from hermes_presence.hook import setup_presence
    _presence = setup_presence(agent, model=..., provider=..., source="cli")

Or use the lazy auto-detect version (recommended):
    from hermes_presence.hook import auto_setup
    _presence = auto_setup(agent)
"""

import logging
import os

logger = logging.getLogger(__name__)


def _auto_detect_wsl():
    """Detect WSL2 and set WINDOWS_USER env var for cross-filesystem state output."""
    if os.environ.get("WINDOWS_USER"):
        return  # Already set
    try:
        with open("/proc/version", "r") as f:
            if "microsoft" in f.read().lower() or "wsl" in f.read().lower():
                # Running in WSL — discover Windows username from /mnt/c/Users/
                users_dir = "/mnt/c/Users"
                if os.path.isdir(users_dir):
                    for name in os.listdir(users_dir):
                        user_path = os.path.join(users_dir, name)
                        if os.path.isdir(user_path) and name not in ("Public", "Default", "All Users", "desktop.ini"):
                            os.environ["WINDOWS_USER"] = name
                            logger.debug("Auto-detected WSL Windows user: %s", name)
                            return
    except Exception:
        pass


def setup_presence(
    agent,
    session_id: str = "",
    source: str = "cli",
    model: str = "",
    provider: str = "",
):
    """
    Hook presence writer into an AIAgent instance.

    Args:
        agent: AIAgent instance
        session_id: Hermes session ID
        source: 'cli', 'telegram', 'discord', etc.
        model: Model name
        provider: Provider name
    """
    try:
        from hermes_presence.writer import PresenceWriter
    except ImportError:
        logger.debug("hermes-presence not installed, skipping")
        return None

    # Auto-detect WSL2 Windows user for dual-path state file output
    _auto_detect_wsl()

    writer = PresenceWriter(
        session_id=session_id or getattr(agent, "session_id", ""),
        source=source,
        model=model or getattr(agent, "model", ""),
        provider=provider or getattr(agent, "provider", ""),
    )

    # Hook tool completion
    agent.tool_complete_callback = writer

    # Also hook the existing tool_complete_callback if set
    # (chain with original if needed)
    logger.info("Hermes Presence writer hooked (session=%s)", writer._session_id)
    return writer


def auto_setup(agent):
    """Auto-detect settings from agent and enable presence."""
    return setup_presence(
        agent=agent,
        session_id=getattr(agent, "session_id", ""),
        source=getattr(agent, "platform", "cli"),
        model=getattr(agent, "model", ""),
        provider=getattr(agent, "provider", ""),
    )
