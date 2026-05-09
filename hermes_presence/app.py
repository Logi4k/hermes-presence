"""
CLI entry point for hermes-presence.

Usage:
    hermes-presence install        # Full setup wizard
    hermes-presence uninstall      # Remove everything
    hermes-presence status         # Show current state
    hermes-presence enable         # Re-enable after disable
    hermes-presence disable        # Temporarily disable
    hermes-presence config         # Show current config
    hermes-presence config set <key> <value>  # Update config
    hermes-presence run            # Run monitor in foreground (debug)

Environment variables:
    HERMES_DISCORD_CLIENT_ID       # Override client ID
    HERMES_PRESENCE_STATE          # Override state file path
"""

import argparse
import subprocess
import sys
from pathlib import Path


def _cmd_install(args):
    """Install hermes-presence (one-command setup)."""
    from .installer import install

    success = install(
        client_id=args.client_id,
        force=args.force,
        no_start=args.no_start,
        profile=args.profile,
        dry_run=getattr(args, "dry_run", False),
    )

    if success:
        print("\n[DONE] Hermes Presence installed successfully!")
        print("  Discord should now show your Hermes activity.")
        print("  Run 'hermes-presence status' to verify.")
        print("\n  Customize: hermes-presence config set display.show_provider false")
        print("  Disable:   hermes-presence disable")
        print("  Uninstall: hermes-presence uninstall")
    else:
        print("\n[FAIL] Installation encountered errors. Check messages above.")
        sys.exit(1)


def _cmd_uninstall(args):
    """Remove hermes-presence."""
    from .installer import uninstall

    profile = getattr(args, "profile", "main")
    success = uninstall(profile=profile)
    if success:
        print("\n[DONE] Hermes Presence removed.")
    else:
        print("\n[FAIL] Uninstall had errors (may already be removed).")
        sys.exit(1)


