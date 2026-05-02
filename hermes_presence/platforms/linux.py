"""
Linux platform launcher — systemd user unit.

Creates: ~/.config/systemd/user/hermes-presence.service
Enables: systemctl --user enable hermes-presence
"""

import os
import subprocess
from pathlib import Path
from . import PlatformLauncher


SYSTEMD_UNIT_NAME = "hermes-presence"
SYSTEMD_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_UNIT_NAME}.service"

SYSTEMD_TEMPLATE = """[Unit]
Description=Hermes Presence — Discord Rich Presence Monitor
After=network.target

[Service]
Type=simple
ExecStart={python_path} -m hermes_presence.monitor
Environment=HERMES_DISCORD_CLIENT_ID={client_id}
Environment=HERMES_PRESENCE_STATE={state_file}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


class LinuxLauncher(PlatformLauncher):
    """systemd user unit launcher."""

    def _python_path(self) -> str:
        """Find the Python interpreter to use."""
        # Prefer the venv that hermes-presence was installed into
        for candidate in [
            os.environ.get("VIRTUAL_ENV", ""),
            Path.home() / ".hermes" / "hermes-agent" / "venv",
        ]:
            if candidate and Path(candidate).exists():
                py = Path(candidate) / "bin" / "python3"
                if py.exists():
                    return str(py)
                py = Path(candidate) / "bin" / "python"
                if py.exists():
                    return str(py)
        return "python3"

    def install(self) -> bool:
        SYSTEMD_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)

        unit = SYSTEMD_TEMPLATE.format(
            python_path=self._python_path(),
            client_id=self.client_id,
            state_file=self.state_file,
        )

        SYSTEMD_UNIT_PATH.write_text(unit)

        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True, timeout=10
            )
            subprocess.run(
                ["systemctl", "--user", "enable", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
            subprocess.run(
                ["systemctl", "--user", "start", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(
                ["systemctl", "--user", "stop", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
            subprocess.run(
                ["systemctl", "--user", "disable", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        SYSTEMD_UNIT_PATH.unlink(missing_ok=True)

        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        return not SYSTEMD_UNIT_PATH.exists()

    def is_installed(self) -> bool:
        return SYSTEMD_UNIT_PATH.exists()

    def start(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "start", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "stop", SYSTEMD_UNIT_NAME],
                capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", SYSTEMD_UNIT_NAME],
                capture_output=True, text=True, timeout=5
            )
            running = result.stdout.strip() == "active"

            if running:
                prop = subprocess.run(
                    ["systemctl", "--user", "show", SYSTEMD_UNIT_NAME, "-p", "MainPID"],
                    capture_output=True, text=True, timeout=5
                )
                for line in prop.stdout.splitlines():
                    if line.startswith("MainPID="):
                        try:
                            pid = int(line.split("=", 1)[1])
                        except ValueError:
                            pass
        except Exception:
            pass

        return {
            "running": running,
            "auto_start": self.is_installed(),
            "pid": pid,
        }
