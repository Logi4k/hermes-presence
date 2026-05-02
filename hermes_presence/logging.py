"""
Structured file logging for hermes-presence.

Writes JSON-lines logs to a configurable file path.
Enabled via config (advanced.log_file) or CLI (--log-file).
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class PresenceLogger:
    """JSON-lines logger for hermes-presence events."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._logger = logging.getLogger("hermes-presence")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        # Console handler (always active for stderr)
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.WARNING)
        console.setFormatter(LOG_FORMAT)
        self._logger.addHandler(console)

        # File handler (optional)
        if log_path:
            self._enable_file(log_path)

    def _enable_file(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(LOG_FORMAT)
        self._logger.addHandler(fh)
        self.log_path = log_path
        self._logger.info("Logging started")

    def event(self, event_type: str, **kwargs):
        """Log a structured event as a JSON line."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **kwargs,
        }
        self._logger.debug(json.dumps(entry, default=str))

    # Convenience methods matching monitor lifecycle
    def startup(self, client_id: str, platform: str, state_file: Path):
        self.event(
            "startup",
            client_id=client_id[:8] + "...",
            platform=platform,
            state_file=str(state_file),
        )

    def connected(self, pipe_num: int, total_pipes: int):
        self.event("connected", pipe=pipe_num, total_pipes=total_pipes)

    def disconnected(self, pipe_num: int, reason: str = ""):
        self.event("disconnected", pipe=pipe_num, reason=reason)

    def pushed(self, state: str, detail: str, tool: str = ""):
        self.event("pushed", state=state, detail=detail, tool=tool)

    def error(self, message: str, **kwargs):
        self._logger.error(message, extra=kwargs)

    def warning(self, message: str, **kwargs):
        self._logger.warning(message, extra=kwargs)

    def info(self, message: str, **kwargs):
        self._logger.info(message, extra=kwargs)

    def debug(self, message: str, **kwargs):
        self._logger.debug(message, extra=kwargs)


# Singleton
_log_instance: Optional[PresenceLogger] = None


def get_logger(log_path: Optional[Path] = None) -> PresenceLogger:
    global _log_instance
    if _log_instance is None:
        _log_instance = PresenceLogger(log_path)
    elif log_path and _log_instance.log_path != log_path:
        _log_instance._enable_file(log_path)
    return _log_instance
