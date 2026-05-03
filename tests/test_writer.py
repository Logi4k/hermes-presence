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


def test_process_tool_has_specific_label():
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "presence.json"
        writer = PresenceWriter(state_file=state_file)
        writer.set_session("test-model", "test-provider")
        writer.tool_call("process", {})

        data = json.loads(state_file.read_text())
        assert data["activity"]["detail"] == "Monitoring background process"
        assert data["activity"]["detail"] != "Using process"


def test_wsl_username_helper_does_not_create_nul_file(tmp_path, monkeypatch):
    class Result:
        stdout = "LOGI4K\n"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(writer_mod.subprocess, "run", lambda *args, **kwargs: Result())

    assert writer_mod._get_windows_username() == "LOGI4K"
    assert not (tmp_path / "nul").exists()