def _cmd_status(args):
    """Show current status. Use --json for machine-readable output."""
    from .config import get_state_file_path, is_disabled, load_config

    cfg = load_config()
    profile = getattr(args, "profile", "main")
    state_file = get_state_file_path(profile=profile)
    json_mode = getattr(args, "json", False)
    verbose = getattr(args, "verbose", False)

    if json_mode:
        import json as _json

        from .tui_sessions import detect_tui_sessions

        result = {
            "client_id_set": bool(cfg.discord.client_id),
            "state_file": str(state_file),
            "disabled": is_disabled(),
            "idle_timeout": cfg.display.idle_timeout,
            "show_model": cfg.display.show_model,
            "show_provider": cfg.display.show_provider,
            "show_reasoning": cfg.display.show_reasoning,
            "privacy_mode": cfg.display.privacy_mode,
            "poll_interval": cfg.advanced.poll_interval,
            "excluded_tools": cfg.tools.exclude,
            "service": {"running": False, "auto_start": False, "pid": None, "pid_age_s": None},
            "session": None,
            "tui_sessions": detect_tui_sessions(),
        }

        # Platform service status
        from .installer import _detect_platform

        platform = _detect_platform()
        try:
            launcher = _get_launcher(platform, cfg.discord.client_id, state_file, profile=profile)
            if launcher:
                s = launcher.status()
                result["service"]["running"] = s.get("running", False)
                result["service"]["auto_start"] = s.get("auto_start", False)
                result["service"]["pid"] = s.get("pid")
                if s.get("pid"):
                    pid_age = _get_pid_age(s["pid"])
                    result["service"]["pid_age_s"] = pid_age
        except Exception:
            pass

        # Session info from state file
        if state_file.exists():
            try:
                data = _json.loads(state_file.read_text(encoding="utf-8"))
                act = data.get("activity", {})
                sess = data.get("session", {})
                started = sess.get("started_at", "")
                uptime = None
                if started:
                    try:
                        from datetime import datetime, timezone

                        dt = datetime.fromisoformat(started)
                        uptime = int((datetime.now(timezone.utc) - dt).total_seconds())
                    except Exception:
                        pass
                result["session"] = {
                    "state": act.get("state", "unknown"),
                    "tool": act.get("tool"),
                    "detail": act.get("detail", ""),
                    "model": sess.get("model"),
                    "provider": sess.get("provider"),
                    "reasoning_effort": sess.get("reasoning_effort", ""),
                    "tool_calls": sess.get("tool_calls_count", 0),
                    "subagents": sess.get("subagent_count", 0),
                    "files_modified": sess.get("files_modified", 0),
                    "cost_usd": sess.get("cost_usd", 0.0),
                    "uptime_seconds": uptime,
                }
            except Exception:
                pass

        print(_json.dumps(result, indent=2))
        return

    # --- Human-readable mode (existing behaviour) ---
    print("Hermes Presence Status")
    print("=" * 50)
    print(f"  Client ID:      {'[SET]' if cfg.discord.client_id else '[NOT SET]'}")
    print(f"  State file:     {state_file}")
    print(f"  Disabled:       {'Yes' if is_disabled() else 'No'}")
    print(f"  Idle timeout:   {cfg.display.idle_timeout}s")
    print(f"  Show model:     {cfg.display.show_model}")
    print(f"  Show provider:  {cfg.display.show_provider}")
    print(f"  Show reasoning: {cfg.display.show_reasoning}")
    print(f"  Privacy mode:   {cfg.display.privacy_mode}")
    print(f"  Poll interval:  {cfg.advanced.poll_interval}s")
    if cfg.notify.url:
        events_str = ", ".join(cfg.notify.events) if cfg.notify.events else "all"
        print(f"  Notify URL:     [SET] (events: {events_str})")
    if cfg.tools.exclude:
        print(f"  Excluded tools: {', '.join(cfg.tools.exclude)}")
    print()

    # Platform-specific status
    from .installer import _detect_platform

    platform = _detect_platform()

    try:
        launcher = _get_launcher(platform, cfg.discord.client_id, state_file, profile=profile)
        if launcher:
            s = launcher.status()
            print("Service Status")
            print("-" * 40)
            print(f"  Running:     {'Yes' if s.get('running') else 'No'}")
            print(f"  Auto-start:  {'Yes' if s.get('auto_start') else 'No'}")
            pid = s.get("pid")
            if pid:
                print(f"  PID:         {pid}")
                age = _get_pid_age(pid)
                if age is not None:
                    mins, secs = divmod(age, 60)
                    if mins > 0:
                        print(f"  PID age:     {mins}m {secs}s")
                    else:
                        print(f"  PID age:     {secs}s")
            if verbose and hasattr(launcher, "diagnostics"):
                diag = launcher.diagnostics()
                for key, value in diag.items():
                    print(f"  {key}: {value}")
            print()
    except ImportError:
        print("(Platform service status unavailable)")
        print()

    if state_file.exists():
        import json
        from datetime import datetime, timezone

        data = json.loads(state_file.read_text(encoding="utf-8"))
        act = data.get("activity", {})
        sess = data.get("session", {})

        print("Current Activity (from state file)")
        print("-" * 40)
        print(f"  State:        {act.get('state', 'unknown')}")
        print(f"  Tool:         {act.get('tool') or '(none)'}")
        print(f"  Detail:       {act.get('detail', '')[:80]}")
        print(f"  Model:        {sess.get('model', '?')}")
        print(f"  Provider:     {sess.get('provider', '?')}")
        print(f"  Reasoning:    {sess.get('reasoning_effort', '?')}")
        print(f"  Tool calls:   {sess.get('tool_calls_count', 0)}")
        print(f"  Sub-agents:   {sess.get('subagent_count', 0)}")
        print(f"  Files mod'd:  {sess.get('files_modified', 0)}")
        print(f"  Cost:         ${sess.get('cost_usd', 0):.4f}")

        started = sess.get("started_at", "")
        if started:
            try:
                dt = datetime.fromisoformat(started)
                uptime_seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
                mins, secs = divmod(uptime_seconds, 60)
                if mins >= 60:
                    hours, mins = divmod(mins, 60)
                    print(f"  Session uptime: {hours}h {mins}m {secs}s")
                elif mins > 0:
                    print(f"  Session uptime: {mins}m {secs}s")
                else:
                    print(f"  Session uptime: {secs}s")
            except Exception:
                pass

        ts = data.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                print(f"  Last update:  {dt.strftime('%H:%M:%S')}")
            except Exception:
                pass
        print()

    from .tui_sessions import detect_tui_sessions

    tui = detect_tui_sessions()
    if tui.get("running") or verbose:
        print("TUI Sessions")
        print("-" * 40)
        print(f"  Hermes TUI processes:     {tui.get('count', 0)}")
        print(f"  Windows Terminal tabs:    {tui.get('windows_terminal_tab_count', 0)}")

        for session in tui.get("linux_sessions", [])[:5]:
            label = session.get("session_id") or "unknown-session"
            cwd = session.get("cwd") or "unknown cwd"
            print(f"  PID {session.get('pid')}: {label} @ {cwd}")

        tabs = tui.get("windows_terminal_tabs", [])
        if verbose and tabs:
            print("  Windows Terminal WSL targets:")
            for tab in tabs[:5]:
                target = tab.get("tmux_session") or tab.get("cwd") or "wsl tab"
                print(f"    PID {tab.get('pid')}: {target}")

        for warning in tui.get("warnings", []):
            print(f"  Warning: {warning}")
        print()


