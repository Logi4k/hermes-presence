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
import os
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

    success = uninstall()
    if success:
        print("\n[DONE] Hermes Presence removed.")
    else:
        print("\n[FAIL] Uninstall had errors (may already be removed).")
        sys.exit(1)


def _cmd_status(args):
    """Show current status."""
    from .config import load_config, is_disabled, get_state_file_path

    cfg = load_config()
    state_file = get_state_file_path()

    print("Hermes Presence Status")
    print("=" * 50)
    print(f"  Client ID:      {'[SET]' if cfg.discord.client_id else '[NOT SET]'}")
    print(f"  State file:     {state_file}")
    print(f"  Disabled:       {'Yes' if is_disabled() else 'No'}")
    print(f"  Idle timeout:   {cfg.display.idle_timeout}s")
    print(f"  Show model:     {cfg.display.show_model}")
    print(f"  Show provider:  {cfg.display.show_provider}")
    print(f"  Poll interval:  {cfg.advanced.poll_interval}s")
    if cfg.tools.exclude:
        print(f"  Excluded tools: {', '.join(cfg.tools.exclude)}")
    print()

    # Platform-specific status
    from .installer import _detect_platform
    platform = _detect_platform()

    try:
        if platform == "linux":
            from .platforms.linux import LinuxLauncher
            launcher = LinuxLauncher(cfg.discord.client_id, state_file)
        elif platform == "macos":
            from .platforms.macos import MacOSLauncher
            launcher = MacOSLauncher(cfg.discord.client_id, state_file)
        elif platform in ("windows", "wsl2"):
            from .platforms.windows import WindowsLauncher
            launcher = WindowsLauncher(cfg.discord.client_id, state_file)
        else:
            launcher = None

        if launcher:
            s = launcher.status()
            print("Service Status")
            print("-" * 40)
            print(f"  Running:     {'Yes' if s.get('running') else 'No'}")
            print(f"  Auto-start:  {'Yes' if s.get('auto_start') else 'No'}")
            if s.get('pid'):
                print(f"  PID:         {s['pid']}")
            print()
    except ImportError:
        print("(Platform service status unavailable)")
        print()

    if state_file.exists():
        import json
        from datetime import datetime

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
        print(f"  Tool calls:   {sess.get('tool_calls_count', 0)}")
        print(f"  Sub-agents:   {sess.get('subagent_count', 0)}")
        print(f"  Files mod'd:  {sess.get('files_modified', 0)}")
        print(f"  Cost:         ${sess.get('cost_usd', 0):.4f}")

        ts = data.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                print(f"  Last update:  {dt.strftime('%H:%M:%S')}")
            except Exception:
                pass
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
    from .config import load_config, save_config, DEFAULT_CONFIG_PATH

    a = args.args or []

    # Parse: ['show'] → show, ['set', 'key', 'value'] → set, ['key', 'value'] → set
    if not a or a == ["show"]:
        # Show config
        cfg = load_config()
        print("Current configuration:")
        print(f"  discord.client_id     = {'[SET]' if cfg.discord.client_id else '(not set)'}")
        print(f"  display.show_model    = {cfg.display.show_model}")
        print(f"  display.show_provider = {cfg.display.show_provider}")
        print(f"  display.idle_timeout  = {cfg.display.idle_timeout}s")
        print(f"  display.large_image   = {cfg.display.large_image}")
        print(f"  display.large_text    = {cfg.display.large_text}")
        print(f"  advanced.poll_interval = {cfg.advanced.poll_interval}s")
        print(f"  tools.exclude         = {cfg.tools.exclude or '(none)'}")
        print(f"  buttons.hermes_github = {cfg.buttons.hermes_github}")
        print(f"  buttons.nexus_dashboard = {cfg.buttons.nexus_dashboard}")
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
        print(f"ERROR: Config keys must be in format 'section.key' (e.g. 'discord.client_id')")
        sys.exit(1)

    section, field = parts[0], parts[1]

    # Convert value to appropriate type
    if field in ("exclude", "custom_urls"):
        value = value.split(",") if value else []
    elif field in ("show_model", "show_provider", "force_windows_ipc",
                   "state_file_mirror", "hermes_github", "nexus_dashboard"):
        value = value.lower() in ("true", "yes", "1", "on")
    elif field in ("idle_timeout", "poll_interval", "pipe_connect_retry"):
        value = int(value)

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
    else:
        print(f"ERROR: Unknown config key: {key}")
        print("  Valid sections: discord, display, windows, tools, buttons, advanced")
        sys.exit(1)

    save_config(cfg)
    print(f"Config saved: {key} = {value}")
    print(f"File: {DEFAULT_CONFIG_PATH}")


def _cmd_run(args):
    """Run the monitor in foreground (debug mode)."""
    from .config import load_config, get_state_file_path
    from .monitor import UnifiedMonitor

    cfg = load_config()

    if not cfg.discord.client_id:
        print("ERROR: Discord Client ID is not set.")
        print("  Set it: hermes-presence config set discord.client_id YOUR_CLIENT_ID")
        print("  Or:     export HERMES_DISCORD_CLIENT_ID=YOUR_CLIENT_ID")
        sys.exit(1)

    monitor = UnifiedMonitor(
        client_id=cfg.discord.client_id,
        state_file=get_state_file_path(),
        exclude_tools=cfg.tools.exclude,
        idle_timeout=cfg.display.idle_timeout,
        show_model=cfg.display.show_model,
        show_provider=cfg.display.show_provider,
        poll_interval=cfg.advanced.poll_interval,
        pipe_connect_retry=cfg.advanced.pipe_connect_retry,
        large_image=cfg.display.large_image,
        large_text=cfg.display.large_text,
        show_hermes_button=cfg.buttons.hermes_github,
        show_nexus_button=cfg.buttons.nexus_dashboard,
        custom_buttons=cfg.buttons.custom_urls,
    )

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\n[stop] Interrupted by user", flush=True)
        monitor._shutdown()


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
    p_install.add_argument("--profile", default="main",
                           help="Profile to install for (main, apollo, or any custom profile)")

    # uninstall
    subparsers.add_parser("uninstall", help="Remove hermes-presence")

    # status
    subparsers.add_parser("status", help="Show current status")

    # enable / disable
    subparsers.add_parser("enable", help="Re-enable after disable")
    subparsers.add_parser("disable", help="Temporarily disable presence")

    # config
    p_config = subparsers.add_parser("config", help="Show or update configuration")
    p_config.add_argument("args", nargs="*", help="[set] <key> <value> | <key> <value> | 'show'")

    # run
    subparsers.add_parser("run", help="Run monitor in foreground (debug)")

    # version
    parser.add_argument("--version", action="version", version="hermes-presence v3.1.0")

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
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
