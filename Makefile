.PHONY: ci dev-install lint typecheck test

PYTHON_BIN ?= $(shell if [ -x "$$HOME/.hermes/hermes-agent/venv/bin/python" ]; then echo "$$HOME/.hermes/hermes-agent/venv/bin/python"; elif [ -x .venv/bin/python ]; then echo .venv/bin/python; elif command -v python >/dev/null 2>&1; then command -v python; else command -v python3; fi)

dev-install:
	"$(PYTHON_BIN)" -m pip install -e ".[dev]"

ci:
	PYTHON_BIN="$(PYTHON_BIN)" ./scripts/ci-check.sh

lint:
	PYTHON_BIN="$(PYTHON_BIN)" ./scripts/ci-check.sh lint

typecheck:
	PYTHON_BIN="$(PYTHON_BIN)" ./scripts/ci-check.sh typecheck

test:
	PYTHON_BIN="$(PYTHON_BIN)" ./scripts/ci-check.sh test
