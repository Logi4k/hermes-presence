"""Detect live Hermes TUI sessions.

The presence state file is hook-driven, but status/doctor also need a runtime
view of TUI sessions that are launched through Windows Terminal into WSL/tmux.
Windows only sees WindowsTerminal.exe, OpenConsole.exe, and wsl.exe; the actual
Hermes TUI process lives inside the WSL process tree. This module joins both
views best-effort without requiring admin privileges.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

HERMES_TUI_FLAGS = {"--tui", "tui"}
_WINDOWS_TERMINAL_NAMES = {"windowsterminal.exe", "openconsole.exe"}
_WSL_PROCESS_NAMES = {"wsl.exe", "wslhost.exe"}


def _safe_int(value: str | int | None) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_cmdline(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    parts = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
    return parts


def _read_status_ppid(status_path: Path) -> int | None:
    try:
        for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PPid:"):
                return _safe_int(line.split()[1])
    except OSError:
        return None
    return None


def _read_cwd(pid_dir: Path) -> str:
    try:
        return str((pid_dir / "cwd").resolve())
    except OSError:
        return ""


def iter_linux_processes(proc_root: Path = Path("/proc")) -> list[dict[str, Any]]:
    """Return a compact WSL/Linux process table.

    Output is intentionally plain dictionaries so tests can inject fixtures
    without depending on psutil.
    """
    processes: list[dict[str, Any]] = []
    if not proc_root.exists():
        return processes

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        args = _read_cmdline(entry / "cmdline")
        if not args:
            continue
        processes.append(
            {
                "pid": pid,
                "ppid": _read_status_ppid(entry / "status"),
                "name": Path(args[0]).name,
                "args": args,
                "cmdline": " ".join(args),
                "cwd": _read_cwd(entry),
            }
        )
    return processes


def _arg_value(args: list[str], flag: str) -> str:
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return args[index + 1]
        if value.startswith(f"{flag}="):
            return value.split("=", 1)[1]
    return ""


def _is_hermes_tui_process(args: list[str]) -> bool:
    if not args:
        return False
    joined = " ".join(args).lower()
    first = Path(args[0]).name.lower()
    python_entry = first.startswith("python") and any(Path(arg).name == "hermes" for arg in args[1:5])
    direct_entry = first == "hermes"
    has_hermes_entry = direct_entry or python_entry
    has_tui_flag = any(flag in args for flag in HERMES_TUI_FLAGS) or "--tui" in joined
    is_gateway_worker = "tui_gateway" in joined or "slash_worker" in joined
    return has_hermes_entry and has_tui_flag and not is_gateway_worker


def _session_key_from_args(args: list[str]) -> str:
    return _arg_value(args, "--session-key")


def _session_id_from_hermes_args(args: list[str]) -> str:
    return _arg_value(args, "--resume") or _arg_value(args, "--session-id")


def _descendant_session_keys(processes: list[dict[str, Any]], root_pid: int) -> list[str]:
    children: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for proc in processes:
        ppid = _safe_int(proc.get("ppid"))
        if ppid is not None:
            children[ppid].append(proc)

    keys: list[str] = []
    queue: deque[int] = deque([root_pid])
    seen: set[int] = set()
    while queue:
        pid = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)
        for child in children.get(pid, []):
            child_pid = _safe_int(child.get("pid"))
            if child_pid is not None:
                queue.append(child_pid)
            args = list(child.get("args") or [])
            key = _session_key_from_args(args)
            if key and key not in keys:
                keys.append(key)
    return keys


def summarise_linux_tui_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarise Hermes TUI processes from an injected or live process table."""
    sessions: list[dict[str, Any]] = []
    for proc in sorted(processes, key=lambda p: int(p.get("pid") or 0)):
        args = list(proc.get("args") or [])
        if not _is_hermes_tui_process(args):
            continue
        pid = int(proc["pid"])
        descendant_keys = _descendant_session_keys(processes, pid)
        session_id = _session_id_from_hermes_args(args)
        if not session_id and descendant_keys:
            session_id = descendant_keys[-1]
        sessions.append(
            {
                "pid": pid,
                "ppid": proc.get("ppid"),
                "session_id": session_id,
                "cwd": proc.get("cwd", ""),
                "command": " ".join(args),
                "descendant_session_keys": descendant_keys,
            }
        )
    return sessions


