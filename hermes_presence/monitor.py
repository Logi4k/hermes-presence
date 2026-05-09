"""
Unified cross-platform Discord Rich Presence monitor.

Works on Linux, macOS, Windows, and WSL2 (via Windows-side runner).
Single codebase — detects OS and adjusts IPC mechanism automatically.

Features:
- Multi-pipe connection (stable + canary Discord)
- Auto-reconnect with cooldown
- Tool-specific icons with prefix matching
- Sub-agent party size tracking
- Per-tool elapsed timer
- Model + provider display
- Configurable idle timeout
- Tool exclude filter
- Error state detection
- Graceful degradation (no crash if Discord not running)
- Unicode-safe console output (ASCII only, no → in print)
- Profiles: reads profile from state file
- Session duration tracking
- Cost display (Tier 4)
- Cron/orchestrator indicators (Tier 4)
"""

import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from pypresence import DiscordNotFound, PipeClosed, Presence

    PYPRESENCE_AVAILABLE = True
except ImportError:
    PYPRESENCE_AVAILABLE = False

from .tool_icons import TOOL_ICON_MAP

# ---- Constants ----

PIPES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

ACTIVITY_MAP = {
    "starting": ("Launching Hermes", "Starting session..."),
    "thinking": ("Answering", "Composing reply"),
    "error": ("Error", None),
    "offline": ("Offline", "Session ended"),
    "orchestrating": ("Orchestrating", None),
    "cron_job": ("Cron Job", None),
    "session_ended": ("Session Ended", None),
}


