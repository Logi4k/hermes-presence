# Contributing to hermes-presence

## Quick Start

```bash
git clone https://github.com/Logi4k/hermes-presence.git
cd hermes-presence
pip install -e ".[dev]"
```

## Development Setup

1. Fork and clone the repo
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Make changes in a feature branch
4. Run the full local CI mirror: `make ci`
5. Or run focused checks:
   - `make lint`
   - `make typecheck`
   - `make test`
6. Open a PR

## Code Style

- Follow PEP 8
- Type hints on all public functions
- British English in docstrings and user-facing strings
- No em dashes in output
- Version string in `__init__.py` is the canonical version

## Project Structure

```
hermes_presence/
  __init__.py        # Package init + version
  app.py             # CLI entry point
  config.py          # TOML config load/save
  writer.py          # State file writer
  monitor.py         # Discord Rich Presence monitor
  hook.py            # Hermes CLI hook integration
  installer.py       # One-command installer
  tool_icons.py      # Tool-to-icon mapping
  platforms/
    __init__.py      # PlatformLauncher base
    windows.py       # Windows Task Scheduler + WSL
    linux.py         # Linux systemd
    macos.py         # macOS launchd
scripts/
  hermes-hook-bridge.py  # Hook bridge for Hermes
tests/
assets/              # Discord Art Assets (upload to Developer Portal)
```

## CI

GitHub Actions runs on push/PR:
- `ruff` lint with `--select I,F,E,W`
- `mypy` type checking
- `pytest` test suite (when tests exist)

## Release Process

1. Update `__version__` in `hermes_presence/__init__.py`
2. Update CHANGELOG.md
3. Tag: `git tag vX.Y.Z`
4. Push: `git push --tags`
5. PyPI release (when package is published)
