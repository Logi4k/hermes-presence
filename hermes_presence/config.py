"""
Configuration system for hermes-presence.

Reads from (in priority order):
1. Environment variables (HERMES_DISCORD_CLIENT_ID, HERMES_PRESENCE_STATE, etc.)
2. Config file: ~/.hermes/presence.toml
3. Built-in defaults

CLI commands read/write the config file via Config.save().
"""

import os
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore[assignment]
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore

DEFAULT_CONFIG_PATH = Path.home() / ".hermes" / "presence.toml"
DISABLE_MARKER = Path.home() / ".hermes" / ".presence_disabled"


@dataclass
class DisplayConfig:
    show_model: bool = True
    show_provider: bool = True
    idle_timeout: int = 10
    large_image: str = "hermes_logo"
    large_text: str = "Hermes Agent"


@dataclass
class DiscordConfig:
    client_id: str = ""


@dataclass
class WindowsConfig:
    force_windows_ipc: bool = False
    state_file_mirror: bool = True


@dataclass
class ToolsConfig:
    exclude: list[str] = field(default_factory=list)


@dataclass
class ButtonsConfig:
    hermes_github: bool = True
    nexus_dashboard: bool = False
    custom_urls: list[dict] = field(default_factory=list)


@dataclass
class AdvancedConfig:
    poll_interval: int = 5
    pipe_connect_retry: int = 3
    log_file: str = ""  # path to JSON-lines log, empty = disabled