def _cmd_enable(args):
    """Re-enable presence after disable."""
    from .config import set_disabled

    set_disabled(False)
    print("Hermes Presence enabled.")
    print("Run 'hermes-presence install' if the monitor isn't running.")


def _cmd_disable(args):
    """Temporarily disable presence."""
    from .config import set_disabled

    set_disabled(True)
    print("Hermes Presence disabled.")
    print("Run 'hermes-presence enable' to re-enable.")


def _cmd_config(args):
    """Show or update config."""
    from .config import DEFAULT_CONFIG_PATH, load_config, save_config

    a = args.args or []

    # Parse: ['show'] → show, ['set', 'key', 'value'] → set, ['key', 'value'] → set
    if not a or a == ["show"]:
        # Show config
        cfg = load_config()
        print("Current configuration:")
        print(f"  discord.client_id     = {'[SET]' if cfg.discord.client_id else '(not set)'}")
        print(f"  display.show_model    = {cfg.display.show_model}")
        print(f"  display.show_provider = {cfg.display.show_provider}")
        print(f"  display.show_reasoning = {cfg.display.show_reasoning}")
        print(f"  display.privacy_mode  = {cfg.display.privacy_mode}")
        print(f"  display.idle_timeout  = {cfg.display.idle_timeout}s")
        print(f"  display.large_image   = {cfg.display.large_image}")
        print(f"  display.large_text    = {cfg.display.large_text}")
        print(f"  advanced.poll_interval = {cfg.advanced.poll_interval}s")
        print(f"  tools.exclude         = {cfg.tools.exclude or '(none)'}")
        print(f"  buttons.hermes_github = {cfg.buttons.hermes_github}")
        print(f"  buttons.nexus_dashboard = {cfg.buttons.nexus_dashboard}")
        if cfg.notify.url:
            print("  notify.url            = [SET]")
            print(f"  notify.events         = {cfg.notify.events or '(all)'}")
        else:
            print("  notify.url            = (not set)")
        print()
        print(f"Config file: {DEFAULT_CONFIG_PATH}")
        if not DEFAULT_CONFIG_PATH.exists():
            print("  (no config file found — using defaults and env vars)")
        return

    # Determine key and value
    if a[0] == "set":
        if len(a) < 3:
            print("ERROR: 'config set' requires key and value")
            print("  Usage: hermes-presence config set <key> <value>")
            sys.exit(1)
        key = a[1]
        value = a[2]
    else:
        if len(a) < 2:
            print("ERROR: Config requires key and value")
            print("  Usage: hermes-presence config <key> <value>")
            sys.exit(1)
        key = a[0]
        value = a[1]

    # Set config
    cfg = load_config()

    # Navigate the dotted key path
    parts = key.split(".")
    if len(parts) < 2:
        print("ERROR: Config keys must be in format 'section.key' (e.g. 'discord.client_id')")
        sys.exit(1)

    section, field = parts[0], parts[1]

    # Convert value to appropriate type
    if field in ("exclude", "custom_urls", "events"):
        value = value.split(",") if value else []
    elif field in (
        "show_model",
        "show_provider",
        "show_reasoning",
        "privacy_mode",
        "force_windows_ipc",
        "state_file_mirror",
        "hermes_github",
        "nexus_dashboard",
    ):
        value = value.lower() in ("true", "yes", "1", "on")
    elif field in ("idle_timeout", "poll_interval", "pipe_connect_retry"):
        try:
            value = int(value)
        except ValueError:
            print(f"ERROR: '{field}' requires an integer value, got '{value}'")
            sys.exit(1)

    if section == "discord" and field == "client_id":
        cfg.discord.client_id = value
    elif section == "display":
        setattr(cfg.display, field, value)
    elif section == "windows":
        setattr(cfg.windows, field, value)
    elif section == "tools" and field == "exclude":
        cfg.tools.exclude = value if isinstance(value, list) else [value]
    elif section == "buttons":
        setattr(cfg.buttons, field, value)
    elif section == "advanced":
        setattr(cfg.advanced, field, value)
    elif section == "notify":
        setattr(cfg.notify, field, value)
    else:
        print(f"ERROR: Unknown config key: {key}")
        print("  Valid sections: discord, display, windows, tools, buttons, advanced, notify")
        sys.exit(1)

    save_config(cfg)
    print(f"Config saved: {key} = {value}")
    print(f"File: {DEFAULT_CONFIG_PATH}")


