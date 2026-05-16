#!/usr/bin/env python3
"""
Shell-hook bridge for hermes-presence.

Reads Hermes shell hook payload from stdin (JSON), translates to
hermes_presence hook calls, and writes state updates.

Usage in config.yaml:
  hooks:
    pre_tool_call:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
    post_tool_call:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
    pre_llm_call:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
    on_session_start:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
    on_session_end:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
    subagent_stop:
      - command: /mnt/e/hermes-projects/hermes-presence/scripts/hermes-hook-bridge.py
"""

import json
import os
import sys
from pathlib import Path

# Add parent to sys.path so we can import hermes_presence
_package_root = Path(__file__).resolve().parent.parent
if str(_package_root) not in sys.path:
    sys.path.insert(0, str(_package_root))

from hermes_presence.config import is_disabled, get_state_file_path, load_config  # noqa: E402
from hermes_presence.writer import get_writer  # noqa: E402

# Profile detection
_PROFILE = os.environ.get("HERMES_PROFILE", "main")

# Session ID detection (TUI/gateway sessions get unique state files)
_SESSION_ID = ""
_IS_TUI_SESSION = False
try:
    _tui_session_file = os.environ.get("HERMES_TUI_ACTIVE_SESSION_FILE", "").strip()
    if _tui_session_file:
        with open(_tui_session_file) as _f:
            _SESSION_ID = json.load(_f).get("session_id", "")
        _IS_TUI_SESSION = bool(_SESSION_ID)
except Exception:
    pass
if not _SESSION_ID:
    _SESSION_ID = os.environ.get("HERMES_SESSION_ID", "").strip()

# Cron / orchestrator detection
_IS_CRON = any(
    os.environ.get(v, "").strip() for v in ["HERMES_CRON_JOB_ID", "CRON_JOB_ID", "HERMES_SCHEDULED"]
)
_IS_ORCHESTRATOR = os.environ.get("HERMES_ORCHESTRATOR", "").strip() == "1"


def _payload_extra(payload: dict) -> dict:
    """Return shell-hook extras, tolerating malformed payloads."""
    extra = payload.get("extra", {})
    return extra if isinstance(extra, dict) else {}


def _payload_value(payload: dict, key: str, default=None):
    """Read a value from top-level payload, then shell-hook `extra`.

    Hermes shell hooks serialize only a small allowlist at top level and place
    fields such as model/platform/provider in `extra`. The bridge historically
    read only top-level keys, which meant richer session metadata silently fell
    back to environment defaults.
    """
    value = payload.get(key)
    if value not in (None, ""):
        return value
    value = _payload_extra(payload).get(key)
    if value not in (None, ""):
        return value
    return default


def _payload_session_id(payload: dict) -> str:
    """Resolve session ID from environment first, then hook payload."""
    return _SESSION_ID or str(_payload_value(payload, "session_id", "") or "").strip()


def handle_pre_tool_call(payload: dict, writer):
    """Tool about to execute."""
    tool_name = payload.get("tool_name", "unknown")
    params = payload.get("args", {}) or payload.get("tool_input", {})
    writer.tool_call(tool_name, params)


def handle_post_tool_call(payload: dict, writer):
    """Tool completed (success or error)."""
    error = payload.get("error")
    if error:
        writer.error(str(error)[:100])
    else:
        # Do not immediately fall back to idle. Most Hermes tools finish faster
        # than Discord's polling interval, so an instant idle update hides the
        # task entirely. Keep a short "reviewing results" state until the next
        # LLM/final idle hook takes over.
        writer.reviewing_tool_results(payload.get("tool_name", ""))

    # Track file modifications
    tool_name = payload.get("tool_name", "")
    if tool_name in ("write_file", "patch", "skill_manage"):
        writer.file_modified()

    # Track cost if available
    cost = payload.get("cost_usd")
    if cost is not None:
        writer.add_cost(cost)


def handle_pre_llm_call(payload: dict, writer):
    """Before LLM call — model info, thinking state."""
    is_first_turn = bool(_payload_value(payload, "is_first_turn", False))
    model = _payload_value(payload, "model", os.environ.get("HERMES_MODEL", "unknown"))
    provider = _payload_value(payload, "provider", os.environ.get("HERMES_PROVIDER", "unknown"))

    if is_first_turn:
        writer.set_session(
            model=model,
            provider=provider,
            thinking=True,
            is_cron=_IS_CRON,
            is_orchestrator=_IS_ORCHESTRATOR,
            profile=_PROFILE,
        )
    else:
        writer.thinking()


def handle_post_llm_call(payload: dict, writer):
    """After LLM response."""
    # Return to idle state
    writer.idle()
    # Track cost from usage if present
    usage = payload.get("usage", {})
    if usage:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        # Rough cost estimate, actual cost should come from provider
        if input_tokens or output_tokens:
            # Delegate to writer's cost tracking (accurate costs come from Hermes)
            pass


def handle_on_session_start(payload: dict, writer):
    """Session started."""
    model = _payload_value(payload, "model", os.environ.get("HERMES_MODEL", "unknown"))
    provider = _payload_value(payload, "provider", os.environ.get("HERMES_PROVIDER", "unknown"))
    writer.set_session(
        model=model,
        provider=provider,
        is_cron=_IS_CRON,
        is_orchestrator=_IS_ORCHESTRATOR,
        profile=_PROFILE,
    )


def handle_on_session_end(payload: dict, writer):
    """Session ending."""
    writer.session_summary()


def handle_subagent_stop(payload: dict, writer):
    """Subagent completed — decrement subagent count."""
    task_count = payload.get("task_count", 1)
    current = writer._subagent_count
    if current > 0:
        writer.set_subagent_count(max(0, current - task_count))
    if writer._subagent_count <= 0:
        writer.idle()


# Event → handler mapping
HANDLERS = {
    "pre_tool_call": handle_pre_tool_call,
    "post_tool_call": handle_post_tool_call,
    "pre_llm_call": handle_pre_llm_call,
    "post_llm_call": handle_post_llm_call,
    "on_session_start": handle_on_session_start,
    "on_session_end": handle_on_session_end,
    "subagent_stop": handle_subagent_stop,
}


def main():
    if is_disabled():
        # Disabled — return empty JSON silently
        print(json.dumps({}))
        return 0

    try:
        if load_config().display.tui_only and not _IS_TUI_SESSION:
            print(json.dumps({}))
            return 0
    except Exception:
        pass

    # Read payload from stdin
    try:
        payload_str = sys.stdin.read()
        if not payload_str.strip():
            return 0
        payload = json.loads(payload_str)
    except (json.JSONDecodeError, Exception):
        return 0

    # Determine event from payload (Hermes v4+ includes hook_event_name)
    event = payload.get("hook_event_name", "")

    if not event or event not in HANDLERS:
        return 0

    session_id = _payload_session_id(payload)
    state_file = get_state_file_path(_PROFILE, session_id)
    writer = get_writer(state_file, session_id=session_id)

    # Restore model/provider and session stats from prior state file.
    # Each hook runs as a separate process with a fresh writer that
    # starts with model="unknown". Reading the existing state preserves
    # model, provider, tool_calls_count, files_modified, cost, etc.
    # Skip for on_session_start (new session, should start fresh).
    if event != "on_session_start":
        writer._restore_from_state_file()

    handler = HANDLERS[event]

    try:
        handler(payload, writer)
    except Exception:
        # Never crash Hermes — hooks are non-blocking
        pass

    # Return empty JSON (observer-only, no blocking)
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
