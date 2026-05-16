"""
Windows platform launcher — Task Scheduler + shell:startup.

Creates a Windows Scheduled Task (triggered at user logon) and/or
a hidden launcher in the Startup folder for auto-start.

On WSL2: commands run through powershell.exe bridge automatically.
"""

import ntpath
import os
import subprocess
import time
from pathlib import Path

from . import PlatformLauncher

TASK_NAME = "HermesPresence"

_IGNORED_WINDOWS_USER_DIRS = {
    "All Users",
    "Default",
    "Default User",
    "Public",
    "WDAGUtilityAccount",
    "desktop.ini",
}


def _detect_wsl() -> bool:
    """Check if running inside WSL without depending on later module globals."""
    try:
        with open("/proc/version") as f:
            content = f.read().lower()
            return "microsoft" in content or "wsl" in content
    except Exception:
        return False


def _windows_user_candidates() -> list[str]:
    """Return likely real Windows usernames, preferring the active session."""
    candidates: list[str] = []

    def add(name: str | None) -> None:
        if name and name not in _IGNORED_WINDOWS_USER_DIRS and name not in candidates:
            candidates.append(name)

    add(os.environ.get("WINDOWS_USER"))
    add(os.environ.get("USERNAME"))

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        add(Path(userprofile).name)

    if _detect_wsl():
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "$env:USERNAME"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            add(result.stdout.strip())
        except Exception:
            pass

    try:
        for entry in sorted(Path("/mnt/c/Users").iterdir()):
            is_real_user = (
                entry.is_dir()
                and not entry.name.startswith(".")
                and entry.name not in _IGNORED_WINDOWS_USER_DIRS
            )
            if is_real_user:
                if (entry / "AppData" / "Roaming").exists():
                    add(entry.name)
    except Exception:
        pass

    return candidates


def _resolve_appdata() -> str:
    """Resolve %APPDATA% — works on native Windows, WSL, and remote SSH tunnel."""
    # 1. Native Windows: %APPDATA% env var is set
    raw = os.environ.get("APPDATA")
    if raw and Path(raw).exists():
        return raw

    # 2. WSL: prefer active Windows user, then scan real user directories.
    for username in _windows_user_candidates():
        candidate = Path("/mnt/c/Users") / username / "AppData" / "Roaming"
        if candidate.exists():
            return str(candidate)

    # 3. Last resort — WSL-side fallback (functional for mirror writes via hook.py)
    return os.path.expanduser("~/.hermes/state")


def _find_windows_username() -> str:
    """Discover the Windows username from WSL or native env."""
    candidates = _windows_user_candidates()
    if candidates:
        return candidates[0]
    return os.environ.get("USER", "unknown")


_APPDATA = _resolve_appdata()
STARTUP_DIR = Path(_APPDATA) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
MONITOR_TARGET = Path(_APPDATA) / "hermes_presence_monitor.py"

# Cache for python path discovery
_CACHED_PYTHON: str | None = None


def _wsl_to_win_path(wsl_path: str) -> str:
    """Convert /mnt/c/Users/... to C:\\Users\\..."""
    if wsl_path.startswith("/mnt/"):
        drive = wsl_path[5:6].upper()
        rest = wsl_path[7:]
        sep = "\\"
        return f"{drive}:{sep}{rest.replace('/', sep)}"
    return wsl_path.replace("/", "\\")


def _win_to_wsl_path(win_path: str) -> str:
    """Convert C:\\Users\\... to /mnt/c/Users/... when checking from WSL."""
    if len(win_path) >= 3 and win_path[1:3] in {":\\", ":/"}:
        drive = win_path[0].lower()
        rest = win_path[3:].replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return win_path


def _windows_path_exists(path: str) -> bool:
    """Check Windows paths correctly when this launcher is running inside WSL."""
    try:
        if Path(path).exists():
            return True
    except Exception:
        pass
    if _is_wsl():
        try:
            return Path(_win_to_wsl_path(path)).exists()
        except Exception:
            return False
    return False


def _current_reasoning_effort() -> str:
    """Best-effort fallback reasoning level to bake into the Windows monitor."""
    for var in ("HERMES_REASONING_EFFORT", "HERMES_REASONING"):
        value = os.environ.get(var, "").strip()
        if value:
            return value

    try:
        import yaml  # type: ignore[import-untyped]

        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            value = str((cfg.get("agent") or {}).get("reasoning_effort", "") or "").strip()
            if value:
                return value
    except Exception:
        pass

    return ""


def _pythonw_path(python_path: str) -> str:
    """Prefer pythonw.exe on Windows so the monitor never owns a console."""
    clean = python_path.replace("\\\\", "\\")
    if _is_wsl() and clean.startswith("/mnt/"):
        clean = _wsl_to_win_path(clean)
    if clean.lower() == "python":
        return "pythonw"

    basename = ntpath.basename(clean).lower()
    if basename == "pythonw.exe":
        return clean
    if basename == "python.exe":
        candidate = ntpath.join(ntpath.dirname(clean), "pythonw.exe")
        return candidate if _windows_path_exists(candidate) else clean
    return clean


def _startup_launcher_vbs_content(python_path: str, monitor_path: str) -> str:
    """Create a no-console Startup launcher for Windows logon."""
    command = f'"{_pythonw_path(python_path)}" "{monitor_path}"'
    escaped_command = command.replace('"', '""')
    return (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run "{escaped_command}", 0, False\n'
    )


def _is_wsl() -> bool:
    """Check if running inside WSL."""
    return _detect_wsl()


