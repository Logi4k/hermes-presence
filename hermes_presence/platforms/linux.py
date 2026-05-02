"""
Linux platform launcher — systemd user unit.

Creates: ~/.config/systemd/user/hermes-presence.service
Enables: systemctl --user enable hermes-presence
"""

import subprocess
import sys
from pathlib import Path
from . import PlatformLauncher


SYSTEMD_UNIT_BASE = "hermes-presence"

SYSTEMD_TEMPLATE = """[Unit]
Description=Hermes Presence — Discord Rich Presence Monitor ({profile})
After=network.target

[Service]
Type=simple
ExecStart={python_path} -m hermes_presence.monitor
Environment=HERMES_DISCORD_CLIENT_ID={client_id}
Environment=HERMES_PRESENCE_STATE={state_file}
Environment=HERMES_PROFILE={profile}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


class LinuxLauncher(PlatformLauncher):
    """systemd user unit launcher."""

    def __init__(self, client_id: str, state_file: str, profile: str = "main"):
        super().__init__(client_id, state_file)
        self.profile = profile

    @property
    def _unit_name(self) -> str:
        if self.profile == "main":
            return SYSTEMD_UNIT_BASE
        return f"{SYSTEMD_UNIT_BASE}@{self.profile}"

    @property
    def _unit_path(self) -> Path:
        return (
            Path.home() / ".config" / "systemd" / "user" / f"{self._unit_name}.service"
        )

    def _python_path(self) -> str:
        """Find the Python interpreter to use."""
        # 1. Current Python executable
        if sys.executable:
            return sys.executable
        # 2. hermes-agent venv
        venv_py = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3"
        if venv_py.exists():
            return str(venv_py)
        # 3. which python3
        result = subprocess.run(["which", "python3"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # 4. Fallback
        return "python3"

    def install(self) -> bool:
        self._unit_path.parent.mkdir(parents=True, exist_ok=True)

        unit = SYSTEMD_TEMPLATE.format(
            python_path=self._python_path(),
            client_id=self.client_id,
            state_file=self.state_file,
            profile=self.profile,
        )

        self._unit_path.write_text(unit)

        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["systemctl", "--user", "enable", self._unit_name],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["systemctl", "--user", "start", self._unit_name],
                capture_output=True,
                timeout=10,
            )
            return True
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(
                ["systemctl", "--user", "stop", self._unit_name],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["systemctl", "--user", "disable", self._unit_name],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        self._unit_path.unlink(missing_ok=True)

        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        return not self._unit_path.exists()

    def is_installed(self) -> bool:
        return self._unit_path.exists()

    def start(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "start", self._unit_name],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "stop", self._unit_name],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", self._unit_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            running = result.stdout.strip() == "active"

            if running:
                prop = subprocess.run(
                    ["systemctl", "--user", "show", self._unit_name, "-p", "MainPID"],
                    capture_output=True,
                    text=True,
                    timeout=5,
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