def _cmd_run(args):
    """Run the monitor in foreground (debug mode)."""
    from .config import get_state_file_path, load_config
    from .logging import get_logger
    from .monitor import UnifiedMonitor

    cfg = load_config()

    if not cfg.discord.client_id:
        print("ERROR: Discord Client ID is not set.")
        print("  Set it: hermes-presence config set discord.client_id YOUR_CLIENT_ID")
        print("  Or:     export HERMES_DISCORD_CLIENT_ID=YOUR_CLIENT_ID")
        sys.exit(1)

    # Set up logging
    log_path = getattr(args, "log_file", None) or cfg.advanced.log_file or None
    log = get_logger(Path(log_path) if log_path else None)
    profile = getattr(args, "profile", "main")

    monitor = UnifiedMonitor(
        client_id=cfg.discord.client_id,
        state_file=get_state_file_path(profile=profile),
        exclude_tools=cfg.tools.exclude,
        idle_timeout=cfg.display.idle_timeout,
        show_model=cfg.display.show_model,
        show_provider=cfg.display.show_provider,
        show_reasoning=cfg.display.show_reasoning,
        privacy_mode=cfg.display.privacy_mode,
        poll_interval=cfg.advanced.poll_interval,
        pipe_connect_retry=cfg.advanced.pipe_connect_retry,
        large_image=cfg.display.large_image,
        large_text=cfg.display.large_text,
        show_hermes_button=cfg.buttons.hermes_github,
        show_nexus_button=cfg.buttons.nexus_dashboard,
        custom_buttons=cfg.buttons.custom_urls,
        logger=log,
    )

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\n[stop] Interrupted by user", flush=True)
        monitor._shutdown()


def _cmd_help(args):
    """Show full help text."""
    parser = argparse.ArgumentParser(
        prog="hermes-presence",
        description="Cross-platform Discord Rich Presence for Hermes Agent",
    )
    parser.print_help()


def _cmd_version(args):
    """Show version information."""
    print("hermes-presence v3.3.0")


def _cmd_update(args):
    """Self-update hermes-presence from GitHub."""

    print("Updating hermes-presence...")
    print("=" * 40)

    # Try pip install --upgrade from GitHub
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "git+https://github.com/Logi4k/hermes-presence.git@main",
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print("[FAIL] Update failed. Check pip output above.")
        sys.exit(1)

    print()
    print("[DONE] hermes-presence updated to latest.")
    if getattr(args, "restart", False):
        _cmd_restart(args)
    else:
        print("Run 'hermes-presence restart' to restart the monitor.")