def _run_win(cmd: list, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a command on Windows — auto-bridges when in WSL."""
    if _is_wsl():
        # Build PowerShell command with proper quoting
        ps_cmd_parts = []
        for c in cmd:
            if " " in str(c):
                ps_cmd_parts.append(f'"{c}"')
            else:
                ps_cmd_parts.append(str(c))
        ps_line = " ".join(ps_cmd_parts)
        full_cmd = [
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-Command",
            ps_line,
        ]
    else:
        full_cmd = cmd

    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)


class WindowsLauncher(PlatformLauncher):
    """Windows Task Scheduler + shell:startup launcher."""

    def __init__(
        self,
        client_id: str,
        state_file: Path,
        profile: str = "main",
        show_reasoning: bool = False,
        privacy_mode: bool = True,
        tui_only: bool = False,
    ):
        super().__init__(client_id, state_file)
        self.profile = profile
        self.show_reasoning = show_reasoning
        self.privacy_mode = privacy_mode
        self.tui_only = tui_only
        # Task name differs for non-default profiles
        self._task_name = f"{profile.capitalize()}Presence" if profile != "main" else TASK_NAME
        # Monitor target differs for non-default
        self._monitor_target = Path(_APPDATA) / (
            f"{profile}_presence_monitor.py" if profile != "main" else "hermes_presence_monitor.py"
        )
        self._startup_script_name = (
            f"{profile}_presence.vbs" if profile != "main" else "hermes_presence.vbs"
        )
        self._startup_bat_name = (
            f"{profile}_presence.bat" if profile != "main" else "hermes_presence.bat"
        )

    def _legacy_task_names(self) -> tuple[str, ...]:
        if self.profile == "main":
            return ("Hermes Presence Monitor",)
        return (f"Hermes Presence {self.profile.capitalize()}",)

    def _disable_legacy_tasks(self) -> None:
        """Disable old task names so upgrades do not leave duplicate pollers running."""
        for task_name in self._legacy_task_names():
            if task_name == self._task_name:
                continue
            try:
                _run_win(["schtasks", "/Change", "/TN", task_name, "/Disable"], timeout=10)
            except Exception:
                pass

    def _remove_startup_fallback(self) -> None:
        """Remove Startup-folder fallback launchers when Scheduled Task is active."""
        for launcher in (self._startup_script_path(), self._legacy_bat_path()):
            try:
                launcher.unlink(missing_ok=True)
            except Exception:
                pass

        disabled_bat = self._legacy_bat_path().with_suffix(
            self._legacy_bat_path().suffix + ".disabled"
        )
        try:
            disabled_bat.unlink(missing_ok=True)
        except Exception:
            pass

    def _find_python(self) -> str:
        """Locate Python on Windows. Uses cached result, then a priority chain:
        1. Hermes venv (most reliable, has pypresence)
        2. Active Python3 from PATH (via 'where' / powershell)
        3. Common install locations
        4. Bare 'python' fallback (last resort)
        """
        global _CACHED_PYTHON
        if _CACHED_PYTHON:
            return _CACHED_PYTHON

        candidates: list[str] = []

        # 1. Hermes venv — resolve dynamically
        username = _find_windows_username()
        hermes_venv = f"C:\\Users\\{username}\\.hermes\\hermes-agent\\venv\\Scripts\\python.exe"
        if _windows_path_exists(hermes_venv):
            candidates.append(hermes_venv)
        # Also try pipx-style install
        pipx_venv = f"C:\\Users\\{username}\\.hermes\\hermes-agent\\.venv\\Scripts\\python.exe"
        if _windows_path_exists(pipx_venv):
            candidates.append(pipx_venv)

        # 2. Common install locations
        for ver in range(13, 8, -1):  # 3.13 down to 3.9
            for base in [
                f"C:\\Python3{ver}\\python.exe",
                f"C:\\Program Files\\Python3{ver}\\python.exe",
            ]:
                candidates.append(base)

        # 3. System 'where' / PowerShell discovery
        try:
            if _is_wsl():
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-Command",
                        "(Get-Command python -ErrorAction SilentlyContinue).Source",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and "python" in line.lower() and line not in candidates:
                        candidates.insert(0, line)
            else:
                result = subprocess.run(["where", "python"], capture_output=True, text=True, timeout=5)
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and line not in candidates:
                        candidates.insert(0, line)
        except Exception:
            pass

        for c in candidates:
            try:
                if _windows_path_exists(c):
                    _CACHED_PYTHON = c
                    return c
            except Exception:
                pass

        return "python"

    def _monitor_process_name(self) -> str:
        if self.profile == "main":
            return "hermes_presence_monitor"
        return f"{self.profile}_presence_monitor"

    def _startup_script_path(self) -> Path:
        return STARTUP_DIR / self._startup_script_name

    def _legacy_bat_path(self) -> Path:
        return STARTUP_DIR / self._startup_bat_name

    def _start_startup_launcher(self) -> bool:
        startup_script = self._startup_script_path()
        if startup_script.exists():
            win_script_path = _wsl_to_win_path(str(startup_script))
            result = _run_win(["wscript", win_script_path], timeout=10)
            return result.returncode == 0

        legacy_bat = self._legacy_bat_path()
        if legacy_bat.exists():
            win_bat_path = _wsl_to_win_path(str(legacy_bat))
            result = _run_win(["cmd", "/c", win_bat_path], timeout=10)
            return result.returncode == 0

        return False

    def install(self) -> bool:
        """Install via Scheduled Task (most reliable), with shell:startup fallback."""
        python_path = self._find_python()
        hidden_python_path = _pythonw_path(python_path)
        # Convert paths for Windows-native commands
        win_target = _wsl_to_win_path(str(self._monitor_target))

        # Write the monitor runner script to %APPDATA%
        monitor_script = _monitor_script_content(
            client_id=self.client_id,
            state_file=str(self.state_file),
            profile=self.profile,
            fallback_reasoning_effort=_current_reasoning_effort(),
            show_reasoning=self.show_reasoning,
            privacy_mode=self.privacy_mode,
            tui_only=self.tui_only,
        )
        try:
            self._monitor_target.parent.mkdir(parents=True, exist_ok=True)
            self._monitor_target.write_text(monitor_script, encoding="utf-8")
        except Exception:
            pass

        self._disable_legacy_tasks()

        # Method 1: Try Scheduled Task (needs admin on some systems)
        try:
            result = _run_win(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    self._task_name,
                    "/SC",
                    "ONLOGON",
                    "/TR",
                    f'"{hidden_python_path}" "{win_target}"',
                    "/F",
                    "/RL",
                    "LIMITED",
                    "/DELAY",
                    "0000:30",
                ]
            )
            if result.returncode == 0:
                self._remove_startup_fallback()
                _run_win(["schtasks", "/Run", "/TN", self._task_name])
                print("[OK] Scheduled Task created and started")
                return True
            else:
                print(f"[INFO] schtasks unavailable (this is fine): {result.stderr.strip()}")
        except Exception as e:
            print(f"[INFO] schtasks failed (will use startup folder fallback): {e}")

        # Method 2: Fallback — shell:startup .vbs file (no admin needed, no console)
        try:
            startup_script = self._startup_script_path()
            legacy_bat = self._legacy_bat_path()
            py_path_clean = hidden_python_path.replace("\\\\", "\\")
            win_script_path = _wsl_to_win_path(str(startup_script))
            vbs_content = _startup_launcher_vbs_content(py_path_clean, win_target)
            STARTUP_DIR.mkdir(parents=True, exist_ok=True)
            startup_script.write_text(vbs_content)

            # Disable the old .bat fallback if present; otherwise it will still flash cmd.exe.
            if legacy_bat.exists():
                legacy_backup = legacy_bat.with_suffix(legacy_bat.suffix + ".disabled")
                legacy_bat.replace(legacy_backup)

            print(f"[OK] Hidden Startup launcher created at {win_script_path}")

            # Also start it now
            try:
                _run_win(["wscript", win_script_path])
                print("[OK] Monitor started via hidden Startup launcher")
            except Exception as e:
                print(f"[WARN] Could not start via hidden Startup launcher: {e}")

            return True
        except Exception as e:
            print(f"[FAIL] Startup folder fallback also failed: {e}")
            return False

    def uninstall(self) -> bool:
        try:
            _run_win(["schtasks", "/Delete", "/TN", self._task_name, "/F"])
        except Exception:
            pass
        self._monitor_target.unlink(missing_ok=True)
        self._startup_script_path().unlink(missing_ok=True)
        self._legacy_bat_path().unlink(missing_ok=True)
        disabled_bat = self._legacy_bat_path().with_suffix(
            self._legacy_bat_path().suffix + ".disabled"
        )
        disabled_bat.unlink(missing_ok=True)
        return not self.is_installed()

    def is_installed(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Query", "/TN", self._task_name], timeout=5)
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # Check for startup fallback
        startup_script = self._startup_script_path()
        startup_bat = self._legacy_bat_path()
        return startup_script.exists() or startup_bat.exists()

    def start(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Run", "/TN", self._task_name], timeout=10)
            if result.returncode == 0:
                return True
        except Exception:
            pass
        return self._start_startup_launcher()

    def stop(self) -> bool:
        stopped = False
        try:
            result = _run_win(["schtasks", "/End", "/TN", self._task_name], timeout=10)
            stopped = result.returncode == 0
        except Exception:
            pass

        try:
            monitor_name = self._monitor_process_name().replace("'", "''")
            ps_cmd = (
                "Get-WmiObject Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
                f"Where-Object {{ $_.CommandLine -match '{monitor_name}' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $($_.ProcessId) }"
            )
            result = subprocess.run(
                ["powershell.exe" if _is_wsl() else "powershell", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            stopped = stopped or bool(result.stdout.strip())
        except Exception:
            pass

        return stopped

    def status(self) -> dict:
        running = False
        pid = None

        # Method 1: Check via schtasks
        try:
            result = _run_win(["schtasks", "/Query", "/TN", self._task_name, "/FO", "CSV"], timeout=5)
            running = "Running" in result.stdout
        except Exception:
            pass

        # Method 2: Fallback — check if any python process is running the presence monitor
        if not running:
            try:
                monitor_name = self._monitor_process_name()
                ps_cmd = (
                    "Get-WmiObject Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
                    "Select-Object ProcessId, CommandLine | "
                    "Where-Object { $_.CommandLine -match '%s' } | "
                    'ForEach-Object { "$($_.ProcessId)" }'
                ) % monitor_name
                if _is_wsl():
                    result = subprocess.run(
                        ["powershell.exe", "-Command", ps_cmd],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                else:
                    result = subprocess.run(
                        ["powershell", "-Command", ps_cmd],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                pid_str = result.stdout.strip()
                if pid_str:
                    running = True
                    try:
                        pid = int(pid_str.split()[0])
                    except (ValueError, IndexError):
                        pass
            except Exception:
                pass

        # Method 3: Check if state file is being actively written (recent timestamp)
        if not running:
            try:
                if self.state_file.exists():
                    mtime = self.state_file.stat().st_mtime
                    if (time.time() - mtime) < 30:
                        running = True  # State file updated within last 30s
            except Exception:
                pass

        return {
            "running": running,
            "auto_start": self.is_installed(),
            "pid": pid,
        }

    def diagnostics(self) -> dict:
        return {
            "task_name": self._task_name,
            "monitor_target": str(self._monitor_target),
            "startup_script": str(self._startup_script_path()),
            "legacy_bat": str(self._legacy_bat_path()),
            "process_name": self._monitor_process_name(),
        }


def _monitor_script_content(
    client_id: str,
    state_file: str,
    profile: str = "main",
    fallback_reasoning_effort: str = "",
    show_reasoning: bool = False,
    privacy_mode: bool = True,
    tui_only: bool = False,
) -> str:
    mirror_name = "hermes_presence.json" if profile == "main" else f"{profile}_presence.json"
    return f'''"""
Hermes Presence Monitor v3.4.2 — Windows auto-start script (all-pipe).
Profile: {profile}
Generated by hermes-presence install --profile {profile}.
Do not edit manually — run `hermes-presence install` to reconfigure.
"""
import json
import os
import signal
import sys
import time
import ctypes
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from pypresence import Presence, DiscordNotFound, PipeClosed
except ImportError:
    print("[FATAL] pypresence not installed. Run: pip install pypresence", flush=True)
    sys.exit(1)

CLIENT_ID = "{client_id}"
STATE_DIR = Path(os.environ.get("APPDATA", ""))
DEFAULT_REASONING_EFFORT = "{fallback_reasoning_effort}"
SHOW_REASONING = {str(show_reasoning)}
PRIVACY_MODE = {str(privacy_mode)}
TUI_ONLY = {str(tui_only)}
PIPES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

_MUTEX_HANDLE = None
if os.name == "nt":
    _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
        None,
        True,
        "Local\\\\HermesPresenceMonitor_{profile}",
    )
    if ctypes.windll.kernel32.GetLastError() == 183:
        print("[MONITOR] Another Hermes Presence Monitor is already running; exiting", flush=True)
        sys.exit(0)

# Tool → small_image icon (Discord asset names — must exist in Developer Portal)
TOOL_ICON_MAP = {{
    "terminal":        "status_active",
    "execute_code":    "status_active",
    "web_search":      "status_researching",
    "web_extract":     "status_researching",
    "browser_navigate": "status_monitoring",
    "browser_click":   "status_monitoring",
    "browser_type":    "status_monitoring",
    "browser_snapshot":"status_monitoring",
    "browser_back":    "status_monitoring",
    "browser_vision":  "status_monitoring",
    "browser_console": "status_monitoring",
    "browser_scroll":  "status_monitoring",
    "browser_press":   "status_monitoring",
    "browser_get_images": "status_monitoring",
    "read_file":       "status_researching",
    "write_file":      "status_working",
    "patch":           "status_working",
    "search_files":    "status_researching",
    "delegate_task":   "status_monitoring",
    "delegate_tasks":  "status_monitoring",
    "send_message":    "status_active",
    "memory":          "status_standby",
    "session_search":  "status_researching",
    "mem0local_search":"status_researching",
    "mem0local_remember":"status_standby",
    "mem0local_health":"status_standby",
    "skill_view":      "status_researching",
    "skill_manage":    "status_working",
    "skills_list":     "status_researching",
    "vision_analyze":  "status_monitoring",
    "image_generate":  "status_active",
    "text_to_speech":  "status_active",
    "cronjob":         "status_standby",
    "clarify":         "status_active",
    "todo":            "status_standby",
    "process":         "status_active",
}}

STATE_DISPLAY = {{
    "idle":          "Idle",
    "working":       "Working",
    "thinking":      "Answering",
    "error":         "Error",
    "monitoring":    "Monitoring",
    "offline":       "Offline",
    "orchestrating": "Orchestrating",
    "session_ended": "Session Ended",
}}

MODEL_SHORT = {{
    "claude-sonnet-4": "Claude Sonnet 4",
    "claude-opus-4": "Claude Opus 4",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-v4": "DeepSeek V4",
    "gpt-5.5": "GPT-5.5",
    "gpt-4o": "GPT-4o",
    "gpt-5": "GPT-5",
}}

PROVIDER_SHORT = {{
    "openai-codex": "Codex",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
}}


def _iso_to_epoch(iso_str):
    """Convert ISO datetime string to Unix epoch int."""
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return int(time.time())


def _resolve_small_icon(tool_name):
    """Pick the best small_image icon for a tool. Fallback: state-based."""
    if not tool_name:
        return None
    icon = TOOL_ICON_MAP.get(tool_name)
    if icon:
        return icon
    # Prefix fallback for browser_, delegate_, mem0local_ families
    for prefix, icon_fallback in [
        ("browser_", "status_monitoring"),
        ("delegate_", "status_monitoring"),
        ("mem0local_", "status_standby"),
    ]:
        if tool_name.startswith(prefix):
            return icon_fallback
    return None


def _format_model_label(model, provider):
    """Build a compact model label."""
    label = ""
    if model:
        for long, short in MODEL_SHORT.items():
            if long in model.lower():
                label = short
                break
        if not label:
            label = model
    elif provider:
        label = PROVIDER_SHORT.get(provider.lower(), provider.capitalize())

    if label and provider:
        provider_label = PROVIDER_SHORT.get(provider.lower(), provider.capitalize())
        if provider_label.lower() not in label.lower():
            label = f"{{label}} ({{provider_label}})"
    return label


def _format_reasoning_label(reasoning_effort):
    effort = str(reasoning_effort or "").strip().lower()
    if not effort:
        return ""
    return {{
        "minimal": "R: minimal",
        "low": "R: low",
        "medium": "R: medium",
        "high": "R: high",
        "xhigh": "R: xhigh",
        "none": "R: off",
    }}.get(effort, f"R: {{effort}}")


def _human_tool(tool):
    cleaned = str(tool or "").replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in cleaned.split())


def _clip(value, max_len=128):
    text = str(value or "")
    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."


def _action_label(state_name, tool, detail):
    if state_name == "error":
        return "hit an error"
    if state_name in ("thinking", "typing"):
        return "thinking"
    if state_name == "idle":
        return "ready"
    if state_name == "orchestrating":
        return "orchestrating"
    if state_name == "cron_job":
        return "running a cron job"
    if state_name == "session_ended":
        return "session ended"
    lower_detail = str(detail or "").lower()
    if "running tests" in lower_detail:
        return "running tests"
    if "checking code quality" in lower_detail:
        return "checking code"
    if "reviewing code changes" in lower_detail:
        return "reviewing changes"
    if tool in {{"patch", "write_file", "skill_manage"}}:
        return "editing"
    if tool in {{"read_file", "search_files", "web_search", "web_extract", "session_search", "mem0local_search"}}:
        return "researching"
    if str(tool or "").startswith("browser_"):
        return "browsing"
    if str(tool or "").startswith("delegate_") or tool == "delegate_task":
        return "delegating"
    if state_name == "working":
        return "working"
    return str(state_name or "working").replace("_", " ")


def _workspace_parts(workspace, target):
    parts = []
    workspace = workspace if isinstance(workspace, dict) else {{}}
    project = str(workspace.get("project", "") or "").strip()
    branch = str(workspace.get("git_branch", "") or "").strip()
    dirty = bool(workspace.get("git_dirty", False))
    target = str(target or "").strip()
    if project:
        parts.append(project)
    if branch:
        parts.append(f"{{branch}}{{'*' if dirty else ''}}")
    if target:
        parts.append(target)
    return parts


def _format_presence_lines(state_name, tool, detail, model_label, workspace, target):
    action = _action_label(state_name, tool, detail)
    lead = model_label or "Hermes"
    project = ""
    if isinstance(workspace, dict):
        project = str(workspace.get("project", "") or "").strip()
    if project and action not in {{"ready", "session ended"}}:
        details = f"{{lead}} {{action}} {{project}}"
    else:
        details = f"{{lead}} {{action}}"
    state_parts = _workspace_parts(workspace, target)
    if not state_parts and detail:
        state_parts = [detail]
    state_text = " | ".join(state_parts) or action.capitalize()
    return _clip(details), _clip(state_text)


def _state_is_tui(data):
    return bool(data.get("session", {{}}).get("is_tui", False))


def _state_session_id(data):
    return str(data.get("session", {{}}).get("id", "") or "").strip()


def _windows_visible_cwds():
    try:
        ps = r"""
Get-CimInstance Win32_Process |
  Where-Object {{ $_.Name -match 'WindowsTerminal|OpenConsole|wsl' -or ($_.CommandLine -and $_.CommandLine -match 'tmux|hermes|--tui') }} |
  Select-Object Name,CommandLine |
  ConvertTo-Json -Depth 3
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return set()
        rows = json.loads(result.stdout)
        if isinstance(rows, dict):
            rows = [rows]
    except Exception:
        return set()
    cwds = set()
    for row in rows if isinstance(rows, list) else []:
        cmd = str(row.get("CommandLine") or "")
        match = re.search(r'--cd\s+"([^"]+)"', cmd) or re.search(r'--cd\s+([^\s]+)', cmd)
        if match:
            cwds.add(match.group(1))
    return cwds


def _wsl_tui_sessions():
    code = r"""
import json, os
from pathlib import Path

def read_cmd(pid):
    try:
        return [p.decode('utf-8','replace') for p in Path('/proc', pid, 'cmdline').read_bytes().split(b'\\0') if p]
    except Exception:
        return []

def ppid(pid):
    try:
        for line in Path('/proc', pid, 'status').read_text(errors='replace').splitlines():
            if line.startswith('PPid:'):
                return int(line.split()[1])
    except Exception:
        pass
    return None

def cwd(pid):
    try:
        return str(Path('/proc', pid, 'cwd').resolve())
    except Exception:
        return ''

procs=[]
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    args=read_cmd(entry.name)
    if args:
        procs.append({{'pid': int(entry.name), 'ppid': ppid(entry.name), 'args': args, 'cwd': cwd(entry.name)}})
children={{}}
for p in procs:
    children.setdefault(p.get('ppid'), []).append(p)

def arg_value(args, flag):
    for i, v in enumerate(args):
        if v == flag and i + 1 < len(args):
            return args[i+1]
        if v.startswith(flag + '='):
            return v.split('=', 1)[1]
    return ''

def descendant_keys(root):
    out=[]; queue=[root]; seen=set()
    while queue:
        pid=queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        for child in children.get(pid, []):
            queue.append(child['pid'])
            key=arg_value(child['args'], '--session-key')
            if key and key not in out:
                out.append(key)
    return out

sessions=[]
for p in procs:
    args=p['args']; joined=' '.join(args).lower(); first=Path(args[0]).name.lower()
    is_python=first.startswith('python') and any(Path(a).name == 'hermes' for a in args[1:5])
    is_tui=(first == 'hermes' or is_python) and ('--tui' in args or '--tui' in joined) and 'tui_gateway' not in joined and 'slash_worker' not in joined
    if not is_tui:
        continue
    keys=descendant_keys(p['pid'])
    sid=arg_value(args, '--resume') or arg_value(args, '--session-id') or (keys[-1] if keys else '')
    sessions.append({{'session_id': sid, 'cwd': p['cwd'], 'descendant_session_keys': keys}})
print(json.dumps(sessions))
"""
    try:
        result = subprocess.run(
            ["wsl.exe", "--", "python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        rows = json.loads(result.stdout)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _session_ids_from_tui_session(session):
    ids = set()
    sid = str(session.get('session_id', '') or '').strip()
    if sid:
        ids.add(sid)
    for key in session.get('descendant_session_keys', []) or []:
        if key:
            ids.add(str(key))
    return ids


def _active_tui_sessions():
    sessions = [s for s in _wsl_tui_sessions() if isinstance(s, dict)]
    visible_cwds = _windows_visible_cwds()
    visible = []
    if visible_cwds:
        for session in sessions:
            if str(session.get('cwd', '') or '').strip() in visible_cwds:
                visible.append(session)
        if visible:
            return visible
    return sessions


def _active_tui_session_ids():
    ids = set()
    for session in _active_tui_sessions():
        ids.update(_session_ids_from_tui_session(session))
    return ids


def _state_age_seconds(data):
    ts_str = str(data.get('timestamp', '') or '').strip()
    if not ts_str:
        return None
    try:
        return datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(ts_str).timestamp()
    except ValueError:
        return None


def _project_from_cwd(cwd):
    clean = str(cwd or '').rstrip('/')
    if not clean:
        return 'Hermes TUI'
    name = Path(clean).name or 'Hermes TUI'
    if name in {{'hermes-projects', 'hermes-project'}}:
        return 'Hermes TUI'
    return name


def _known_session_value(old_session, key):
    value = str(old_session.get(key, '') or '').strip()
    return '' if value.lower() == 'unknown' else value


def _synthesise_active_tui_state(session, existing=None):
    existing = existing if isinstance(existing, dict) else {{}}
    old_session = existing.get('session', {{}}) if isinstance(existing.get('session'), dict) else {{}}
    now = datetime.now(timezone.utc).isoformat()
    sid = str(old_session.get('id', '') or '').strip()
    ids = _session_ids_from_tui_session(session)
    if not sid:
        sid = next(iter(ids), '')
    cwd = str(session.get('cwd', '') or '').strip()
    return {{
        'version': 3,
        'timestamp': now,
        'profile': existing.get('profile', 'main'),
        'activity': {{
            'state': 'idle',
            'tool': None,
            'target': '',
            'detail': 'Visible TUI active',
            'large_image': 'status_idle',
            'tool_started_at': None,
            'is_error': False,
            'error_msg': None,
        }},
        'workspace': {{
            'cwd': cwd,
            'project': _project_from_cwd(cwd),
            'git_branch': '',
            'git_dirty': False,
        }},
        'session': {{
            'id': sid,
            'started_at': old_session.get('started_at') or now,
            'duration_seconds': 0,
            'model': _known_session_value(old_session, 'model'),
            'provider': _known_session_value(old_session, 'provider'),
            'reasoning_effort': old_session.get('reasoning_effort', ''),
            'tool_calls_count': old_session.get('tool_calls_count', 0),
            'subagent_count': old_session.get('subagent_count', 0),
            'files_modified': old_session.get('files_modified', 0),
            'cost_usd': old_session.get('cost_usd', 0.0),
            'is_tui': True,
            'is_cron': False,
            'is_orchestrator': False,
        }},
    }}


def _find_latest_state_file(state_dir):
    """Scan for all presence_*.json files and return the newest by timestamp."""
    if not state_dir.exists():
        return None, None
    active_ids = _active_tui_session_ids() if TUI_ONLY else set()
    candidates = []
    for f in state_dir.glob("presence_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if not ts_str:
                continue
            if TUI_ONLY:
                if not _state_is_tui(data):
                    continue
                if active_ids and _state_session_id(data) not in active_ids:
                    continue
            ts = datetime.fromisoformat(ts_str)
            candidates.append((f, data, ts.timestamp()))
        except (json.JSONDecodeError, ValueError, OSError):
            continue
    # Legacy fallback
    legacy = state_dir / "{mirror_name}"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if TUI_ONLY:
                if not _state_is_tui(data):
                    ts_str = ""
                elif active_ids and _state_session_id(data) not in active_ids:
                    ts_str = ""
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                candidates.append((legacy, data, ts.timestamp()))
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    if not candidates:
        if TUI_ONLY:
            active_sessions = _active_tui_sessions()
            if active_sessions:
                return None, _synthesise_active_tui_state(active_sessions[0])
        return None, None
    candidates.sort(key=lambda x: x[2], reverse=True)
    selected_file, selected_state, _ = candidates[0]
    if TUI_ONLY:
        active_sessions = _active_tui_sessions()
        state_age = _state_age_seconds(selected_state)
        if active_sessions and state_age is not None and state_age >= 60:
            selected_sid = _state_session_id(selected_state)
            selected_session = next(
                (
                    session for session in active_sessions
                    if selected_sid in _session_ids_from_tui_session(session)
                ),
                active_sessions[0],
            )
            selected_state = _synthesise_active_tui_state(selected_session, selected_state)
    return selected_file, selected_state


print("[MONITOR] Starting Hermes Presence v3.4.2 (all-pipe, multi-session)", flush=True)
print(f"[MONITOR] Client ID: {{CLIENT_ID}}", flush=True)
print(f"[MONITOR] State dir: {{STATE_DIR}}", flush=True)

# connections dict: pipe_num -> Presence
connections = {{}}
last_hash = ""
last_push_monotonic = 0.0
REPUBLISH_INTERVAL = 30


def connect_all():
    """Connect to every available Discord pipe."""
    for pipe_num in PIPES:
        if pipe_num in connections:
            continue
        try:
            rpc = Presence(CLIENT_ID, pipe=pipe_num)
            rpc.connect()
            connections[pipe_num] = rpc
            print(f"[MONITOR] Pipe {{pipe_num}} connected", flush=True)
        except DiscordNotFound:
            continue
        except PipeClosed:
            continue
        except Exception as e:
            print(f"[MONITOR] Pipe {{pipe_num}} error: {{e}}", flush=True)
    return len(connections) > 0


def disconnect_all():
    """Clear and close all connections."""
    for pipe_num, rpc in list(connections.items()):
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass
    connections.clear()


def update_all(presence, party_size=None):
    """Push presence to every connected pipe."""
    dead = []
    for pipe_num, rpc in connections.items():
        try:
            kwargs = dict(presence)
            if party_size is not None and party_size > 1:
                kwargs["party_size"] = [party_size, party_size]
            rpc.update(**kwargs)
        except (PipeClosed, ConnectionError, OSError):
            print(f"[MONITOR] Pipe {{pipe_num}} disconnected", flush=True)
            dead.append(pipe_num)
        except Exception as e:
            print(f"[MONITOR] Pipe {{pipe_num}} error: {{e}}", flush=True)
    for pipe_num in dead:
        try:
            connections[pipe_num].close()
        except Exception:
            pass
        del connections[pipe_num]


def shutdown(*args):
    disconnect_all()
    print("[MONITOR] Shutdown", flush=True)
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)
if hasattr(signal, 'SIGHUP'):  # Unix only — no-op on Windows
    signal.signal(signal.SIGHUP, shutdown)  # systemd sends SIGHUP before SIGTERM

# Main loop
no_conn_count = 0  # Watchdog: consecutive iterations with no connections
while True:
    prev_count = len(connections)
    connect_all()

    # New pipe connected? Force push current state to all pipes
    if len(connections) > prev_count:
        new_count = len(connections) - prev_count
        print(f"[MONITOR] +{{new_count}} new pipe(s), forcing state push", flush=True)
        last_hash = ""
        no_conn_count = 0  # Reset watchdog

    if not connections:
        no_conn_count += 1
        if no_conn_count == 100:
            print("[MONITOR] No Discord pipes for 5 minutes; continuing to retry", flush=True)
        elif no_conn_count < 100 or no_conn_count % 12 == 0:
            print(f"[MONITOR] No Discord pipes available, waiting... ({{no_conn_count}})", flush=True)
        time.sleep(5)
        continue
    else:
        no_conn_count = 0  # Reset watchdog on successful connection

    try:
        state_file, data = _find_latest_state_file(STATE_DIR)
        if data is None:
            if last_hash:
                disconnect_all()
                last_hash = ""
            time.sleep(2)
            continue

        act = data.get("activity", {{}})
        sess = data.get("session", {{}})

        state_name = act.get("state", "idle")
        tool = act.get("tool") or ""
        detail = act.get("detail", "")
        tool_started_at = act.get("tool_started_at")

        # If Hermes misses a post-tool hook, Discord otherwise keeps showing
        # the last tool forever. Treat old in-progress tool states as idle.
        stale_working_seconds = 90
        if state_name == "working" and tool_started_at:
            tool_age = time.time() - _iso_to_epoch(tool_started_at)
            if tool_age >= stale_working_seconds:
                state_name = "idle"
                detail = "Waiting for next request"
                tool = ""
                tool_started_at = None

        model = sess.get("model", "")
        provider = sess.get("provider", "")
        reasoning_effort = sess.get("reasoning_effort", "") or DEFAULT_REASONING_EFFORT
        calls = sess.get("tool_calls_count", 0)
        subs = sess.get("subagent_count", 0)
        started_at = sess.get("started_at", "")
        session_id = sess.get("id", "")

        if PRIVACY_MODE:
            tool = ""
            detail = "Working privately"
            model = ""
            provider = ""
            reasoning_effort = ""

        # Context line: project/branch/file. Keep the model in details.
        model_label = _format_model_label(model, provider)
        workspace = data.get("workspace", {{}})
        target = act.get("target", "") or ""
        details, state_text = _format_presence_lines(
            state_name,
            tool,
            detail,
            model_label,
            workspace,
            target,
        )
        if PRIVACY_MODE:
            details = _clip(detail or "Working privately")
            state_text = STATE_DISPLAY.get(state_name, "Hermes")
        reasoning_label = _format_reasoning_label(reasoning_effort) if SHOW_REASONING else ""
        if reasoning_label:
            state_text = f"{{state_text}} | {{reasoning_label}}"

        # Large image always hermes_logo
        large_image = "hermes_logo"

        # Small image from tool icon map
        small_image = _resolve_small_icon(tool)
        small_text = "private" if PRIVACY_MODE else (tool or state_name)

        # Start timestamp: prefer per-tool, fallback to session
        if tool_started_at:
            start_ts = _iso_to_epoch(tool_started_at)
        else:
            start_ts = _iso_to_epoch(started_at) if started_at else int(time.time())

        # Hover text
        hover_parts = []
        if model_label:
            hover_parts.append(f"Model: {{model_label}}")
        elif model:
            hover_parts.append(f"Model: {{model}}")
        if reasoning_label:
            hover_parts.append(f"Reasoning: {{reasoning_label.replace('R: ', '')}}")
        if provider:
            hover_parts.append(f"Provider: {{provider}}")
        hover_parts.append(f"tool calls: {{calls}}")
        if subs > 0:
            hover_parts.append(f"sub-agents: {{subs}}")

        # Buttons
        buttons = [{{
            "label": "Hermes Agent",
            "url": "https://github.com/NousResearch/hermes-agent"
        }}]

        # Hash check. Include session identity so Hermes restarts with the same
        # visible idle state still repush presence after Discord/Hermes restart.
        hash_parts = [
            state_text,
            details,
            tool,
            session_id,
            started_at,
            str(calls),
            str(subs),
            str(tool_started_at),
            reasoning_effort,
            str(SHOW_REASONING),
            str(PRIVACY_MODE),
            str(workspace.get("project", "") if isinstance(workspace, dict) else ""),
            str(workspace.get("git_branch", "") if isinstance(workspace, dict) else ""),
            str(workspace.get("git_dirty", False) if isinstance(workspace, dict) else False),
            target,
        ]
        new_hash = "|".join(hash_parts)
        now_mono = time.monotonic()
        should_republish = (now_mono - last_push_monotonic) >= REPUBLISH_INTERVAL
        if new_hash != last_hash or should_republish:
            presence = {{
                "state": state_text,
                "details": details,
                "large_image": large_image,
                "large_text": " | ".join(hover_parts) if hover_parts else "Hermes Agent",
                "small_image": small_image,
                "small_text": small_text,
                "start": start_ts,
                "buttons": buttons,
            }}

            # Party size: Hermes + sub-agents
            party = (subs + 1) if subs > 0 else None

            update_all(presence, party_size=party)
            last_hash = new_hash
            last_push_monotonic = now_mono
            pipes_str = ",".join(str(p) for p in connections)
            extras = []
            if subs > 0:
                extras.append(f"{{subs}} subs")
            if tool:
                extras.append(f"icon={{small_image}}")
            extra_str = f" ({{', '.join(extras)}})" if extras else ""
            print(f"[MONITOR] -> pipes {{pipes_str}}: {{state_text}}{{extra_str}}", flush=True)

    except json.JSONDecodeError as e:
        print(f"[MONITOR] Bad JSON: {{e}}", flush=True)
        time.sleep(3)
        continue
    except Exception as e:
        import traceback
        print(f"[MONITOR] Error: {{e}}", flush=True)
        traceback.print_exc()
        time.sleep(5)
        continue

    time.sleep(3)
'''


def _task_scheduler_xml(task_name: str, python_path: str, script_path: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Hermes Presence — Discord Rich Presence Monitor</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python_path}</Command>
      <Arguments>{script_path}</Arguments>
    </Exec>
  </Actions>
</Task>"""


def _profile_artifact_paths(profile: str) -> list[Path]:
    if profile == "main":
        monitor_name = "hermes_presence_monitor.py"
        vbs_name = "hermes_presence.vbs"
        bat_name = "hermes_presence.bat"
    else:
        monitor_name = f"{profile}_presence_monitor.py"
        vbs_name = f"{profile}_presence.vbs"
        bat_name = f"{profile}_presence.bat"
    return [
        STARTUP_DIR / vbs_name,
        STARTUP_DIR / bat_name,
        STARTUP_DIR / f"{bat_name}.disabled",
        Path(_APPDATA) / monitor_name,
    ]


def cleanup_profile_artifacts(profile: str) -> list[str]:
    """Remove stale Windows launcher/monitor files for a profile."""
    removed: list[str] = []
    launcher = WindowsLauncher("", Path("presence.json"), profile=profile)
    try:
        launcher.stop()
    except Exception:
        pass
    try:
        _run_win(["schtasks", "/Delete", "/TN", launcher._task_name, "/F"], timeout=10)
    except Exception:
        pass
    for task_name in launcher._legacy_task_names():
        try:
            _run_win(["schtasks", "/Delete", "/TN", task_name, "/F"], timeout=10)
        except Exception:
            pass
    for path in _profile_artifact_paths(profile):
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except Exception:
            pass
    return removed


def diagnose_startup(profile: str = "main", fix: bool = False) -> dict:
    """Diagnose common Windows startup issues that cause visible consoles or duplicate pollers."""
    launcher = WindowsLauncher("", Path("presence.json"), profile=profile)
    issues: list[dict] = []
    fixes: list[str] = []

    legacy_bat = launcher._legacy_bat_path()
    if legacy_bat.exists():
        issues.append({
            "id": "visible_bat_launcher",
            "severity": "warn",
            "message": f"Visible Startup .bat launcher exists: {legacy_bat}",
        })
        if fix:
            disabled = legacy_bat.with_suffix(legacy_bat.suffix + ".disabled")
            try:
                legacy_bat.replace(disabled)
                fixes.append(f"Disabled visible Startup launcher: {disabled}")
            except Exception as exc:
                fixes.append(f"Could not disable visible Startup launcher: {exc}")

    for task_name in launcher._legacy_task_names():
        try:
            result = _run_win(["schtasks", "/Query", "/TN", task_name], timeout=10)
            if result.returncode == 0 or task_name in (result.stdout or ""):
                issues.append({
                    "id": "legacy_scheduled_task",
                    "severity": "warn",
                    "message": f"Legacy scheduled task exists: {task_name}",
                })
                if fix:
                    _run_win(["schtasks", "/Change", "/TN", task_name, "/Disable"], timeout=10)
                    fixes.append(f"Disabled legacy scheduled task: {task_name}")
        except Exception:
            pass

    try:
        ps_cmd = (
            "Get-WmiObject Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
            "Where-Object { $_.CommandLine -match 'run_presence.py' } | "
            'ForEach-Object { "$($_.ProcessId)" }'
        )
        result = subprocess.run(
            ["powershell.exe" if _is_wsl() else "powershell", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.strip():
            issues.append({
                "id": "legacy_run_presence_process",
                "severity": "warn",
                "message": f"Legacy run_presence.py process is active: {result.stdout.strip()}",
            })
    except Exception:
        pass

    python_path = launcher._find_python()
    hidden_python = _pythonw_path(python_path)
    if hidden_python.lower().endswith("python.exe"):
        issues.append({
            "id": "pythonw_missing",
            "severity": "info",
            "message": (
                "pythonw.exe was not found beside python.exe; "
                "console-free startup may depend on WScript only."
            ),
        })

    return {"profile": profile, "issues": issues, "fixes": fixes}
