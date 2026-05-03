"""
Shared tool icon mappings for hermes-presence.

Used by both writer.py (hook events / state generation) and
monitor.py (Discord Rich Presence display).

Single source of truth — update TOOL_ICONS here and both
consumers stay in sync.
"""

# Full mapping: tool_name -> {detail_template, large_image_key}
# detail_template may contain {path} placeholder
TOOL_ICONS: dict[str, dict[str, str]] = {
    "delegate_task": {
        "detail": "Orchestrating sub-agents",
        "large_image": "status_monitoring",
    },
    "delegate_tasks": {
        "detail": "Orchestrating sub-agents",
        "large_image": "status_monitoring",
    },  # alias
    "read_file": {"detail": "Reading {path}", "large_image": "status_active"},
    "write_file": {"detail": "Writing {path}", "large_image": "status_active"},
    "patch": {"detail": "Editing {path}", "large_image": "status_active"},
    "terminal": {"detail": "Running command", "large_image": "status_working"},
    "execute_code": {"detail": "Executing Python", "large_image": "status_working"},
    "web_search": {"detail": "Searching the web", "large_image": "status_researching"},
    "web_extract": {
        "detail": "Extracting web content",
        "large_image": "status_researching",
    },
    "browser_navigate": {
        "detail": "Browsing the web",
        "large_image": "status_researching",
    },
    "browser_click": {
        "detail": "Interacting with page",
        "large_image": "status_researching",
    },
    "browser_type": {
        "detail": "Filling form fields",
        "large_image": "status_researching",
    },
    "browser_snapshot": {
        "detail": "Inspecting page",
        "large_image": "status_researching",
    },
    "browser_back": {"detail": "Navigating back", "large_image": "status_researching"},
    "browser_scroll": {"detail": "Scrolling page", "large_image": "status_researching"},
    "browser_console": {
        "detail": "Checking browser console",
        "large_image": "status_researching",
    },
    "browser_vision": {
        "detail": "Taking screenshot",
        "large_image": "status_researching",
    },
    "memory": {"detail": "Storing memory", "large_image": "status_active"},
    "send_message": {"detail": "Sending message", "large_image": "status_active"},
    "skill_view": {"detail": "Loading skill", "large_image": "status_researching"},
    "skill_manage": {"detail": "Managing skill", "large_image": "status_active"},
    "vision_analyze": {
        "detail": "Analyzing image",
        "large_image": "status_researching",
    },
    "image_generate": {"detail": "Generating image", "large_image": "status_working"},
    "text_to_speech": {"detail": "Generating speech", "large_image": "status_working"},
    "session_search": {
        "detail": "Searching memory",
        "large_image": "status_researching",
    },
    "clarify": {"detail": "Asking for clarification", "large_image": "status_active"},
    "search_files": {"detail": "Searching files", "large_image": "status_active"},
    "todo": {"detail": "Managing task list", "large_image": "status_active"},
    "cronjob": {"detail": "Managing cron jobs", "large_image": "status_working"},
    "process": {"detail": "Monitoring background process", "large_image": "status_active"},
}

# Simplified mapping for Discord large_image lookup (derived from TOOL_ICONS)
TOOL_ICON_MAP: dict[str, str] = {tool: meta["large_image"] for tool, meta in TOOL_ICONS.items()}