def _cmd_restart(args):
    """Restart the presence monitor."""
    from .config import get_state_file_path, load_config

    cfg = load_config()
    if not cfg.discord.client_id:
        print("ERROR: Discord Client ID is not set.")
        print("  Set it: hermes-presence config set discord.client_id YOUR_CLIENT_ID")
        sys.exit(1)

    from .installer import _detect_platform

    platform = _detect_platform()
    profile = getattr(args, "profile", "main")
    state_file = get_state_file_path(profile=profile)

    launcher = _get_launcher(platform, cfg.discord.client_id, state_file, profile=profile)
    if not launcher:
        print(f"ERROR: No launcher for platform {platform}")
        sys.exit(1)

    print(f"Restarting monitor for {platform}...")
    launcher.stop()
    import time

    time.sleep(1)
    if launcher.start():
        print("[OK] Monitor restarted")
    else:
        print("[WARN] Monitor may not have restarted. Try 'hermes-presence install --force'.")


def _cmd_doctor(args):
    """Diagnose common startup and runtime problems."""
    from .installer import _detect_platform

    platform = _detect_platform()
    print("Hermes Presence Doctor")
    print("=" * 40)
    print(f"Platform: {platform}")
    if platform not in ("windows", "wsl2"):
        print("No Windows startup checks needed on this platform.")
        return

    from .platforms.windows import diagnose_startup

    report = diagnose_startup(profile=getattr(args, "profile", "main"), fix=getattr(args, "fix", False))
    if not report["issues"]:
        print("[PASS] No known startup issues found")
    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['id']}: {issue['message']}")
    for fix in report.get("fixes", []):
        print(f"[FIX] {fix}")


def _cmd_cleanup_profiles(args):
    """Remove stale Windows profile launchers and monitors."""
    from .platforms.windows import cleanup_profile_artifacts

    removed = []
    for profile in args.profiles:
        removed.extend(cleanup_profile_artifacts(profile))
    if removed:
        print("Removed stale profile artifacts:")
        for item in removed:
            print(f"  {item}")
    else:
        print("No stale profile artifacts found.")


def _get_launcher(platform: str, client_id: str, state_file, profile: str = "main"):
    """Get the platform launcher for the given OS."""
    try:
        if platform == "linux":
            from .platforms.linux import LinuxLauncher

            return LinuxLauncher(client_id, state_file)
        elif platform == "macos":
            from .platforms.macos import MacOSLauncher

            return MacOSLauncher(client_id, state_file)
        elif platform in ("windows", "wsl2"):
            from .platforms.windows import WindowsLauncher

            return WindowsLauncher(client_id, state_file, profile=profile)
    except ImportError:
        pass
    return None


def _get_pid_age(pid: int) -> int | None:
    """Get the age of a process in seconds, or None if unavailable."""
    try:
        import os

        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.exists():
            # Field 22 is starttime in clock ticks since boot
            parts = proc_stat.read_text().split()
            if len(parts) >= 22:
                start_ticks = int(parts[21])
                clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                start_sec = start_ticks / clk_tck
                uptime_sec = float(Path("/proc/uptime").read_text().split()[0])
                return int(uptime_sec - start_sec)
    except Exception:
        pass
    return None


