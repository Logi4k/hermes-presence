
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from hermes_presence.monitor import _find_latest_state_file, _cleanup_stale_state_files


def test_find_latest_state_file_picks_newest():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        now = datetime.now(timezone.utc)

        # Old session
        old = d / "presence_old123.json"
        old.write_text(json.dumps({
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "activity": {"state": "idle"},
            "session": {"model": "old-model"},
        }))

        # New session
        new = d / "presence_new456.json"
        new.write_text(json.dumps({
            "timestamp": now.isoformat(),
            "activity": {"state": "working"},
            "session": {"model": "new-model"},
        }))

        path, data = _find_latest_state_file(d)
        assert path == new
        assert data["session"]["model"] == "new-model"


def test_cleanup_stale_state_files_removes_old():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        now = datetime.now(timezone.utc)

        # Stale file
        stale = d / "presence_stale.json"
        stale.write_text(json.dumps({
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "activity": {"state": "idle"},
            "session": {},
        }))

        # Fresh file
        fresh = d / "presence_fresh.json"
        fresh.write_text(json.dumps({
            "timestamp": now.isoformat(),
            "activity": {"state": "working"},
            "session": {},
        }))

        removed = _cleanup_stale_state_files(d, max_age_seconds=3600)
        assert removed == 1
        assert not stale.exists()
        assert fresh.exists()


def test_find_latest_includes_legacy_presence_json():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        now = datetime.now(timezone.utc)

        legacy = d / "presence.json"
        legacy.write_text(json.dumps({
            "timestamp": now.isoformat(),
            "activity": {"state": "thinking"},
            "session": {"model": "legacy"},
        }))

        path, data = _find_latest_state_file(d)
        assert path == legacy
        assert data["session"]["model"] == "legacy"
