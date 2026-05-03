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
            "openrouter": "via OpenRouter",
            "google": "Google",
            "xai": "xAI",
            "meta": "Meta",
            "mistral": "Mistral",
        }.get(provider.lower(), provider.capitalize())
        label = f"{label} ({provider_display})"

    return label


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
        poll_interval: int = 5,
        pipe_connect_retry: int = 3,
        large_image: str = "hermes_logo",
        large_text: str = "Hermes Agent",
        show_hermes_button: bool = True,
        show_nexus_button: bool = False,
        custom_buttons: Optional[list[dict]] = None,
        logger=None,
    ):
        if not PYPRESENCE_AVAILABLE:
            raise RuntimeError("pypresence is required. Install: pip install pypresence")

        self.client_id = client_id
        self.state_file = state_file
        self.exclude_tools = set(exclude_tools or [])
        self.idle_timeout = idle_timeout
        self.show_model = show_model
        self.show_provider = show_provider
        self.poll_interval = poll_interval
        self.pipe_connect_retry = pipe_connect_retry
        self.large_image = large_image
        self.large_text = large_text
        self.show_hermes_button = show_hermes_button
        self.show_nexus_button = show_nexus_button
        self.custom_buttons = custom_buttons or []

        self.logger = logger

        self.platform = _detect_platform()
        self.connections: dict[int, Presence] = {}
        self.last_hash = ""
        self.session_start: Optional[datetime] = None
        self._last_push_monotonic = 0.0
        self._republish_interval = max(30, int(self.poll_interval) * 6)

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
    ):
        """Push presence update to all connected pipes."""
        dead = []
        for pipe_num, rpc in self.connections.items():
            try:
                kwargs: dict[str, Any] = {
                    "state": state_text,
                    "details": details,
                    "large_image": self.large_image,
                    "large_text": self.large_text,
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
        print("[start] Hermes Presence Monitor v3.1.2", flush=True)
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
                self._poll_once()
            except Exception as e:
                print(f"[err] {e}", flush=True)
                if self.logger:
                    self.logger.log_event("poll_error", {"error": str(e)})

            time.sleep(self.poll_interval)

    def _poll_once(self):
        """Read state file, push to Discord if changed."""
        if not self.state_file.exists():
            if self.last_hash:
                self.disconnect_all()
                self.last_hash = ""
            return

        raw = self.state_file.read_text(encoding="utf-8")
        state = json.loads(raw)

        act = state.get("activity", {})
        sess = state.get("session", {})
        state_name = act.get("state", "thinking")
        detail = act.get("detail", "")
        tool = act.get("tool") or ""
        subagent_count = sess.get("subagent_count", 0)
        tool_started_at = act.get("tool_started_at")
        is_error = act.get("is_error", False)

        # ---- Tool exclude filter (Tier 3.16) ----
        if tool in self.exclude_tools:
            # Still show working state but without tool detail
            tool = ""
            detail = "Working..."

        # ---- Override state for errors (Tier 3.13) ----
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

        # ---- Model + provider display (Tier 2.5, 3.11) ----
        model_label = ""
        if self.show_model:
            model_label = _format_model_label(
                sess.get("model", ""),
                sess.get("provider", ""),
                show_provider=self.show_provider,
            )
        if model_label:
            state_text = f"{state_text} -- {model_label}"

        # ---- Tool-specific icon (Tier 1, already v2) ----
        small_img = _resolve_small_icon(tool, state_name)
        small_text = tool or state_name

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

        # ---- Hash for change detection ----
        # Use tool name + state, NOT the precise ISO timestamp
        # (timestamp changes every second, causing unnecessary Discord pushes)
        hash_parts = [
            state_text,
            details,
            tool,
            str(sess.get("id", "")),
            str(sess.get("started_at", "")),
            str(sess.get("tool_calls_count", 0)),
            str(subagent_count),
        ]
        # Tier 4 additions
        hash_parts.append(str(sess.get("files_modified", 0)))
        hash_parts.append(str(act.get("is_error", False)))

        new_hash = "|".join(hash_parts)

        now_mono = time.monotonic()
        should_republish = (now_mono - self._last_push_monotonic) >= self._republish_interval

        if new_hash != self.last_hash or should_republish:
            # ---- Sub-agent party size (Tier 1) ----
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
            # Tier 4: cost
            cost = sess.get("cost_usd")
            if cost and cost > 0:
                extras.append(f"${cost:.4f}")
            # Tier 4: files
            files = sess.get("files_modified", 0)
            if files > 0:
                extras.append(f"{files} files")
            # Tier 4: cron/orchestrator (from session, not top-level state)
            is_cron = sess.get("is_cron", False)
            if is_cron:
                extras.append("cron")
            is_orch = sess.get("is_orchestrator", False)
            if is_orch:
                extras.append("orch")

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
        poll_interval=cfg.advanced.poll_interval,
        pipe_connect_retry=cfg.advanced.pipe_connect_retry,
        large_image=cfg.display.large_image,
        large_text=cfg.display.large_text,
        show_hermes_button=cfg.buttons.hermes_github,
        show_nexus_button=cfg.buttons.nexus_dashboard,
        custom_buttons=cfg.buttons.custom_urls,
    )
