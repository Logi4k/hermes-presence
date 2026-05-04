from pathlib import Path

from hermes_presence.platforms import windows
from hermes_presence.platforms.windows import _monitor_script_content


def test_windows_monitor_retries_without_watchdog_exit():
    script = _monitor_script_content("123", "presence.json")

    assert "continuing to retry" in script
    assert "exiting for watchdog restart" not in script
    assert "sys.exit(1)  # Exit with error to trigger Task Scheduler restart" not in script


def test_windows_monitor_template_displays_model_and_reasoning_metadata():
    script = _monitor_script_content(
        "123",
        "presence.json",
        fallback_reasoning_effort="high",
    )

    assert 'DEFAULT_REASONING_EFFORT = "high"' in script
    assert "gpt-5.5" in script
    assert "openai-codex" in script
    assert "_format_reasoning_label" in script
    assert '"large_text": " | ".join(hover_parts)' in script
    assert "hash_parts = [" in script
    assert "reasoning_effort," in script


def test_windows_startup_launcher_uses_pythonw_and_hidden_wscript_run(monkeypatch):
    monkeypatch.setattr(windows, "_windows_path_exists", lambda path: path.endswith("pythonw.exe"))

    launcher = windows._startup_launcher_vbs_content(
        r"C:\Users\LOGI4K\AppData\Local\Programs\Python\Python312\python.exe",
        r"C:\Users\LOGI4K\AppData\Roaming\hermes_presence_monitor.py",
    )

    assert "pythonw.exe" in launcher
    assert "python.exe" not in launcher
    assert "WshShell.Run" in launcher
    assert ", 0, False" in launcher
    assert '"""C:\\Users\\LOGI4K' in launcher


def test_pythonw_path_rewrites_standard_windows_python_exe_when_sibling_exists(monkeypatch):
    monkeypatch.setattr(windows, "_windows_path_exists", lambda path: path == r"C:\Python312\pythonw.exe")

    assert windows._pythonw_path(r"C:\Python312\python.exe") == r"C:\Python312\pythonw.exe"


def test_pythonw_path_falls_back_to_python_exe_when_sibling_missing(monkeypatch):
    monkeypatch.setattr(windows, "_windows_path_exists", lambda path: False)

    assert windows._pythonw_path(r"C:\Python312\python.exe") == r"C:\Python312\python.exe"


def test_pythonw_path_converts_wsl_python_path_before_rewrite(monkeypatch):
    monkeypatch.setattr(windows, "_is_wsl", lambda: True)
    monkeypatch.setattr(
        windows,
        "_windows_path_exists",
        lambda path: path == r"C:\Users\LOGI4K\AppData\Local\Programs\Python\Python312\pythonw.exe",
    )

    assert windows._pythonw_path(
        "/mnt/c/Users/LOGI4K/AppData/Local/Programs/Python/Python312/python.exe"
    ) == r"C:\Users\LOGI4K\AppData\Local\Programs\Python\Python312\pythonw.exe"


def test_windows_path_exists_converts_windows_paths_under_wsl(monkeypatch, tmp_path):
    fake_c = tmp_path / "c" / "Users" / "LOGI4K" / "pythonw.exe"
    fake_c.parent.mkdir(parents=True)
    fake_c.write_text("")

    monkeypatch.setattr(windows, "_is_wsl", lambda: True)
    monkeypatch.setattr(
        windows,
        "_win_to_wsl_path",
        lambda path: str(fake_c) if path == r"C:\Users\LOGI4K\pythonw.exe" else path,
    )

    assert windows._windows_path_exists(r"C:\Users\LOGI4K\pythonw.exe") is True


def test_windows_user_candidates_ignore_default_profile(monkeypatch, tmp_path):
    users = tmp_path / "Users"
    (users / "Default" / "AppData" / "Roaming").mkdir(parents=True)
    (users / "LOGI4K" / "AppData" / "Roaming").mkdir(parents=True)

    monkeypatch.delenv("WINDOWS_USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setattr(windows, "_detect_wsl", lambda: False)
    monkeypatch.setattr(windows, "Path", lambda value: users if value == "/mnt/c/Users" else Path(value))

    assert windows._windows_user_candidates() == ["LOGI4K"]


def test_main_profile_disables_legacy_scheduled_task_name():
    launcher = windows.WindowsLauncher("123", Path("presence.json"))

    assert launcher._legacy_task_names() == ("Hermes Presence Monitor",)
