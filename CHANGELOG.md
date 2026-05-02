# Changelog

All notable changes to Hermes Presence.

---

## [3.1.1] - 2026-05-02

### Added
- `hermes-presence update` command -- self-update via git pull + pip reinstall + monitor restart
- `hermes-presence restart` command -- restart the monitor without reinstalling
- `hermes-presence status --json` mode for scripting/automation
- Webhook notification support: `[notify]` config section with `url` + `events` filter
- Session uptime and monitor process age shown in `status` output
- CI status badge in README

### Fixed
- Config validation: `config set` now validates value types (int, bool, list) before saving
- Graceful error handling when pypresence is not installed (clear message, not a traceback)
- CI pipeline fully green: ruff lint + format + mypy + pyright + pytest all pass
- 27 mypy type errors resolved across 7 files
- Ruff import sorting (I001) and line length (E501) violations fixed
- `pyproject.toml` now includes `ruff>=0.9.0` in `[dev]` extras

### Changed
- README rewritten with: CI badge, multi-profile architecture diagram, quick-start for new users
- PyPI badge shows actual package status ("published" not "pending")
- `hermes-presence status` now shows session uptime and monitor PID age

---

## [3.1.0] - 2026-04-28

### Added
- Profile-aware WSL-to-Windows state file mirroring (main, clinical, custom profiles)
- Single Discord application architecture -- one client ID, one slot, no conflicts
- Two-layer "unknown model" fix: bridge restore + write-time safety net
- Clinical monitor (apollo profile) disabled to prevent slot conflicts

### Fixed
- `unknown` model displayed in Discord when `post_llm_call` hook runs with fresh writer
- State file mirror now uses profile-specific filenames (`clinical_presence.json` etc.)

---

## [3.0.0] - 2026-04-01

### Added
- Multi-pipe Discord connections (stable + canary) with auto-reconnect
- Tool-specific icons (status_working, status_researching, status_monitoring, etc.)
- Model + provider tracking in presence detail line
- Subagent party size (Discord party_size = subagents + 1)
- Per-tool elapsed timer
- Error state detection with error message display
- Cron / orchestrator detection via environment variables
- Session tracking: ID, start time, duration, cost, files modified, tool calls
- Named profiles with inheritance
- Atomic writes (write-to-temp + rename)
- Cross-platform auto-start: systemd (Linux), launchd (macOS), Task Scheduler (Windows), WSL bridge
- `hermes-presence validate` command
- `hermes-presence disable` / `hermes-presence enable` commands
- Configurable buttons (Hermes GitHub, Nexus Dashboard, custom URLs)
- Configurable idle timeout, poll interval, tool exclusion list

---

## [0.1.0] - 2025-11-15

### Added
- Initial release: basic Discord Rich Presence monitor for Hermes Agent
- Linux systemd auto-start
- `hermes-presence install`, `status`, `config`, `run` commands
