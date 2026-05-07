from hermes_presence.tui_sessions import (
    extract_windows_terminal_targets,
    summarise_linux_tui_processes,
)


def test_detects_hermes_tui_process_and_descendant_session_key():
    processes = [
        {
            "pid": 100,
            "ppid": 1,
            "args": [
                "/home/logi4k/.hermes/hermes-agent/venv/bin/python3",
                "/home/logi4k/.local/bin/hermes",
                "chat",
                "--tui",
                "--pass-session-id",
            ],
            "cwd": "/mnt/e/hermes-projects",
        },
        {
            "pid": 101,
            "ppid": 100,
            "args": ["node", "/home/logi4k/.hermes/hermes-agent/ui-tui/dist/entry.js"],
            "cwd": "/mnt/e/hermes-projects",
        },
        {
            "pid": 102,
            "ppid": 101,
            "args": [
                "/home/logi4k/.hermes/hermes-agent/venv/bin/python3",
                "-m",
                "tui_gateway.slash_worker",
                "--session-key",
                "20260506_190359_be2d58",
            ],
            "cwd": "/mnt/e/hermes-projects",
        },
    ]

    sessions = summarise_linux_tui_processes(processes)

    assert len(sessions) == 1
    assert sessions[0]["pid"] == 100
    assert sessions[0]["session_id"] == "20260506_190359_be2d58"
    assert sessions[0]["cwd"] == "/mnt/e/hermes-projects"


def test_resume_session_id_is_used_when_present():
    processes = [
        {
            "pid": 200,
            "ppid": 1,
            "args": [
                "python3",
                "-P",
                "/home/logi4k/.local/bin/hermes",
                "chat",
                "--resume",
                "20260505_223454_ae6e59",
                "--accept-hooks",
                "--tui",
            ],
            "cwd": "/mnt/e/hermes-projects/modern-fitness-app/mobile-app",
        }
    ]

    sessions = summarise_linux_tui_processes(processes)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "20260505_223454_ae6e59"


def test_windows_terminal_wsl_tmux_targets_are_detected_once():
    processes = [
        {
            "pid": 10,
            "ppid": 1,
            "name": "WindowsTerminal.exe",
            "command": "wt.exe new-tab wsl.exe -e bash",
        },
        {
            "pid": 11,
            "ppid": 10,
            "name": "OpenConsole.exe",
            "command": "OpenConsole.exe --headless",
        },
        {
            "pid": 12,
            "ppid": 10,
            "name": "wsl.exe",
            "command": 'wsl.exe --cd "E:\\hermes-projects" -e bash -lc "tmux attach -t hermes-main"',
        },
        {
            "pid": 13,
            "ppid": 12,
            "name": "wslhost.exe",
            "command": " --distro-id abc",
        },
    ]

    targets = extract_windows_terminal_targets(processes)

    assert len(targets) == 1
    assert targets[0]["pid"] == 12
    assert targets[0]["tmux_session"] == "hermes-main"
    assert targets[0]["cwd"] == "E:\\hermes-projects"
