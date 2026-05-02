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

from hermes_presence.config import is_disabled, get_state_file_path, load_config
from hermes_presence.writer import get_writer

# Profile detection
_PROFILE = os.environ.get("HERMES_PROFILE", "main")
_STATE_FILE = get_state_file_path(_PROFILE)

# Cron / orchestrator detection
_IS_CRON = any(
    os.environ.get(v, "").strip()
    for v in ["HERMES_CRON_JOB_ID", "CRON_JOB_ID", "HERMES_SCHEDULED"]
)
_IS_ORCHESTRATOR = os.environ.get("HERMES_ORCHESTRATOR", "").strip() == "1"


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
        writer.idle()

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
    is_first_turn = payload.get("is_first_turn", False)
    model = payload.get("model", os.environ.get("HERMES_MODEL", "unknown"))
    provider = payload.get("provider", os.environ.get("HERMES_PROVIDER", "unknown"))
    # Platform from payload or env
    platform = payload.get("platform", "")

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
    model = payload.get("model", os.environ.get("HERMES_MODEL", "unknown"))
    provider = payload.get("provider", os.environ.get("HERMES_PROVIDER", "unknown"))
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
    child_status = payload.get("child_status", "completed")
    child_role = payload.get("child_role", "leaf")
    # Approximate: decrement by 1 for each stopped subagent
    # (batch tasks report as a single stop with task count in the payload)
    task_count = payload.get("task_count", 1)
    current = writer._subagent_count
    if current > 0:
        writer.set_subagent_count(max(0, current - task_count))
    # If all sub-agents done, return to idle
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

    writer = get_writer(_STATE_FILE)
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
