"""
Abstract base class for platform-specific launcher setup.

Each platform subclass implements:
- install(): Create and enable the auto-start mechanism
- uninstall(): Remove the auto-start mechanism
- is_installed(): Check if already set up
- start(): Launch the monitor now
- stop(): Stop the running monitor
"""

from abc import ABC, abstractmethod
from pathlib import Path


class PlatformLauncher(ABC):
    """Base class for OS-specific launcher setup."""

    def __init__(self, client_id: str, state_file: Path):
        self.client_id = client_id
        self.state_file = state_file

    @abstractmethod
    def install(self) -> bool:
        """Install and enable auto-start. Returns True on success."""
        ...

    @abstractmethod
    def uninstall(self) -> bool:
        """Remove auto-start. Returns True on success."""
        ...

    @abstractmethod
    def is_installed(self) -> bool:
        """Check if auto-start is configured."""
        ...

    @abstractmethod
    def start(self) -> bool:
        """Start the monitor process now."""
        ...

    @abstractmethod
    def stop(self) -> bool:
        """Stop the running monitor process."""
        ...

    @abstractmethod
    def status(self) -> dict:
        """Return status dict: {running: bool, auto_start: bool, pid: int|None}."""
        ...
