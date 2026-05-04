import json
from pathlib import Path

from hermes_presence import app, config as config_mod
from hermes_presence.monitor import UnifiedMonitor
from hermes_presence.platforms import windows


class Args:
    json = False
    verbose = False
    fix = False
    restart = False
    profile = "main"
    log_file = None


def test_status_json_includes_reasoning_effort(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "presence.json"
    state_file.write_text(json.dumps({
        "version": 3,
        "timestamp": "2026-05-04T12:00:00+00:00",
        "activity": {"state": "working", "tool": "terminal", "detail": "Running tests"},
        "session": {
            "id": "s1",
            "started_at": "2026-05-04T11:59:00+00:00",
            "model": "gpt-5.5",
            "provider": "openai-codex",
            "reasoning_effort": "high",
        },
    }), encoding="utf-8")

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "presence.toml")
    monkeypatch.setattr(app, "_get_launcher", lambda *args, **kwargs: None)
    monkeypatch.setattr("hermes_presence.installer._detect_platform", lambda: "linux")
    monkeypatch.setenv("HERMES_PRESENCE_STATE", str(state_file))

    args = Args()
    args.json = True
    app._cmd_status(args)

    data = json.loads(capsys.readouterr().out)
    assert data["session"]["reasoning_effort"] == "high"


def test_monitor_can_hide_reasoning_and_apply_privacy_mode(tmp_path, monkeypatch):
    state_file = tmp_path / "presence.json"
    state_file.write_text(json.dumps({
        "version": 3,
        "timestamp": "2026-05-04T12:00:00+00:00",
        "activity": {"state": "working", "tool": "read_file", "detail": "Reading /secret/client-file.md"},
        "session": {
            "id": "s1",
            "started_at": "2026-05-04T11:59:00+00:00",
            "model": "gpt-5.5",
            "provider": "openai-codex",
            "reasoning_effort": "high",
            "tool_calls_count": 3,
            "subagent_count": 0,
        },
    }), encoding="utf-8")

    class FakeRpc:
        def __init__(self):
            self.updates = []
        def update(self, **kwargs):
            self.updates.append(kwargs)
        def clear(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr("hermes_presence.monitor.PYPRESENCE_AVAILABLE", True)
    monitor = UnifiedMonitor(
        client_id="123",
        state_file=state_file,
        show_reasoning=False,
        privacy_mode=True,
    )
    rpc = FakeRpc()
    monitor.connections = {0: rpc}
    monitor._poll_once()

    update = rpc.updates[0]
    assert "R: high" not in update["state"]
    assert "Reasoning:" not in update["large_text"]
    assert update["details"] == "Working privately"
    assert update["small_text"] == "private"


def test_windows_doctor_reports_visible_bat_and_legacy_task(monkeypatch, tmp_path):
    startup = tmp_path / "Startup"
    startup.mkdir()
    (startup / "hermes_presence.bat").write_text("python run_presence.py", encoding="utf-8")
    monkeypatch.setattr(windows, "STARTUP_DIR", startup)

    def fake_run_win(cmd, timeout=15):
        class Result:
            returncode = 0
            stdout = "Hermes Presence Monitor\n"
            stderr = ""
        return Result()

    monkeypatch.setattr(windows, "_run_win", fake_run_win)
    report = windows.diagnose_startup(profile="main")

    assert any(item["id"] == "visible_bat_launcher" for item in report["issues"])
    assert any(item["id"] == "legacy_scheduled_task" for item in report["issues"])


def test_cleanup_profiles_removes_stale_windows_profile_artifacts(monkeypatch, tmp_path):
    startup = tmp_path / "Startup"
    appdata = tmp_path / "Roaming"
    startup.mkdir()
    appdata.mkdir()
    (startup / "clinical_presence.vbs").write_text("", encoding="utf-8")
    (startup / "clinical_presence.bat").write_text("", encoding="utf-8")
    (appdata / "clinical_presence_monitor.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(windows, "STARTUP_DIR", startup)
    monkeypatch.setattr(windows, "_APPDATA", str(appdata))
    monkeypatch.setattr(windows, "_run_win", lambda *args, **kwargs: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    removed = windows.cleanup_profile_artifacts("clinical")

    assert removed
    assert not (startup / "clinical_presence.vbs").exists()
    assert not (startup / "clinical_presence.bat").exists()
    assert not (appdata / "clinical_presence_monitor.py").exists()


def test_update_command_can_restart_monitor(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=False):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(app.subprocess, "run", fake_run, raising=False)
    monkeypatch.setattr(app, "_cmd_restart", lambda args: calls.append(["restart"]))

    args = Args()
    args.restart = True
    app._cmd_update(args)

    assert ["restart"] in calls


def test_release_workflow_exists_and_builds_package():
    workflow = Path(".github/workflows/release.yml")
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    assert "python -m build" in text
    assert "pypa/gh-action-pypi-publish" in text
