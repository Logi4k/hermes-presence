# Changelog

## [3.4.0] - 2026-05-09

### Added
- **Zombie detection (F1)**: Auto-clears Discord presence when state file timestamp
  goes stale beyond `idle_timeout * zombie_timeout_multiplier` (default 2x = 20s).
  Prevents stale Discord status when Hermes crashes or exits uncleanly.
- **Profile name display (F2)**: Shows active profile in Discord state line.
  e.g., "Answering -- GPT-5.5 (OpenAI) | clinical"
- **Cost tracking (F3)**: Shows session cost and daily accumulator in Discord state.
  Persists to `~/.hermes/state/daily_cost.json`. Displays "Session: $0.04 | Today: $1.23"
- **Provider logos (F4)**: Dynamic `large_image` based on model provider.
  Maps known providers to Discord asset keys (anthropic_logo, openai_logo, etc.)
- **Zero-session auto-clear (F6)**: Clears Discord if zero TUI sessions detected
  AND no valid state files exist. Faster than waiting for zombie timeout.
- **New config fields**: `display.zombie_timeout_multiplier`, `display.show_profile`,
  `display.show_cost`, `display.provider_logo_mode`, `advanced.cost_tracker_file`

### Fixed
- WSL mirror writes per-session files to Windows (`presence_{session_id}.json`)
- update command works offline (reinstalls monitor script instead of pip install)
- Zombie detection ignores test fixtures older than 24 hours

## [3.3.0] - 2026-05-09

### Added
- **Per-session state files** eliminate multi-session contention:
  - Each TUI/gateway session writes to `presence_{session_id}.json`
  - Windows monitor scans all `presence_*.json` files and picks the newest by timestamp
  - Legacy `presence.json` still supported as backward-compatibility fallback
- **Stale file cleanup**: `_cleanup_stale_state_files()` removes state files older than 1 hour
- **Session ID detection**: reads `HERMES_TUI_ACTIVE_SESSION_FILE` env var for unique session IDs,
  falls back to `HERMES_SESSION_ID`
- **WSL mirror**: per-session files mirrored to Windows as `presence_{session_id}.json`

### Fixed
- TUI sessions no longer overwrite each other's Discord state (last-active-wins)
- Telegram/gateway sessions no longer clobber TUI status in Discord
- Lint: `tui_sessions.py` E501 line too long and import ordering issues resolved
- Monitor `_find_latest_state_file()` separated from cleanup logic to avoid breaking tests

### Changed
- `get_state_file_path()` now accepts optional `session_id` parameter
- `get_mirror_path()` now accepts optional `session_id` parameter
- Windows monitor template updated to scan multiple session files
- Hook bridge and `hook.py` both detect session ID automatically

---

## [3.2.0] - 2026-05-04

### Added
- Display reasoning effort in Discord state and hover text.
- `display.show_reasoning` and `display.privacy_mode` controls.
- `status --json` reasoning metadata and `status --verbose` launcher diagnostics.
- `doctor --fix` for Windows startup issues and stale legacy tasks.
- `cleanup-profiles` for stale Windows profile launchers and monitor scripts.
- `update --restart` to update and restart in one command.
- GitHub release workflow for wheel/sdist builds and tagged PyPI publishing.

### Fixed
- Windows startup monitor now prefers hidden `pythonw.exe`/`wscript` launch.
- Config writer now preserves inline dict keys correctly.

All notable changes to Hermes Presence.

---

## [3.1.2] - 2026-05-03

### Fixed
- Discord presence now republishes when a restarted Hermes session has the same visible idle/model state.
- Windows monitor retries indefinitely when Discord is closed, so startup fallback can recover after Discord launches later.
- Periodic republish keeps Discord IPC pipes fresh after Discord or Hermes restarts.
- Presence copy now uses `Answering` / `Composing reply` instead of `Thinking` / `Generating response`.
- Tool display now labels background process monitoring instead of falling back to `Using process`.
- WSL username helpers no longer create stray `nul` files.

### Added
- Regression coverage for Hermes restart pickup, periodic republish, Windows monitor retry behavior, and improved status copy.

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
- Profile-aware WSL-to-Windows state file mirroring (default, research, custom profiles)
- Single Discord application architecture -- one client ID, one slot, no conflicts
- Two-layer "unknown model" fix: bridge restore + write-time safety net

### Fixed
- `unknown` model displayed in Discord when `post_llm_call` hook runs with fresh writer
- State file mirror now uses profile-specific filenames (`research_presence.json` etc.)

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
