import json
import tempfile
from pathlib import Path

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