def _cmd_validate(args):
    """Validate the installation."""
    from .config import get_state_file_path, load_config

    print("Validating Hermes Presence Installation")
    print("=" * 50)

    # Check 1: Config (client_id set)
    try:
        cfg = load_config()
        if cfg.discord.client_id:
            print("  [PASS] discord.client_id is set")
        else:
            print("  [FAIL] discord.client_id is not set")
    except Exception as e:
        print(f"  [FAIL] Could not load config: {e}")

    # Check 2: State file path valid
    try:
        state_file = get_state_file_path()
        print(f"  [PASS] State file path: {state_file}")
    except Exception as e:
        print(f"  [FAIL] State file path invalid: {e}")

    # Check 3: pypresence installed
    try:
        from importlib.util import find_spec

        if find_spec("pypresence"):
            print("  [PASS] pypresence is installed")
        else:
            raise ImportError
    except (ImportError, ModuleNotFoundError):
        print("  [FAIL] pypresence is not installed (pip install pypresence)")

    # Check 4: Discord reachable
    try:
        from pypresence import DiscordNotFound, Presence

        rpc = Presence("0" * 18, pipe=0)
        rpc.connect()
        rpc.close()
        print("  [PASS] Discord is reachable")
    except DiscordNotFound:
        print("  [FAIL] Discord is not running (start Discord first)")
    except Exception as e:
        print(f"  [PASS] Discord check inconclusive (pypresence error: {e})")

    # Check 5: powershell.exe on WSL/Windows
    try:
        import subprocess

        result = subprocess.run(
            ["powershell.exe", "-Command", "echo ok"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print("  [PASS] powershell.exe is available")
        else:
            print("  [WARN] powershell.exe returned non-zero")
    except FileNotFoundError:
        # Not on Windows/WSL, this is expected
        pass
    except Exception:
        pass

    print()


def main():
    parser = argparse.ArgumentParser(
        prog="hermes-presence",
        description="Cross-platform Discord Rich Presence for Hermes Agent",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # install
    p_install = subparsers.add_parser("install", help="Full one-command setup")
    p_install.add_argument("--client-id", help="Discord Application Client ID")
    p_install.add_argument("--force", action="store_true", help="Force reinstall")
    p_install.add_argument("--no-start", action="store_true", help="Don't start immediately")
    p_install.add_argument(
        "--profile",
        default="main",
        help="Profile to install for (default, research, or any custom profile)",
    )
    p_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without installing",
    )

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="Remove hermes-presence")
    p_uninstall.add_argument("--profile", default="main", help="Profile to uninstall (default: main)")

    # status
    p_status = subparsers.add_parser("status", help="Show current status")
    p_status.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_status.add_argument(
        "--verbose",
        action="store_true",
        help="Show launcher paths and platform details",
    )
    p_status.add_argument("--profile", default="main", help="Profile to inspect")

    # enable / disable
    subparsers.add_parser("enable", help="Re-enable after disable")
    subparsers.add_parser("disable", help="Temporarily disable presence")

    # config
    p_config = subparsers.add_parser("config", help="Show or update configuration")
    p_config.add_argument("args", nargs="*", help="[set] <key> <value> | <key> <value> | 'show'")

    # run
    p_run = subparsers.add_parser("run", help="Run monitor in foreground (debug)")
    p_run.add_argument(
        "--profile",
        default="main",
        help="Profile to monitor (default, research, or any custom profile)",
    )
    p_run.add_argument("--log-file", default=None, help="Path to write JSON-lines log output")

    # version
    parser.add_argument("--version", action="version", version="hermes-presence v3.3.0")

    # help subcommand
    subparsers.add_parser("help", help="Show detailed help")

    # version subcommand
    subparsers.add_parser("version", help="Show version")

    # validate subcommand
    subparsers.add_parser("validate", help="Validate installation")

    # update subcommand
    p_update = subparsers.add_parser("update", help="Self-update from GitHub")
    p_update.add_argument("--restart", action="store_true", help="Restart monitor after update")
    p_update.add_argument("--profile", default="main", help="Profile to restart after update")

    # restart subcommand
    p_restart = subparsers.add_parser("restart", help="Restart the monitor")
    p_restart.add_argument("--profile", default="main", help="Profile to restart")

    # doctor / cleanup
    p_doctor = subparsers.add_parser("doctor", help="Diagnose common startup issues")
    p_doctor.add_argument("--fix", action="store_true", help="Apply safe startup cleanup fixes")
    p_doctor.add_argument("--profile", default="main", help="Profile to diagnose")

    p_cleanup = subparsers.add_parser("cleanup-profiles", help="Remove stale Windows profile artifacts")
    p_cleanup.add_argument("profiles", nargs="+", help="Profile names to clean up")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "install": _cmd_install,
        "uninstall": _cmd_uninstall,
        "status": _cmd_status,
        "enable": _cmd_enable,
        "disable": _cmd_disable,
        "config": _cmd_config,
        "run": _cmd_run,
        "help": _cmd_help,
        "version": _cmd_version,
        "validate": _cmd_validate,
        "update": _cmd_update,
        "restart": _cmd_restart,
        "doctor": _cmd_doctor,
        "cleanup-profiles": _cmd_cleanup_profiles,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