def _find_latest_state_file(state_dir: Path) -> tuple[Path, dict] | tuple[None, None]:
    """Scan for all presence_*.json files and return the newest by timestamp.

    Returns (path, parsed_data) or (None, None) if no valid files found.
    """
    if not state_dir.exists():
        return None, None

    candidates: list[tuple[Path, dict, float]] = []

    for f in state_dir.glob("presence_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str)
            ts_epoch = ts.timestamp()
            candidates.append((f, data, ts_epoch))
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    # Also check legacy presence.json for backward compat
    legacy = state_dir / "presence.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                ts_epoch = ts.timestamp()
                candidates.append((legacy, data, ts_epoch))
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    if not candidates:
        return None, None

    # Sort by timestamp descending, pick newest
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[0][0], candidates[0][1]


def _cleanup_stale_state_files(state_dir: Path, max_age_seconds: int = 3600) -> int:
    """Remove state files older than max_age_seconds. Returns count removed."""
    if not state_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
    removed = 0

    for f in state_dir.glob("presence_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str)
            if ts.timestamp() < cutoff:
                f.unlink()
                removed += 1
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    return removed


def _resolve_provider_logo(provider: str) -> str:
    """Return Discord asset key for a provider."""
    PROVIDER_LOGO = {
        "anthropic": "anthropic_logo",
        "openai": "openai_logo",
        "xai": "xai_logo",
        "google": "google_logo",
        "deepseek": "deepseek_logo",
        "meta": "meta_logo",
        "mistral": "mistral_logo",
        "openrouter": "openrouter_logo",
    }
    return PROVIDER_LOGO.get((provider or "").lower().strip(), "hermes_logo")


def _load_cost(cost_file: Optional[Path]) -> tuple[float, str]:
    """Load daily cost accumulator from disk. Returns (cost, day_stamp)."""
    if not cost_file or not cost_file.exists():
        return 0.0, datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        data = json.loads(cost_file.read_text(encoding="utf-8"))
        return data.get("cost", 0.0), data.get("day", "")
    except (json.JSONDecodeError, OSError):
        return 0.0, datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _save_cost(cost_file: Optional[Path], cost: float, day: str):
    """Save daily cost accumulator to disk."""
    if not cost_file:
        return
    try:
        cost_file.parent.mkdir(parents=True, exist_ok=True)
        cost_file.write_text(json.dumps({"cost": cost, "day": day}), encoding="utf-8")
    except (OSError, IOError):
        pass


def _detect_platform() -> str:
    """Detect OS: 'linux', 'macos', 'windows', 'wsl2'."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    # Check for WSL2 (requires both proc/version match AND Windows filesystem)
    try:
        with open("/proc/version") as f:
            content = f.read().lower()
            if ("microsoft" in content or "wsl" in content) and Path("/mnt/c/Windows").exists():
                return "wsl2"
    except Exception:
        pass
    return "linux"


def _is_discord_running() -> bool:
    """Check if any Discord process appears to be running."""
    import subprocess

    try:
        platform = _detect_platform()
        if platform == "windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Discord.exe"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "Discord.exe" in result.stdout
        else:
            pgrep_result = subprocess.run(["pgrep", "-x", "Discord"], capture_output=True, timeout=5)
            return pgrep_result.returncode == 0
    except Exception:
        return True  # Assume running if we can't check


def _format_model_label(model: str, provider: str, show_provider: bool = True) -> str:
    """Build a compact model label from session info."""
    MODEL_SHORTEN = {
        "claude-sonnet-4": "Claude Sonnet 4",
        "claude-opus-4": "Claude Opus 4",
        "claude-haiku-4": "Claude Haiku 4",
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "deepseek-v4": "DeepSeek V4",
        "deepseek-r1": "DeepSeek R1",
        "gpt-5.5": "GPT-5.5",
        "gpt-4o": "GPT-4o",
        "gpt-4.5": "GPT-4.5",
        "gpt-5": "GPT-5",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "llama-4-maverick": "Llama 4 Maverick",
        "llama-4-scout": "Llama 4 Scout",
        "mistral-large": "Mistral Large",
        "qwen3": "Qwen 3",
    }

    label = model or ""
    for pattern, display in MODEL_SHORTEN.items():
        if pattern in label.lower():
            label = display
            break

    if show_provider and provider:
        provider_display = {
            "deepseek": "DeepSeek",
            "anthropic": "Anthropic",
            "openai": "OpenAI",
            "openai-codex": "Codex",
            "openrouter": "via OpenRouter",
            "google": "Google",
            "xai": "xAI",
            "meta": "Meta",
            "mistral": "Mistral",
        }.get(provider.lower(), provider.capitalize())
        label = f"{label} ({provider_display})"

    return label


def _format_reasoning_label(reasoning_effort: str) -> str:
    """Build a compact reasoning-effort label from session info."""
    effort = str(reasoning_effort or "").strip().lower()
    if not effort:
        return ""
    return {
        "minimal": "R: minimal",
        "low": "R: low",
        "medium": "R: medium",
        "high": "R: high",
        "xhigh": "R: xhigh",
        "none": "R: off",
    }.get(effort, f"R: {effort}")


def _resolve_small_icon(tool_name: str, state_name: str) -> Optional[str]:
    """Pick the best small_image icon for the current context."""
    if tool_name:
        icon = TOOL_ICON_MAP.get(tool_name)
        if icon:
            return icon
        for prefix in ("browser_", "delegate_"):
            if tool_name.startswith(prefix):
                return TOOL_ICON_MAP.get(prefix.rstrip("_"), "status_active")

    if state_name in ("working", "idle", "error"):
        return f"status_{state_name}"

    return None


def _format_duration(seconds: int) -> str:
    """Format seconds into a readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    mins = seconds // 60
    if mins < 60:
        return f"{mins}m {seconds % 60}s"
    hours = mins // 60
    return f"{hours}h {mins % 60}m"


class UnifiedMonitor:
    """Cross-platform Discord presence monitor."""

    def __init__(
        self,
        client_id: str,
        state_file: Path,
        exclude_tools: Optional[list[str]] = None,
        idle_timeout: int = 10,
        show_model: bool = True,
        show_provider: bool = True,
        show_reasoning: bool = True,
        privacy_mode: bool = False,
        poll_interval: int = 5,
        pipe_connect_retry: int = 3,
        large_image: str = "hermes_logo",
        large_text: str = "Hermes Agent",
        show_hermes_button: bool = True,
        show_nexus_button: bool = False,
        custom_buttons: Optional[list[dict]] = None,
        logger=None,
        # v3.4.0 features
        show_profile: bool = True,
        show_cost: bool = True,
        provider_logo_mode: bool = True,
        zombie_timeout_multiplier: int = 2,
        cost_tracker_file: Optional[Path] = None,
    ):
        if not PYPRESENCE_AVAILABLE:
            raise RuntimeError("pypresence is required. Install: pip install pypresence")

        self.client_id = client_id
        self.state_file = state_file
        self.exclude_tools = set(exclude_tools or [])
        self.idle_timeout = idle_timeout
        self.show_model = show_model
        self.show_provider = show_provider
        self.show_reasoning = show_reasoning
        self.privacy_mode = privacy_mode
        self.poll_interval = poll_interval
        self.pipe_connect_retry = pipe_connect_retry
        self.large_image = large_image
        self.large_text = large_text
        self.show_hermes_button = show_hermes_button
        self.show_nexus_button = show_nexus_button
        self.custom_buttons = custom_buttons or []

        # v3.4.0 features
        self.show_profile = show_profile
        self.show_cost = show_cost
        self.provider_logo_mode = provider_logo_mode
        self.zombie_timeout_multiplier = zombie_timeout_multiplier
        self.cost_tracker_file = cost_tracker_file
        self._last_seen_timestamp: Optional[float] = None
        self._zombie_cleared = False
        self._daily_cost: float = 0.0
        self._cost_day = ""

        self.logger = logger

        self.platform = _detect_platform()
        self.connections: dict[int, Presence] = {}
        self.last_hash = ""
        self.session_start: Optional[datetime] = None
        self._last_push_monotonic = 0.0
        self._republish_interval = max(30, int(self.poll_interval) * 6)

        # v3.4.0: load accumulated daily cost
        cost_file = self.cost_tracker_file
        if cost_file is None:
            cost_file = Path.home() / ".hermes" / "state" / "daily_cost.json"
        self._daily_cost, self._cost_day = _load_cost(cost_file)

        # State tracking
        self._disconnected_notified = False

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGHUP, self._shutdown)

    # ---- Connection management ----

    def connect_all(self) -> bool:
        """Connect to every available Discord pipe."""
        for pipe_num in PIPES:
            if pipe_num in self.connections:
                continue
            try:
                rpc = Presence(self.client_id, pipe=pipe_num)
                rpc.connect()
                self.connections[pipe_num] = rpc
                print(f"[OK] Pipe {pipe_num} connected", flush=True)
            except DiscordNotFound:
                continue
            except Exception as e:
                print(f"[pipe {pipe_num}] {e}", flush=True)
                continue

        if self.connections:
            self._disconnected_notified = False
        return len(self.connections) > 0

    def disconnect_all(self):
        """Clear and close all connections."""
        for pipe_num, rpc in list(self.connections.items()):
            try:
                rpc.clear()
                rpc.close()
            except Exception:
                pass
        self.connections.clear()

    def update_all(
        self,
        state_text: str,
        details: str,
        small_img: Optional[str],
        small_text: str,
        start_ts: int,
        buttons: list[dict],
        party_size: Optional[int] = None,
        large_text: Optional[str] = None,
    ):
        """Push presence update to all connected pipes."""
        dead = []
        for pipe_num, rpc in self.connections.items():
            try:
                kwargs: dict[str, Any] = {
                    "state": state_text,
                    "details": details,
                    "large_image": self.large_image,
                    "large_text": large_text or self.large_text,
                    "small_image": small_img,
                    "small_text": small_text,
                    "start": start_ts,
                    "buttons": buttons,
                }
                if party_size is not None and party_size > 1:
                    kwargs["party_size"] = [party_size, party_size]

                rpc.update(**kwargs)
            except (PipeClosed, ConnectionError, OSError):
                print(f"[pipe {pipe_num}] Disconnected", flush=True)
                dead.append(pipe_num)
            except Exception as e:
                print(f"[pipe {pipe_num}] Error: {e}", flush=True)

        for pipe_num in dead:
            try:
                self.connections[pipe_num].close()
            except Exception:
                pass
            del self.connections[pipe_num]

        if dead and self.logger:
            self.logger.log_event(
                "pipe_disconnect",
                {
                    "dead_pipes": dead,
                    "remaining_pipes": list(self.connections.keys()),
                },
            )

    # ---- Shutdown ----

    def _shutdown(self, *args):
        self.disconnect_all()
        print("[END] Clean shutdown", flush=True)
        sys.exit(0)

    # ---- Main loop ----

    def run(self):
        """Main monitor loop. Blocks until interrupted."""
        print("[start] Hermes Presence Monitor v3.4.0", flush=True)
        print(f"[start] Platform: {self.platform}", flush=True)
        print(f"[start] State file: {self.state_file}", flush=True)
        print(f"[start] Poll interval: {self.poll_interval}s", flush=True)

        if self.logger:
            self.logger.log_event(
                "monitor_start",
                {
                    "platform": self.platform,
                    "state_file": str(self.state_file),
                    "poll_interval": self.poll_interval,
                },
            )

        if self.platform == "wsl2":
            print(
                "[FATAL] WSL2 detected -- Discord IPC does not work under WSL.",
                flush=True,
            )
            print("[FATAL] Run the monitor on the Windows side instead.", flush=True)
            print("[FATAL] Install: hermes-presence install --wsl2", flush=True)
            if self.logger:
                self.logger.log_event("monitor_fatal", {"error": "wsl2_detected"})
            sys.exit(1)

        while True:
            prev_count = len(self.connections)
            self.connect_all()
            if len(self.connections) > prev_count:
                print("[OK] New pipe(s) connected, forcing state push", flush=True)
                self.last_hash = ""
                if self.logger:
                    self.logger.log_event(
                        "discord_connect",
                        {
                            "pipe_count": len(self.connections),
                            "pipes": list(self.connections.keys()),
                        },
                    )

            if not self.connections:
                if not self._disconnected_notified:
                    print("[wait] No Discord pipes available", flush=True)
                    self._disconnected_notified = True

                    if not _is_discord_running():
                        print("[wait] Discord does not appear to be running", flush=True)

                    if self.logger:
                        self.logger.log_event(
                            "discord_disconnect",
                            {
                                "discord_running": _is_discord_running(),
                            },
                        )

                time.sleep(self.pipe_connect_retry)
                continue

            try:
                # Remove stale per-session state files before reading latest activity.
                stale_removed = _cleanup_stale_state_files(self.state_file.parent)
                if stale_removed and self.logger:
                    self.logger.log_event(
                        "state_cleanup",
                        {
                            "removed_files": stale_removed,
                        },
                    )
                self._poll_once()
            except Exception as e:
                print(f"[err] {e}", flush=True)
                if self.logger:
                    self.logger.log_event("poll_error", {"error": str(e)})

            time.sleep(self.poll_interval)

    def _poll_once(self):
        """Read state file(s), pick newest by timestamp, push to Discord if changed."""
        state_file, state = _find_latest_state_file(self.state_file.parent)

        # v3.4.0 F6: zero TUI sessions + no valid state -> clear
        tui_count = 0
        try:
            from .tui_sessions import detect_tui_sessions
            tui = detect_tui_sessions()
            tui_count = tui.get("count", 0)
        except Exception:
            pass

        # Only clear immediately if zero TUI, no state, and we had something showing
        if tui_count == 0 and self.last_hash and state is None:
            self.disconnect_all()
            self.last_hash = ""
            self._zombie_cleared = False
            self._last_seen_timestamp = None
            print("[clear] No TUI sessions or state detected, cleared Discord", flush=True)
            return

        if state is None:
            if self.last_hash:
                self.disconnect_all()
                self.last_hash = ""
            return

        act = state.get("activity", {})
        sess = state.get("session", {})
        state_name = act.get("state", "thinking")
        detail = act.get("detail", "")
        tool = act.get("tool") or ""
        subagent_count = sess.get("subagent_count", 0)
        tool_started_at = act.get("tool_started_at")
        is_error = act.get("is_error", False)
        ts_str = state.get("timestamp", "")

        # v3.4.0 F1: heartbeat / zombie detection
        self._zombie_cleared = False
        if ts_str:
            try:
                ts_epoch = datetime.fromisoformat(ts_str).timestamp()
                # Only track fresh states (ignore old test fixtures)
                age_secs = datetime.now(timezone.utc).timestamp() - ts_epoch
                if age_secs < 86400:  # only track states created within 24h
                    self._last_seen_timestamp = ts_epoch
            except ValueError:
                pass

        if self._last_seen_timestamp and self.last_hash:
            stale_secs = datetime.now(timezone.utc).timestamp() - self._last_seen_timestamp
            zombie_threshold = self.idle_timeout * self.zombie_timeout_multiplier
            if stale_secs >= zombie_threshold and not self._zombie_cleared:
                self.disconnect_all()
                self.last_hash = ""
                self._zombie_cleared = True
                mins = int(stale_secs // 60)
                print(f"[clear] State stale ({mins}m old), cleared Discord", flush=True)
                return

        # ---- Tool exclude filter ----
        if self.privacy_mode:
            tool = ""
            detail = "Working privately"

        if tool in self.exclude_tools:
            tool = ""
            detail = "Working..."

        # ---- Override state for errors ----
        if is_error:
            state_name = "error"
            if not detail:
                detail = act.get("error_msg", "An error occurred")

        # ---- Activity template ----
        template = ACTIVITY_MAP.get(state_name, ("Active", None))
        state_text = template[0]
        details = detail or template[1] or ""
        if len(details) > 128:
            details = details[:125] + "..."

        # ---- Model + provider display ----
        model_label = ""
        if self.show_model:
            model_label = _format_model_label(
                sess.get("model", ""),
                sess.get("provider", ""),
                show_provider=self.show_provider,
            )
        if model_label:
            state_text = f"{state_text} -- {model_label}"

        if self.show_reasoning:
            reasoning_label = _format_reasoning_label(sess.get("reasoning_effort", ""))
        else:
            reasoning_label = ""
        if reasoning_label:
            state_text = f"{state_text} -- {reasoning_label}"

        # v3.4.0 F2: profile name in state
        profile = state.get("profile", "") or ""
        if not profile and state_file:
            # Try extracting from filename: {profile}_presence.json
            fname = state_file.name if isinstance(state_file, Path) else ""
            if "_presence" in fname and fname != "presence.json":
                profile = fname.split("_presence")[0] or ""
        if self.show_profile and profile and profile not in ("presence", "main"):
            state_text = f"{state_text} | {profile}"

        hover_parts = []
        if model_label:
            hover_parts.append(f"Model: {model_label}")
        if reasoning_label:
            hover_parts.append(f"Reasoning: {reasoning_label.replace('R: ', '')}")
        calls = sess.get("tool_calls_count", 0)
        hover_parts.append(f"Tool calls: {calls}")
        large_text = " | ".join(hover_parts) if hover_parts else self.large_text

        # ---- Tool-specific icon ----
        small_img = _resolve_small_icon(tool, state_name)
        small_text = "private" if self.privacy_mode else (tool or state_name)

        # ---- v3.4.0 F4: provider logo ----
        provider = str(sess.get("provider", "") or "").lower().strip()
        large_image = self.large_image
        if self.provider_logo_mode and provider:
            large_image = _resolve_provider_logo(provider)

        # ---- Per-tool timer ----
        if tool_started_at:
            start_ts = int(datetime.fromisoformat(tool_started_at).timestamp())
        else:
            start_ts = int(
                datetime.fromisoformat(
                    sess.get("started_at", datetime.now(timezone.utc).isoformat())
                ).timestamp()
            )

        # ---- Buttons ----
        buttons = []
        if self.show_hermes_button:
            buttons.append(
                {
                    "label": "Hermes Agent",
                    "url": "https://github.com/NousResearch/hermes-agent",
                }
            )
        if self.show_nexus_button:
            buttons.append(
                {
                    "label": "Nexus Dashboard",
                    "url": "http://localhost:5173",
                }
            )
        for cb in self.custom_buttons:
            if isinstance(cb, dict) and "label" in cb and "url" in cb:
                if len(buttons) < 2:
                    buttons.append(cb)

        # ---- v3.4.0 F3: cost tracking ----
        cost_display = ""
        cost = sess.get("cost_usd")
        if cost and isinstance(cost, (int, float)):
            # Rollover daily cost tracking
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._cost_day != today:
                self._daily_cost = 0.0
                self._cost_day = today
            self._daily_cost += float(cost)
            if self.cost_tracker_file is None:
                ct = Path.home() / ".hermes" / "state" / "daily_cost.json"
            else:
                ct = self.cost_tracker_file
            _save_cost(ct, self._daily_cost, today)

            if self.show_cost:
                cost_display = f"Session: ${float(cost):.2f}"
                if self._daily_cost > float(cost):
                    cost_display = f"{cost_display} | Today: ${self._daily_cost:.2f}"

        # Optional: prepend cost to details line
        if cost_display:
            details = f"{cost_display} -- {details}"

        # ---- Hash for change detection ----
        hash_parts = [
            state_text,
            details,
            tool,
            str(sess.get("id", "")),
            str(sess.get("started_at", "")),
            str(sess.get("tool_calls_count", 0)),
            str(subagent_count),
            str(sess.get("files_modified", 0)),
            str(act.get("is_error", False)),
            str(sess.get("reasoning_effort", "")),
            str(self.show_reasoning),
            str(self.privacy_mode),
            profile,
            large_image,
            cost_display,
        ]

        new_hash = "|".join(hash_parts)

        now_mono = time.monotonic()
        should_republish = (now_mono - self._last_push_monotonic) >= self._republish_interval

        if new_hash != self.last_hash or should_republish:
            # ---- Sub-agent party size ----
            party = None
            if subagent_count > 0:
                party = subagent_count + 1

            self.update_all(
                state_text,
                details,
                small_img,
                small_text,
                start_ts,
                buttons,
                party_size=party,
                large_text=large_text,
            )
            self.last_hash = new_hash
            self._last_push_monotonic = now_mono

            # ---- Console output (ASCII-safe) ----
            pipe_list = ",".join(str(p) for p in self.connections)
            extras = []
            if subagent_count > 0:
                extras.append(f"{subagent_count} subs")
            if tool:
                extras.append(f"icon={small_img}")
            if cost and cost > 0:
                extras.append(f"${cost:.4f}")
            files = sess.get("files_modified", 0)
            if files > 0:
                extras.append(f"{files} files")
            is_cron = sess.get("is_cron", False)
            if is_cron:
                extras.append("cron")
            is_orch = sess.get("is_orchestrator", False)
            if is_orch:
                extras.append("orch")
            if profile and profile not in ("presence", "main"):
                extras.append(f"profile={profile}")
            if provider:
                extras.append(f"logo={large_image}")

            extra_str = f" ({', '.join(extras)})" if extras else ""
            print(
                f"[update -> pipes {pipe_list}] {state_text}: {details}{extra_str}",
                flush=True,
            )


def create_monitor(
    client_id: Optional[str] = None,
    state_file: Optional[Path] = None,
    config_path: Optional[Path] = None,
    exclude_tools: Optional[list[str]] = None,
) -> UnifiedMonitor:
    """Factory function — creates a configured UnifiedMonitor.

    Prefers explicit args, falls back to config file + env vars.
    """
    from .config import get_state_file_path, load_config

    cfg = load_config(config_path)

    return UnifiedMonitor(
        client_id=client_id or cfg.discord.client_id,
        state_file=state_file or get_state_file_path(),
        exclude_tools=exclude_tools or cfg.tools.exclude,
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
    )
