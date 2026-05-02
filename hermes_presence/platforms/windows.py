"""
Windows platform launcher — Task Scheduler + shell:startup.

Creates a Windows Scheduled Task (triggered at user logon) and/or
a .bat file in the Startup folder for auto-start.

On WSL2: commands run through powershell.exe bridge automatically.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from . import PlatformLauncher


TASK_NAME = "HermesPresence"
_APPDATA_FALLBACK = "/mnt/c/Users/logi4k/AppData/Roaming"
STARTUP_DIR = Path(os.environ.get("APPDATA", _APPDATA_FALLBACK)) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
MONITOR_TARGET = Path(os.environ.get("APPDATA", _APPDATA_FALLBACK)) / "hermes_presence_monitor.py"


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
            ps_line
        ]
    else:
        full_cmd = cmd

    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)


class WindowsLauncher(PlatformLauncher):
    """Windows Task Scheduler + shell:startup launcher."""

    def _find_python(self) -> str:
        """Locate Python on Windows."""
        candidates = [
            r"C:\Users\LOGI4K\.hermes\hermes-agent\venv\Scripts\python.exe",
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
        ]

        # Also try via PowerShell on WSL or 'where' on native Windows
        try:
            if _is_wsl():
                result = subprocess.run(
                    ["powershell.exe", "-Command",
                     "Get-Command python | Select-Object -ExpandProperty Source"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and "python" in line.lower():
                        candidates.insert(0, line)
            else:
                result = subprocess.run(
                    ["where", "python"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        candidates.insert(0, line)
        except Exception:
            pass

        for c in candidates:
            p = Path(c) if "\\" in c else Path(c.replace("\\", "/"))
            try:
                if p.exists():
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
        )
        try:
            MONITOR_TARGET.parent.mkdir(parents=True, exist_ok=True)
            MONITOR_TARGET.write_text(monitor_script, encoding="utf-8")
        except Exception:
            pass

        # Method 1: Try Scheduled Task (needs admin on some systems)
        try:
            result = _run_win([
                "schtasks", "/Create", "/TN", TASK_NAME,
                "/SC", "ONLOGON",
                "/TR", f'"{python_path}" "{win_target}"',
                "/F",
                "/RL", "LIMITED",
                "/DELAY", "0000:30",
            ])
            if result.returncode == 0:
                _run_win(["schtasks", "/Run", "/TN", TASK_NAME])
                print("[OK] Scheduled Task created and started")
                return True
            else:
                print(f"[INFO] schtasks unavailable (this is fine): {result.stderr.strip()}")
        except Exception as e:
            print(f"[INFO] schtasks failed (will use startup folder fallback): {e}")

        # Method 2: Fallback — shell:startup .bat file (no admin needed)
        try:
            startup_bat = STARTUP_DIR / "hermes_presence.bat"
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
            _run_win(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        except Exception:
            pass
        MONITOR_TARGET.unlink(missing_ok=True)
        return not self.is_installed()

    def is_installed(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Query", "/TN", TASK_NAME], timeout=5)
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # Check for startup .bat fallback
        startup_bat = STARTUP_DIR / "hermes_presence.bat"
        return startup_bat.exists()

    def start(self) -> bool:
        try:
            result = _run_win(["schtasks", "/Run", "/TN", TASK_NAME], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def stop(self) -> bool:
        try:
            result = _run_win(["schtasks", "/End", "/TN", TASK_NAME], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict:
        running = False
        pid = None

        # Method 1: Check via schtasks
        try:
            result = _run_win(
                ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV"],
                timeout=5
            )
            running = "Running" in result.stdout
        except Exception:
            pass

        # Method 2: Fallback — check if any python process is running the presence monitor
        if not running:
            try:
                ps_cmd = (
                    'Get-WmiObject Win32_Process -Filter "Name=\'python.exe\' OR Name=\'pythonw.exe\'" | '
                    'Select-Object ProcessId, CommandLine | '
                    'Where-Object { $_.CommandLine -match \'run_presence|hermes_presence_monitor\' } | '
                    'ForEach-Object { "$($_.ProcessId)" }'
                )
                if _is_wsl():
                    result = subprocess.run(
                        ["powershell.exe", "-Command", ps_cmd],
                        capture_output=True, text=True, timeout=10
                    )
                else:
                    result = subprocess.run(
                        ["powershell", "-Command", ps_cmd],
                        capture_output=True, text=True, timeout=10
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


def _monitor_script_content(client_id: str, state_file: str) -> str:
    # Convert WSL state_file to Windows AppData path for Windows-native execution
    # On WSL the hook mirrors state to %APPDATA%/hermes_presence.json
    return f'''"""
Hermes Presence Monitor v3.1 — Windows auto-start script (multi-pipe).
Generated by hermes-presence install.
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
STATE_FILE = Path(os.environ.get("APPDATA", "")) / "hermes_presence.json"
PIPES = [0, 1, 2, 3]

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
    "idle":       "Idle",
    "working":    "Working",
    "thinking":   "Thinking",
    "error":      "Error",
    "monitoring": "Monitoring",
    "offline":    "Offline",
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


print("[MONITOR] Starting Hermes Presence v3.1 (multi-pipe)", flush=True)
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

# Main loop
while True:
    prev_count = len(connections)
    connect_all()

    # New pipe connected? Force push current state to all pipes
    if len(connections) > prev_count:
        new_count = len(connections) - prev_count
        print(f"[MONITOR] +{{new_count}} new pipe(s), forcing state push", flush=True)
        last_hash = ""

    if not connections:
        print("[MONITOR] No Discord pipes available, waiting...", flush=True)
        time.sleep(5)
        continue

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
    return f'''<?xml version="1.0" encoding="UTF-16"?>
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
</Task>'''
