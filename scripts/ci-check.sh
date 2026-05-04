#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
  elif [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  elif [[ -x "${HOME}/.hermes/hermes-agent/venv/bin/python" ]]; then
    PYTHON_BIN="${HOME}/.hermes/hermes-agent/venv/bin/python"
  elif command -v python > /dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    PYTHON_BIN="python3"
  fi
fi

run_module() {
  local module="$1"
  shift

  if ! "$PYTHON_BIN" -m "$module" --version > /dev/null 2>&1; then
    echo "Missing Python module: $module" >&2
    echo "Install dev tools with: $PYTHON_BIN -m pip install -e '.[dev]'" >&2
    exit 127
  fi

  "$PYTHON_BIN" -m "$module" "$@"
}

run_lint() {
  echo "==> lint: ruff check hermes_presence/ --select I,F,E,W"
  run_module ruff check hermes_presence/ --select I,F,E,W
}

run_typecheck() {
  echo "==> typecheck: mypy hermes_presence/ --ignore-missing-imports"
  run_module mypy hermes_presence/ --ignore-missing-imports
}

run_tests() {
  echo "==> test: pytest tests/ -v"
  if [[ -d tests ]] && compgen -G "tests/test_*.py" > /dev/null; then
    run_module pytest tests/ -v
  else
    echo "No tests found"
  fi
}

usage() {
  cat <<'EOF'
Usage: scripts/ci-check.sh [all|lint|typecheck|test]

Runs the same gates as .github/workflows/ci.yml:
  lint       ruff check hermes_presence/ --select I,F,E,W
  typecheck  mypy hermes_presence/ --ignore-missing-imports
  test       pytest tests/ -v, with a no-tests fallback only when no tests exist
EOF
}

case "${1:-all}" in
  all)
    run_lint
    run_typecheck
    run_tests
    ;;
  lint)
    run_lint
    ;;
  typecheck)
    run_typecheck
    ;;
  test)
    run_tests
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
