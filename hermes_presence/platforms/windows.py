"""
Windows platform launcher — Task Scheduler + shell:startup.

Creates a Windows Scheduled Task (triggered at user logon) and/or
a .bat file in the Startup folder for auto-start.

On WSL2: commands run through powershell.exe bridge automatically.
"""

import os
import subprocess
import time
from pathlib import Path
from . import PlatformLauncher


TASK_NAME = "HermesPresence"


def _resolve_appdata() -> str:
    """Resolve %APPDATA% — works on native Windows, WSL, and remote SSH tunnel."""
    # 1. Native Windows: %APPDATA% env var is set
    raw = os.environ.get("APPDATA")
    if raw and Path(raw).exists():
        return raw

    # 2. WSL: read the Windows username from /mnt/c/Users, then check AppData
    try:
        for entry in sorted(Path("/mnt/c/Users").iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                candidate = entry / "AppData" / "Roaming"
                if candidate.exists():
                    return str(candidate)
    except Exception:
        pass

    # 3. Last resort — WSL-side fallback (functional for mirror writes via hook.py)
    return os.path.expanduser("~/.hermes/state")


def _find_windows_username() -> str:
    """Discover the Windows username from WSL or native env."""
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile).name
    # WSL: first directory in /mnt/c/Users that has AppData
    try:
        for entry in sorted(Path("/mnt/c/Users").iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                if (entry / "AppData" / "Roaming").exists():
                    return entry.name
    except Exception:
        pass
    return os.environ.get("USER", "unknown")


_APPDATA = _resolve_appdata()
STARTUP_DIR = (
    Path(_APPDATA) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
)
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


def _is_wsl() -> bool:
    """Check if running inside WSL."""
    try:
        with open("/proc/version") as f:
            content = f.read().lower()
            return "microsoft" in content or "wsl" in content
    except Exception:
        return False


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

    def __init__(self, client_id: str, state_file: Path, profile: str = "main"):
        super().__init__(client_id, state_file)
        self.profile = profile
        # Task name differs for non-main profiles
        self._task_name = "ApolloPresence" if profile == "apollo" else TASK_NAME
        # Monitor target differs for non-main
        self._monitor_target = Path(_APPDATA) / (
            "apollo_presence_monitor.py"
            if profile == "apollo"
            else "hermes_presence_monitor.py"
        )
        self._startup_bat_name = (
            "apollo_presence.bat" if profile == "apollo" else "hermes_presence.bat"
        )

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
        hermes_venv = Path(
            f"C:\\Users\\{username}\\.hermes\\hermes-agent\\venv\\Scripts\\python.exe"
        )
        if hermes_venv.exists():
            candidates.append(str(hermes_venv))
        # Also try pipx-style install
        pipx_venv = Path(
            f"C:\\Users\\{username}\\.hermes\\hermes-agent\\.venv\\Scripts\\python.exe"
        )
        if pipx_venv.exists():
            candidates.append(str(pipx_venv))

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
                result = subprocess.run(
                    ["where", "python"], capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and line not in candidates:
                        candidates.insert(0, line)
        except Exception:
            pass

        for c in candidates:
            p = Path(c) if "\\" in c else Path(c.replace("\\", "/"))
            try:
                if p.exists():
                    _CACHED_PYTHON = c
                    return c
            except Exception:
                pass

        return "python"

    def install(self) -> bool:
        """Install via Scheduled Task (most reliable), with shell:startup fallback."""
        python_path = self._find_python()
        # Convert paths for Windows-native commands
        win_target = _wsl_to_win_path(str(MONITOR_TARGET))

        # Write the monitor runner script to %APPDATA%
        monitor_script = _monitor_script_content(
            client_id=self.client_id,
            state_file=str(self.state_file),
            profile=self.profile,
        )
        try:
            self._monitor_target.parent.mkdir(parents=True, exist_ok=True)
            self._monitor_target.write_text(monitor_script, encoding="utf-8")
        except Exception:
            pass

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
                    f'"{python_path}" "{win_target}"',
                    "/F",
                    "/RL",
                    "LIMITED",
                    "/DELAY",
                    "0000:30",
                ]
            )
            if result.returncode == 0:
                _run_win(["schtasks", "/Run", "/TN", self._task_name])
                print("[OK] Scheduled Task created and started")
                return True
            else:
                print(
                    f"[INFO] schtasks unavailable (this is fine): {result.stderr.strip()}"
                )
        except Exception as e:
            print(f"[INFO] schtasks failed (will use startup folder fallback): {e}")

        # Method 2: Fallback — shell:startup .bat file (no admin needed)
        try:
            startup_bat = STARTUP_DIR / self._startup_bat_name
            py_path_clean = python_path.replace("\\\\", "\\")
            win_bat_path = _wsl_to_win_path(str(startup_bat))
            bat_content = f'''@echo off
REM Hermes Presence — auto-start (shell:startup)
start "" /B "{py_path_clean}" "{win_target}"
'''
            STARTUP_DIR.mkdir(parents=True, exist_ok=True)
            startup_bat.write_text(bat_content)
            print(f"[OK] Startup .bat created at {win_bat_path}")

            # Also start it now
            try:
                _run_win(["cmd", "/c", win_bat_path])
                print("[OK] Monitor started via startup .bat")
            except Exception as e:
                print(f"[WARN] Could not start via .bat: {e}")

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
        return not self.is_installed()

    def is_installed(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Query", "/TN", self._task_name], timeout=5)
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # Check for startup .bat fallback
        startup_bat = STARTUP_DIR / self._startup_bat_name
        return startup_bat.exists()

    def start(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Run", "/TN", self._task_name], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            result = _run_win(["schtasks", "/End", "/TN", self._task_name], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None

        # Method 1: Check via schtasks
        try:
            result = _run_win(
                ["schtasks", "/Query", "/TN", self._task_name, "/FO", "CSV"], timeout=5
            )
            running = "Running" in result.stdout
        except Exception:
            pass

        # Method 2: Fallback — check if any python process is running the presence monitor
        if not running:
            try:
                monitor_name = (
                    "apollo_presence_monitor"
                    if self.profile == "apollo"
                    else "hermes_presence_monitor"
                )
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


def _monitor_script_content(
    client_id: str, state_file: str, profile: str = "main"
) -> str:
    mirror_name = (
        "hermes_presence.json" if profile == "main" else f"{profile}_presence.json"
    )
    return f'''"""
Hermes Presence Monitor v3.1.0 — Windows auto-start script (all-pipe).
Profile: {profile}
Generated by hermes-presence install --profile {profile}.
Do not edit manually — run `hermes-presence install` to reconfigure.
"""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from pypresence import Presence, DiscordNotFound, PipeClosed
except ImportError:
    print("[FATAL] pypresence not installed. Run: pip install pypresence", flush=True)
    sys.exit(1)

CLIENT_ID = "{client_id}"
STATE_FILE = Path(os.environ.get("APPDATA", "")) / "{mirror_name}"
PIPES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

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
    "thinking":      "Thinking",
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
    "gpt-4o": "GPT-4o",
    "gpt-5": "GPT-5",
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
    if model:
        for long, short in MODEL_SHORT.items():
            if long in model.lower():
                return short
        return model
    if provider:
        return provider.capitalize()
    return ""


print("[MONITOR] Starting Hermes Presence v3.1.0 (all-pipe)", flush=True)
print(f"[MONITOR] Client ID: {{CLIENT_ID}}", flush=True)
print(f"[MONITOR] State file: {{STATE_FILE}}", flush=True)

# connections dict: pipe_num -> Presence
connections = {{}}
last_hash = ""


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
        if no_conn_count >= 100:  # 5 minutes at 3s sleep
            print("[MONITOR] No Discord pipes for 5 minutes — exiting for watchdog restart", flush=True)
            sys.exit(1)  # Exit with error to trigger Task Scheduler restart
        print(f"[MONITOR] No Discord pipes available, waiting... ({{no_conn_count}}/100)", flush=True)
        time.sleep(5)
        continue
    else:
        no_conn_count = 0  # Reset watchdog on successful connection

    try:
        if not STATE_FILE.exists():
            if last_hash:
                disconnect_all()
                last_hash = ""
            time.sleep(2)
            continue

        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        act = data.get("activity", {{}})
        sess = data.get("session", {{}})

        state_name = act.get("state", "idle")
        tool = act.get("tool", "")
        detail = act.get("detail", "")
        tool_started_at = act.get("tool_started_at")

        model = sess.get("model", "")
        provider = sess.get("provider", "")
        calls = sess.get("tool_calls_count", 0)
        subs = sess.get("subagent_count", 0)
        started_at = sess.get("started_at", "")

        # State text with model name
        state_text = STATE_DISPLAY.get(state_name, "Working")
        model_label = _format_model_label(model, provider)
        if model_label:
            state_text = f"{{state_text}} | {{model_label}}"

        # Details
        if detail and len(detail) > 128:
            detail = detail[:125] + "..."
        details = detail or state_text

        # Large image always hermes_logo
        large_image = "hermes_logo"

        # Small image from tool icon map
        small_image = _resolve_small_icon(tool)
        small_text = tool or state_name

        # Start timestamp: prefer per-tool, fallback to session
        if tool_started_at:
            start_ts = _iso_to_epoch(tool_started_at)
        else:
            start_ts = _iso_to_epoch(started_at) if started_at else int(time.time())

        # Hover text
        hover_parts = [f"model: {{model or 'hermes'}}"]
        if provider:
            hover_parts.append(f"provider: {{provider}}")
        hover_parts.append(f"tool calls: {{calls}}")
        if subs > 0:
            hover_parts.append(f"sub-agents: {{subs}}")

        # Buttons
        buttons = [{{
            "label": "Hermes Agent",
            "url": "https://github.com/NousResearch/hermes-agent"
        }}]

        # Hash check
        new_hash = f"{{state_text}}|{{details}}|{{tool}}|{{calls}}|{{subs}}|{{tool_started_at}}"
        if new_hash != last_hash:
            presence = {{
                "state": state_text,
                "details": details,
                "large_image": large_image,
                "large_text": "Hermes Agent",
                "small_image": small_image,
                "small_text": small_text,
                "start": start_ts,
                "buttons": buttons,
            }}

            # Party size: Hermes + sub-agents
            party = (subs + 1) if subs > 0 else None

            update_all(presence, party_size=party)
            last_hash = new_hash
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
