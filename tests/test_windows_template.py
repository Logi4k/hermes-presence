from hermes_presence.platforms.windows import _monitor_script_content


def test_windows_monitor_retries_without_watchdog_exit():
    script = _monitor_script_content("123", "presence.json")

    assert "continuing to retry" in script
    assert "exiting for watchdog restart" not in script
    assert "sys.exit(1)  # Exit with error to trigger Task Scheduler restart" not in script
