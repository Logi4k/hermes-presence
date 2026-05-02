"""
macOS platform launcher — launchd plist.

Creates: ~/Library/LaunchAgents/com.hermes.presence.plist
Loads: launchctl load ~/Library/LaunchAgents/com.hermes.presence.plist
"""

import os
import subprocess
from pathlib import Path
from . import PlatformLauncher


PLIST_LABEL = "com.hermes.presence"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

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

    def _python_path(self) -> str:
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
        return "/usr/bin/python3"

    @property
    def _log_dir(self) -> Path:
        path = Path.home() / "Library" / "Logs" / "hermes-presence"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def install(self) -> bool:
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

        plist = PLIST_TEMPLATE.format(
            label=PLIST_LABEL,
            python_path=self._python_path(),
            client_id=self.client_id,
            state_file=self.state_file,
            log_dir=self._log_dir,
        )

        PLIST_PATH.write_text(plist)

        try:
            subprocess.run(
                ["launchctl", "load", str(PLIST_PATH)],
                capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "unload", str(PLIST_PATH)],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

        PLIST_PATH.unlink(missing_ok=True)
        return not PLIST_PATH.exists()

    def is_installed(self) -> bool:
        return PLIST_PATH.exists()

    def start(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "start", PLIST_LABEL],
                capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            subprocess.run(
                ["launchctl", "stop", PLIST_LABEL],
                capture_output=True, timeout=10
            )
            return True
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None
        try:
            result = subprocess.run(
                ["launchctl", "list", PLIST_LABEL],
                capture_output=True, text=True, timeout=5
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
