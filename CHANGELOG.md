# Changelog

## [3.1.0] - 2026-05-02

### Fixed
- Removed hardcoded user paths from Windows platform launcher -- now auto-discovers Windows username
- Fixed WSL-to-Windows state mirroring to support all profile names, not just 'apollo'
- Fixed version inconsistency -- all files now report v3.1.0
- Added client ID validation (numeric snowflake, 17-20 digits) during install
- Fixed `_find_python()` to dynamically resolve Hermes venv paths instead of hardcoded user
- Fixed assets path in installer to work for pip-installed users via importlib.resources
- Platform `ImportError` during install now warns instead of silently skipping
- Fixed `_write_toml()` inline dict serialization for TOML compliance
- Fixed trailing double-newline in config file output
- Expanded Discord pipe scan from 0-3 to 0-9
- Added SIGHUP signal handler alongside SIGINT/SIGTERM

### Added
- Discord running check after install -- warns if Discord isn't detected
- `--dry-run` flag on install for preview-only mode
- `--profile` support on `uninstall` to match install
- Profile support on Linux/macOS launchers (systemd templates, launchd labels)
- `verify_config()` function for config health checking
- `--profile` flag on status command for profile-specific checks
- `validate` subcommand for installation health checks
- `help` and `version` subcommands
- GitHub Actions CI: lint + type-check + conditional tests

### Changed
- `__pycache__` added to `.gitignore` and purged from repo
- README PyPI badge updated to 'coming soon'
- Dev extras documented in README

## [3.0.0] - 2026-04-28

### Added
- Multi-pipe Discord Rich Presence support
- WSL-to-Windows state file mirroring via hook.py
- Multi-profile support (main, apollo, clinical)
- Sub-agent count tracking for party size display
- Kanban phase display
- Tool icon mapping for small_image assets
- Session summary on session end

## [2.0.0] - 2026-04-14

### Added
- Platform-specific launchers: Windows (Task Scheduler), Linux (systemd), macOS (launchd)
- One-command installer with Discord app setup walkthrough
- CLI interface (app.py)
- Config system (config.py)
- Presence state writer (writer.py)

## [1.0.0] - 2026-04-01

### Added
- Initial release
- Discord Rich Presence integration via pypresence
- Hermes CLI hook system integration
- Basic state tracking (idle, working, thinking, error, offline)
