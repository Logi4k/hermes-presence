"""
Hermes Presence — Cross-platform Discord Rich Presence for Hermes Agent.

Monitors running Hermes sessions and displays live activity in Discord
regardless of OS (Linux, macOS, Windows, or WSL2).

Usage:
    hermes-presence install     # One-command setup
    hermes-presence run         # Run monitor in foreground
    hermes-presence config      # Show/edit configuration
"""

__version__ = "3.0.0"

from .writer import PresenceWriter
from .monitor import UnifiedMonitor, create_monitor
from .config import load_config, save_config, PresenceConfig, is_disabled
from .hook import setup_presence, auto_setup

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
