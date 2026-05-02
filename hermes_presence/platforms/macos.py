"""
macOS platform launcher — launchd plist.

Creates: ~/Library/LaunchAgents/com.hermes.presence.plist
Loads: launchctl load ~/Library/LaunchAgents/com.hermes.presence.plist
"""

import subprocess
import sys
from pathlib import Path
from . import PlatformLauncher


PLIST_LABEL_BASE = "com.hermes.presence"

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>hermes_presence.monitor</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HERMES_DISCORD_CLIENT_ID</key>
        <string>{client_id}</string>
        <key>HERMES_PRESENCE_STATE</key>
        <string>{state_file}</string>
        <key>HERMES_PROFILE</key>
        <string>{profile}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/hermes-presence.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/hermes-presence.err</string>
</dict>
</plist>
"""


class MacOSLauncher(PlatformLauncher):
    """launchd plist launcher."""

    def __init__(self, client_id: str, state_file: str, profile: str = "main"):
        super().__init__(client_id, state_file)
        self.profile = profile

    @property
    def _label(self) -> str:
        if self.profile == "main":
            return PLIST_LABEL_BASE
        return f"{PLIST_LABEL_BASE}.{self.profile}"

    @property
    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self._label}.plist"

    @property
    def _log_dir(self) -> Path:
        path = Path.home() / "Library" / "Logs" / "hermes-presence"
        path.mkdir(parents=True, exist_ok=True)
        return path

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
        return "/usr/bin/python3"

    def install(self) -> bool:
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)

        plist = PLIST_TEMPLATE.format(
            label=self._label,
            python_path=self._python_path(),
            client_id=self.client_id,
            state_file=self.state_file,
            profile=self.profile,
            log_dir=self._log_dir,
        )

        self._plist_path.write_text(plist)

        try:
            subprocess.run(
                ["launchctl", "load", str(self._plist_path)],
                capture_output=True,
                timeout=10,
            )
            return True
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "unload", str(self._plist_path)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

        self._plist_path.unlink(missing_ok=True)
        return not self._plist_path.exists()

    def is_installed(self) -> bool:
        return self._plist_path.exists()

    def start(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "start", self._label], capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "stop", self._label], capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None
        try:
            result = subprocess.run(
                ["launchctl", "list", self._label],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Output: {"PID" = 12345; ...} or "Could not find service"
            for line in result.stdout.splitlines():
                if '"PID"' in line:
                    running = True
                    try:
                        pid_str = line.split("=")[1].strip().rstrip(";")
                        pid = int(pid_str)
                    except (ValueError, IndexError):
                        pass
                    break
        except Exception:
            pass

        return {
            "running": running,
            "auto_start": self.is_installed(),
            "pid": pid,
        }
