import json
import tempfile
from pathlib import Path

from hermes_presence import writer as writer_mod
from hermes_presence.writer import PresenceWriter


def test_writer_creates_state_file():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.tool_call("terminal", {"command": "ls"})
        writer.idle()

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["activity"]["state"] == "idle"
        assert data["session"]["model"] == "test-model"
        assert "workspace" in data
        assert "project" in data["workspace"]


def test_thinking_uses_polished_detail():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.thinking()

        data = json.loads(state_file.read_text())
        assert data["activity"]["state"] == "thinking"
        assert data["activity"]["detail"] == "Composing reply"
        assert "Generating response" not in data["activity"]["detail"]


def test_writer_persists_and_restores_reasoning_effort():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("gpt-5.5", "openai-codex", reasoning_effort="high")
        writer.idle()

        data = json.loads(state_file.read_text())
        assert data["session"]["reasoning_effort"] == "high"

        fresh_writer = PresenceWriter(state_file=state_file)
        fresh_writer.tool_call("terminal", {"command": "pwd"})

        data = json.loads(state_file.read_text())
        assert data["session"]["model"] == "gpt-5.5"
        assert data["session"]["provider"] == "openai-codex"
        assert data["session"]["reasoning_effort"] == "high"


def test_process_tool_has_specific_label():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.tool_call("process", {})

        data = json.loads(state_file.read_text())
        assert data["activity"]["detail"] == "Monitoring background process"
        assert data["activity"]["detail"] != "Using process"


def test_writer_extracts_display_target_from_tool_params():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.tool_call("read_file", {"path": "/mnt/e/project/monitor.py"})

        data = json.loads(state_file.read_text())
        assert data["activity"]["target"] == "monitor.py"


def test_reviewing_tool_results_keeps_activity_visible_after_fast_tools():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.tool_call("read_file", {"path": "writer.py"})
        writer.reviewing_tool_results("read_file")

        data = json.loads(state_file.read_text())
        assert data["activity"]["state"] == "thinking"
        assert data["activity"]["tool"] == "read_file"
        assert data["activity"]["detail"] == "Reviewing file results"
        assert data["activity"]["tool_started_at"] is not None


def test_wsl_username_helper_does_not_create_nul_file(tmp_path, monkeypatch):
    class Result:
        stdout = "LOGI4K\n"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(writer_mod.subprocess, "run", lambda *args, **kwargs: Result())

    assert writer_mod._get_windows_username() == "LOGI4K"
    assert not (tmp_path / "nul").exists()


def test_get_writer_preserves_session_id_for_singleton(tmp_path):
    writer_mod._writers.clear()
    state_file = tmp_path / "presence_test-session.json"

    writer = writer_mod.get_writer(state_file=state_file, session_id="test-session")

    assert writer._session_id == "test-session"
    assert writer_mod.get_writer(state_file=state_file) is writer


def test_get_writer_backfills_session_id_on_existing_singleton(tmp_path):
    writer_mod._writers.clear()
    state_file = tmp_path / "presence_test-session.json"

    writer = writer_mod.get_writer(state_file=state_file)
    assert writer._session_id == ""

    same_writer = writer_mod.get_writer(state_file=state_file, session_id="test-session")

    assert same_writer is writer
    assert same_writer._session_id == "test-session"
