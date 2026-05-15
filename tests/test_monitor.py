import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from hermes_presence import monitor as monitor_mod
from hermes_presence.monitor import UnifiedMonitor


class FakeRpc:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def clear(self):
        pass

    def close(self):
        pass


def _write_state(path: Path, *, session_id="s1", started_at=None, state="idle", detail="Waiting for input", timestamp=None):
    now = datetime.now(timezone.utc)
    started_at = started_at or now.isoformat()
    timestamp = timestamp or now.isoformat()
    path.write_text(json.dumps({
        "version": 3,
        "timestamp": timestamp,
        "activity": {
            "state": state,
            "tool": None,
            "detail": detail,
            "tool_started_at": None,
            "is_error": False,
        },
        "session": {
            "id": session_id,
            "started_at": started_at,
            "model": "deepseek-v4-pro",
            "provider": "deepseek",
            "reasoning_effort": "high",
            "tool_calls_count": 0,
            "subagent_count": 0,
            "files_modified": 0,
        },
    }), encoding="utf-8")


def _monitor(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_mod, "PYPRESENCE_AVAILABLE", True)
    m = UnifiedMonitor(client_id="123", state_file=tmp_path / "presence.json", privacy_mode=False, show_model=True, show_reasoning=True)
    m._republish_interval = 3600
    rpc = FakeRpc()
    m.connections = {0: rpc}
    return m, rpc


def test_session_restart_repushes_same_visible_idle_state(tmp_path, monkeypatch):
    state_file = tmp_path / "presence.json"
    _write_state(state_file, session_id="s1", started_at="2026-05-03T12:00:00+00:00")
    m, rpc = _monitor(tmp_path, monkeypatch)

    m._poll_once()
    m._poll_once()
    assert len(rpc.updates) == 1

    _write_state(state_file, session_id="s2", started_at="2026-05-03T12:05:00+00:00")
    m._poll_once()

    assert len(rpc.updates) == 2


def test_periodic_republish_exercises_idle_discord_pipe(tmp_path, monkeypatch):
    state_file = tmp_path / "presence.json"
    _write_state(state_file)
    m, rpc = _monitor(tmp_path, monkeypatch)
    m._republish_interval = 30

    m._poll_once()
    m._poll_once()
    assert len(rpc.updates) == 1

    m._last_push_monotonic -= 31
    m._poll_once()

    assert len(rpc.updates) == 2


def test_thinking_presence_uses_answering_copy(tmp_path, monkeypatch):
    state_file = tmp_path / "presence.json"
    _write_state(state_file, state="thinking", detail="Composing reply")
    m, rpc = _monitor(tmp_path, monkeypatch)

    m._poll_once()

    assert rpc.updates[0]["state"].startswith("Answering")
    assert rpc.updates[0]["details"] == "Composing reply"


def test_presence_includes_model_and_reasoning_in_state_and_hover(tmp_path, monkeypatch):
    state_file = tmp_path / "presence.json"
    _write_state(state_file, state="working", detail="Executing Python")
    m, rpc = _monitor(tmp_path, monkeypatch)

    m._poll_once()

    update = rpc.updates[0]
    assert "DeepSeek V4 Pro" in update["state"]
    assert "R: high" in update["state"]
    assert "Model: DeepSeek V4 Pro" in update["large_text"]
    assert "Reasoning: high" in update["large_text"]


def test_stale_state_without_tui_does_not_publish(tmp_path, monkeypatch):
    import hermes_presence.tui_sessions as tui_sessions

    state_file = tmp_path / "presence.json"
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _write_state(state_file, state="thinking", detail="Composing reply", timestamp=stale_ts)
    monkeypatch.setattr(tui_sessions, "detect_tui_sessions", lambda: {"count": 0})
    m, rpc = _monitor(tmp_path, monkeypatch)

    m._poll_once()

    assert rpc.updates == []
    assert m.connections == {}
