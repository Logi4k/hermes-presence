"""
Hermes Presence — Cross-platform Discord Rich Presence for Hermes Agent.

Monitors running Hermes sessions and displays live activity in Discord
regardless of OS (Linux, macOS, Windows, or WSL2).

Usage:
    hermes-presence install     # One-command setup
    hermes-presence run         # Run monitor in foreground
    hermes-presence config      # Show/edit configuration
"""

__version__ = "3.4.0"

# Keep package import cheap. Shell hooks import hermes_presence.config on every
# tool/LLM event, so eager imports of monitor/pypresence make real-time presence
# updates miss their timeout budget. Public symbols stay available via lazy lookup.

__all__ = [
    "PresenceWriter",
    "UnifiedMonitor",
    "create_monitor",
    "load_config",
    "save_config",
    "PresenceConfig",
    "is_disabled",
    "setup_presence",
    "auto_setup",
]


def __getattr__(name):
    if name in {"PresenceConfig", "is_disabled", "load_config", "save_config"}:
        from . import config as _config
        return getattr(_config, name)
    if name in {"auto_setup", "setup_presence"}:
        from . import hook as _hook
        return getattr(_hook, name)
    if name in {"UnifiedMonitor", "create_monitor"}:
        from . import monitor as _monitor
        return getattr(_monitor, name)
    if name == "PresenceWriter":
        from .writer import PresenceWriter
        return PresenceWriter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
