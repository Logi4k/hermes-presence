"""
One-command installer for hermes-presence.

Detects platform, sets up auto-start, walks through Discord App ID setup.
"""

import sys
import time
from pathlib import Path
from typing import Optional

from .config import get_state_file_path, load_config, save_config


def _detect_platform() -> str:
    """Detect the OS platform."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    try:
        with open("/proc/version") as f:
            content = f.read().lower()
            if ("microsoft" in content or "wsl" in content) and Path("/mnt/c/Windows").exists():
                return "wsl2"
    except Exception:
        pass
    return "linux"


def _walk_discord_setup(client_id: Optional[str] = None) -> str:
    """Walk user through Discord Application setup. Returns client_id."""
    if client_id and client_id.strip():
        return client_id.strip()

    print()
    print("=" * 60)
    print("  Discord Application Setup")
    print("=" * 60)
    print()
    print("Hermes needs a Discord Application to display Rich Presence.")
    print("You only need to do this once.")
    print()
    print("Steps:")
    print("  1. Go to https://discord.com/developers/applications")
    print("  2. Click 'New Application'")
    print('  3. Name it "Hermes AI" (or anything you like)')
    print("  4. Copy the APPLICATION ID (long number under the name)")
    print("  5. Paste it below")
    print()

    cid = input("Discord Application Client ID: ").strip()
    if not cid:
        print("ERROR: Client ID is required.")
        sys.exit(1)

    # Validate Discord snowflake: 17-20 digits
    if not cid.isdigit() or not (17 <= len(cid) <= 20):
        print("ERROR: Client ID must be a numeric Discord snowflake (17-20 digits).")
        print(f"  You provided: {cid}")
        sys.exit(1)

    # Try to open the developer portal in a browser
    print()
    print("Optional: Upload art assets for better-looking presence.")
    print("  Go to Rich Presence > Art Assets in your Discord app.")
    # Resolve assets path: prefer importlib.resources (works for pip-installed),
    # fall back to Path(__file__).parent.parent, then show generic message
    try:
        import importlib.resources

        assets_path = importlib.resources.files("hermes_presence") / "assets"
        if assets_path.is_dir():
            assets_display = str(assets_path)
        else:
            raise FileNotFoundError()
    except Exception:
        assets_path = Path(__file__).parent.parent / "assets"
        if assets_path.is_dir():
            assets_display = str(assets_path)
        else:
            assets_display = "<package assets directory>"
    print(f"  Upload the 8 PNG files from: {assets_display}")
    print("  Name them: hermes_logo, status_active, status_error, status_idle,")
    print("            status_monitoring, status_researching, status_standby, status_working")
    print()

    return cid


def _install_config(client_id: str, config_path: Optional[Path] = None):
    """Save the client ID to config file."""
    cfg = load_config(config_path)
    cfg.discord.client_id = client_id
    save_config(cfg, config_path)
    print(f"[OK] Config saved to {config_path or '~/.hermes/presence.toml'}")


def _install_platform(
    platform: str,
    client_id: str,
    state_file: Path,
    no_start: bool = False,
    profile: str = "main",
) -> bool:
    """Set up platform-specific auto-start."""
    try:
        from .platforms import PlatformLauncher

        launcher: PlatformLauncher
        if platform == "linux":
            from .platforms.linux import LinuxLauncher

            launcher = LinuxLauncher(client_id, state_file)
        elif platform == "macos":
            from .platforms.macos import MacOSLauncher

            launcher = MacOSLauncher(client_id, state_file)
        elif platform in ("windows", "wsl2"):
            from .platforms.windows import WindowsLauncher

            launcher = WindowsLauncher(client_id, state_file, profile=profile)
        else:
            print(f"[SKIP] No auto-start mechanism for platform: {platform}")
            return True

        if launcher.is_installed():
            print(f"[OK] Auto-start already configured for {platform}")
            if not no_start:
                launcher.start()
            return True

        print(f"[INSTALL] Setting up auto-start for {platform}...")
        success = launcher.install()

        if success:
            print(f"[OK] Auto-start configured for {platform}")
            if not no_start:
                time.sleep(1)
                if launcher.start():
                    print("[OK] Monitor started")
                else:
                    print("[WARN] Monitor may not have started")
        else:
            print(f"[FAIL] Could not configure auto-start for {platform}")
            return False

        return True

    except ImportError as e:
        print(f"[WARN] Auto-start was not configured: platform module not available ({e})")
        return True
    except Exception as e:
        print(f"[ERROR] Platform setup failed: {e}")
        return False


def install(
    client_id: Optional[str] = None,
    force: bool = False,
    no_start: bool = False,
    config_path: Optional[Path] = None,
    profile: str = "main",
    dry_run: bool = False,
) -> bool:
    """Run the full installation flow.

    Returns True if successful, False on critical failure.
    """
    print("Hermes Presence Installer v3.1.2" + (f" (profile: {profile})" if profile != "main" else ""))
    print("=" * 40)

    platform = _detect_platform()
    print(f"Platform detected: {platform}")

    # Check pypresence
    try:
        import pypresence  # noqa: F401
    except ImportError:
        print("[ERROR] pypresence is required. Install with: pip install pypresence")
        return False

    # Step 1: Discord setup
    client_id = _walk_discord_setup(client_id)

    # Step 2: Save config
    if dry_run:
        print("[DRY RUN] Would save config with client_id")
    else:
        _install_config(client_id, config_path)

    # Step 3: Platform-specific setup
    state_file = get_state_file_path(profile)
    if dry_run:
        print(f"[DRY RUN] Would install platform auto-start for {platform}")
        platform_ok = True
    else:
        platform_ok = _install_platform(
            platform, client_id, state_file, no_start=no_start, profile=profile
        )

    # Step 4: Verify state file directory exists
    if not dry_run:
        state_file.parent.mkdir(parents=True, exist_ok=True)

    # Step 5: Summary
    print()
    print("=" * 40)
    print("Installation complete!")
    print(f"  Platform:   {platform}")
    print(f"  State file: {state_file}")
    print(f"  Auto-start: {'Yes' if platform_ok else 'Manual'}")
    print()
    print("Next time you run Hermes, your activity will appear in Discord.")
    print()
    print("Commands:")
    print("  hermes-presence status   — Check if running")
    print("  hermes-presence disable  — Temporarily hide presence")
    print("  hermes-presence config   — Customize display")
    print("  hermes-presence run      — Run in foreground (debug)")

    # Step 6: Check if Discord is running
    if not dry_run:
        try:
            from pypresence import Presence

            rpc = Presence(0)
            rpc.connect()
            rpc.close()
        except Exception:
            print()
            print(
                "WARNING: Discord does not appear to be running. "
                "Presence won't show until Discord starts."
            )

    return client_id is not None and bool(client_id.strip())


def uninstall(profile: str = "main") -> bool:
    """Remove hermes-presence auto-start and config."""
    print("Hermes Presence Uninstaller")
    print("=" * 40)

    platform = _detect_platform()
    state_file = get_state_file_path(profile)

    # Stop and remove platform-specific setup
    try:
        from .platforms import PlatformLauncher

        launcher: PlatformLauncher | None = None
        if platform == "linux":
            from .platforms.linux import LinuxLauncher

            launcher = LinuxLauncher("", state_file)
        elif platform == "macos":
            from .platforms.macos import MacOSLauncher

            launcher = MacOSLauncher("", state_file)
        elif platform in ("windows", "wsl2"):
            from .platforms.windows import WindowsLauncher

            launcher = WindowsLauncher("", state_file, profile=profile)
        else:
            launcher = None

        if launcher and launcher.is_installed():
            print(f"[UNINSTALL] Removing auto-start for {platform}...")
            launcher.stop()
            time.sleep(1)
            launcher.uninstall()
            print("[OK] Auto-start removed")
    except Exception as e:
        print(f"[WARN] Could not remove auto-start: {e}")

    # Remove disabled marker
    from .config import DISABLE_MARKER

    DISABLE_MARKER.unlink(missing_ok=True)

    print()
    print("Uninstall complete.")
    print("  Config file preserved (delete manually to fully remove).")
    print("  State files preserved.")

    return True