@dataclass
class PresenceConfig:
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    windows: WindowsConfig = field(default_factory=WindowsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    buttons: ButtonsConfig = field(default_factory=ButtonsConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)


def _env_client_id() -> str:
    """Read client ID from environment."""
    for var in ("HERMES_DISCORD_CLIENT_ID", "DISCORD_CLIENT_ID"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return ""


def _env_state_file() -> Optional[str]:
    """Read custom state file path from environment."""
    return os.environ.get("HERMES_PRESENCE_STATE", "").strip() or None


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base dict."""
    for key, val in overlay.items():
        if isinstance(val, dict) and key in base and isinstance(base[key], dict):
            base[key] = _deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def _dataclass_to_dict(dc) -> dict:
    """Convert a dataclass to dict, stripping None values at leaf level."""
    d = asdict(dc)
    # Remove None values from leaf dicts
    for section in d.values():
        if isinstance(section, dict):
            for k in list(section.keys()):
                if section[k] is None:
                    del section[k]
    return d


def load_config(config_path: Optional[Path] = None) -> PresenceConfig:
    """Load config from file + environment, merge in priority order.

    Priority: env vars > config file > defaults
    """
    config = PresenceConfig()

    # Layer 1: Config file
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)

            # discord section
            if "discord" in raw:
                dc = raw["discord"]
                if "client_id" in dc:
                    config.discord.client_id = str(dc["client_id"]).strip()

            # display section
            if "display" in raw:
                dp = raw["display"]
                for key in ("show_model", "show_provider"):
                    if key in dp:
                        setattr(config.display, key, bool(dp[key]))
                if "idle_timeout" in dp:
                    config.display.idle_timeout = int(dp["idle_timeout"])
                for key in ("large_image", "large_text"):
                    if key in dp:
                        setattr(config.display, key, str(dp[key]))

            # windows section
            if "windows" in raw:
                w = raw["windows"]
                for key in ("force_windows_ipc", "state_file_mirror"):
                    if key in w:
                        setattr(config.windows, key, bool(w[key]))

            # tools section
            if "tools" in raw and "exclude" in raw["tools"]:
                config.tools.exclude = [str(x) for x in raw["tools"]["exclude"]]

            # buttons section
            if "buttons" in raw:
                b = raw["buttons"]
                for key in ("hermes_github", "nexus_dashboard"):
                    if key in b:
                        setattr(config.buttons, key, bool(b[key]))
                if "custom_urls" in b:
                    config.buttons.custom_urls = list(b["custom_urls"])

            # advanced section
            if "advanced" in raw:
                a = raw["advanced"]
                if "poll_interval" in a:
                    config.advanced.poll_interval = int(a["poll_interval"])
                if "pipe_connect_retry" in a:
                    config.advanced.pipe_connect_retry = int(a["pipe_connect_retry"])
                if "log_file" in a:
                    config.advanced.log_file = str(a["log_file"])

        except Exception as e:
            # Corrupt config — warn and use defaults
            print(f"[WARN] Could not parse config file ({path}): {e}", file=sys.stderr)
            print("[WARN] Using default configuration.", file=sys.stderr)

    # Layer 2: Environment variables (highest priority)
    env_id = _env_client_id()
    if env_id:
        config.discord.client_id = env_id

    return config


def _write_toml(d: dict, path: Path):
    """Pure-Python TOML writer for simple nested dicts.

    Handles str, int, float, bool, list-of-str/list-of-dict values.
    Nested dicts become [section.subsection] headers.
    """
    lines = []

    for section, data in d.items():
        if not isinstance(data, dict):
            continue
        lines.append(f"[{section}]")
        for k, v in data.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            elif isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{k} = "{escaped}"')
            elif isinstance(v, list):
                items = []
                for item in v:
                    if isinstance(item, str):
                        escaped = item.replace("\\", "\\\\").replace('"', '\\"')
                        items.append(f'"{escaped}"')
                    elif isinstance(item, dict):
                        inner = ", ".join(
                            f"{ik} = {iv}" if not isinstance(iv, str) else f'{ik} = "{iv}"'
                            for ik, iv in item.items()
                        )
                        items.append(f"{{ {inner} }}")
                    else:
                        items.append(str(item))
                lines.append(f"{k} = [{', '.join(items)}]")
            elif isinstance(v, dict):
                inner = ", ".join(
                    f'{ik} = "{iv}"' if isinstance(iv, str) else f"{ik} = {iv}" for ik, iv in v.items()
                )
                lines.append(f"{{ {inner} }}")
            else:
                lines.append(f"{k} = {v}")
        lines.append("")

    # Remove trailing blank line
    if lines and lines[-1] == "":
        lines.pop()

    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def save_config(config: PresenceConfig, config_path: Optional[Path] = None):
    """Save config to disk as TOML.

    Uses tomli_w if available, falls back to a pure-Python writer.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    d = _dataclass_to_dict(config)

    # Remove keys with default/empty values for a cleaner file.
    # Preserve prescribed fields even when empty/zero, and never
    # strip lists (an empty list is a valid config, e.g. exclude_tools = [])
    _keep = {"idle_timeout", "poll_interval"}
    for section_name, section_data in list(d.items()):
        if isinstance(section_data, dict):
            cleaned = {}
            for k, v in section_data.items():
                if k in _keep:
                    cleaned[k] = v
                elif isinstance(v, list):
                    cleaned[k] = v  # preserve empty lists
                elif v not in ("", False, 0):
                    cleaned[k] = v
            d[section_name] = cleaned

    # Remove entirely empty sections
    d = {k: v for k, v in d.items() if v}

    # Also remove sections where every value is an empty list
    for k in list(d):
        if isinstance(d[k], dict) and all(isinstance(v, list) and len(v) == 0 for v in d[k].values()):
            del d[k]

    if tomli_w is not None:
        with open(path, "wb") as f:
            tomli_w.dump(d, f)
    else:
        _write_toml(d, path)


def is_disabled() -> bool:
    """Check if presence is temporarily disabled via marker file."""
    return DISABLE_MARKER.exists()


def set_disabled(disabled: bool):
    """Create or remove the disable marker file."""
    DISABLE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    if disabled:
        DISABLE_MARKER.touch()
    else:
        DISABLE_MARKER.unlink(missing_ok=True)


def get_client_id() -> str:
    """Get the resolved client ID from config or env."""
    config = load_config()
    return config.discord.client_id


def get_state_file_path(profile: str = "main") -> Path:
    """Get the state file path, respecting env override and profile.

    Main profile: ~/.hermes/state/presence.json
    Apollo profile: ~/.hermes/state/apollo_presence.json
    Other profiles: ~/.hermes/state/{profile}_presence.json
    """
    env_path = _env_state_file()
    if env_path:
        return Path(env_path)

    if profile == "main":
        return Path.home() / ".hermes" / "state" / "presence.json"
    return Path.home() / ".hermes" / "state" / f"{profile}_presence.json"


def get_mirror_path(profile: str = "main") -> Optional[Path]:
    """Get the Windows mirror path for WSL2 setups.

    Profile-aware: main → hermes_presence.json, others → {profile}_presence.json
    """
    windows_user = os.environ.get("WINDOWS_USER", "").strip()
    if windows_user:
        filename = "hermes_presence.json" if profile == "main" else f"{profile}_presence.json"
        return Path(f"/mnt/c/Users/{windows_user}/AppData/Roaming/{filename}")
    return None


def verify_config(config_path: Optional[Path] = None) -> bool:
    """Read back the config file and validate basic invariants.

    Prints warnings for issues but does not raise. Returns True if no
    warnings were emitted.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    ok = True

    if not path.exists():
        print(f"[WARN] Config file not found: {path}", file=sys.stderr)
        return False

    try:
        config = load_config(path)
    except Exception as e:
        print(f"[WARN] Could not load config from {path}: {e}", file=sys.stderr)
        return False

    # client_id must be non-empty
    if not config.discord.client_id:
        print(
            "[WARN] discord.client_id is empty — set a Discord application client ID",
            file=sys.stderr,
        )
        ok = False

    # state_file_path must exist or its parent dir must be writable
    state_file_path = get_state_file_path()
    if not state_file_path.exists():
        parent = state_file_path.parent
        if not parent.exists():
            if os.access(os.getcwd(), os.W_OK):
                print(
                    f"[WARN] State file directory {parent} does not exist; "
                    "it will be created on first run",
                    file=sys.stderr,
                )
        elif not os.access(parent, os.W_OK):
            print(
                f"[WARN] State file parent directory {parent} is not writable",
                file=sys.stderr,
            )
            ok = False

    # poll_interval must be > 0
    if config.advanced.poll_interval <= 0:
        print("[WARN] advanced.poll_interval must be > 0", file=sys.stderr)
        ok = False

    return ok