def _powershell_json(command: str, timeout: int = 4) -> Any:
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    exe = "powershell.exe" if Path("/mnt/c/Windows").exists() else "powershell"
    result = subprocess.run(
        [exe, "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    return parsed if isinstance(parsed, list) else []


def scan_windows_terminal_processes(timeout: int = 4) -> list[dict[str, Any]]:
    """Best-effort Windows process scan for Windows Terminal backed WSL tabs."""
    if os.name != "nt" and not Path("/mnt/c/Windows").exists():
        return []

    command = r"""
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match 'WindowsTerminal|OpenConsole|wsl' -or
    ($_.CommandLine -and $_.CommandLine -match 'tmux|hermes|--tui')
  } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine |
  ConvertTo-Json -Depth 3
"""
    rows = _powershell_json(command, timeout=timeout)
    processes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        processes.append(
            {
                "pid": _safe_int(row.get("ProcessId")),
                "ppid": _safe_int(row.get("ParentProcessId")),
                "name": str(row.get("Name") or ""),
                "command": str(row.get("CommandLine") or ""),
            }
        )
    return [p for p in processes if p["pid"] is not None]


def _is_descendant(pid: int, ancestor_pids: set[int], parent_by_pid: dict[int, int | None]) -> bool:
    seen: set[int] = set()
    current: int | None = pid
    while current is not None and current not in seen:
        if current in ancestor_pids:
            return True
        seen.add(current)
        current = parent_by_pid.get(current)
    return False


def _extract_tmux_session(command: str) -> str:
    patterns = [
        r"tmux\s+attach(?:-session)?\s+-t\s+([^\s\"']+)",
        r"tmux\s+new-session\s+-s\s+([^\s\"']+)",
        r"tmux\s+new\s+-s\s+([^\s\"']+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            return match.group(1)
    return ""


def _extract_windows_cd(command: str) -> str:
    match = re.search(r"--cd\s+\"([^\"]+)\"", command)
    if match:
        return match.group(1)
    match = re.search(r"--cd\s+([^\s]+)", command)
    return match.group(1) if match else ""


def extract_windows_terminal_targets(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return WSL tabs launched by Windows Terminal that may host Hermes TUI."""
    terminal_pids = {
        int(p["pid"])
        for p in processes
        if str(p.get("name", "")).lower() in _WINDOWS_TERMINAL_NAMES and p.get("pid") is not None
    }
    parent_by_pid = {
        int(p["pid"]): _safe_int(p.get("ppid")) for p in processes if p.get("pid") is not None
    }

    targets: list[dict[str, Any]] = []
    seen_commands: set[str] = set()
    for proc in sorted(processes, key=lambda p: int(p.get("pid") or 0)):
        name = str(proc.get("name", "")).lower()
        command = str(proc.get("command") or "")
        pid = _safe_int(proc.get("pid"))
        if pid is None or name not in _WSL_PROCESS_NAMES:
            continue
        if not _is_descendant(pid, terminal_pids, parent_by_pid):
            continue
        if not any(
            marker in command.lower() for marker in ("tmux", "hermes", "--tui", "start-main-hermes")
        ):
            continue
        if command in seen_commands:
            continue
        seen_commands.add(command)
        targets.append(
            {
                "pid": pid,
                "ppid": proc.get("ppid"),
                "tmux_session": _extract_tmux_session(command),
                "cwd": _extract_windows_cd(command),
                "command": command,
            }
        )
    return targets


def detect_tui_sessions() -> dict[str, Any]:
    """Detect live Hermes TUI sessions and Windows Terminal WSL tabs."""
    warnings: list[str] = []
    linux_sessions: list[dict[str, Any]] = []
    windows_tabs: list[dict[str, Any]] = []

    try:
        linux_sessions = summarise_linux_tui_processes(iter_linux_processes())
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        warnings.append(f"linux_scan_failed: {exc}")

    try:
        windows_tabs = extract_windows_terminal_targets(scan_windows_terminal_processes())
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        warnings.append(f"windows_scan_failed: {exc}")

    return {
        "running": bool(linux_sessions or windows_tabs),
        "count": len(linux_sessions),
        "windows_terminal_tab_count": len(windows_tabs),
        "linux_sessions": linux_sessions,
        "windows_terminal_tabs": windows_tabs,
        "warnings": warnings,
    }
