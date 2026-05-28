# Developer shortcuts. Run `make help` to list them.
#
# Every target uses the project venv at ./.venv when it exists, so you don't
# need to activate it first. Override with `make PY=python3 test`.

VENV ?= .venv
PY   ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)

.DEFAULT_GOAL := help

.PHONY: help venv install test coverage lint fmt typecheck check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create ./.venv (if missing)
	@test -d $(VENV) || python3 -m venv $(VENV)

install: venv ## Editable install with dev tools (pytest, ruff, mypy)
	$(VENV)/bin/pip install -e ".[dev]"

test: ## Run the unit tests (no Discord needed)
	$(PY) -m pytest -q

coverage: ## Tests with a branch-coverage report (needs pytest-cov from `make install`)
	$(PY) -m pytest -q --cov --cov-report=term-missing

lint: ## Lint with ruff (no changes made)
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt: ## Auto-fix lint issues and format
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

typecheck: ## Static type-check with mypy
	$(PY) -m mypy dexport

check: lint typecheck test ## Everything CI runs

clean: ## Remove caches and build artifacts
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
