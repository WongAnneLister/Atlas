# Every entry point has a target here (AGENTS.md §4).
# Targets for code that does not exist yet print a notice and exit 0.

UV ?= uv
RUN := $(UV) run

.PHONY: setup up down data ingest eval-retrieval eval-intent eval-e2e sweep serve \
        lint format typecheck test check notes-check notes

define todo
	@echo "$@: not implemented yet (commit $(1))"
endef

setup:
	$(UV) sync --all-extras
	$(RUN) pre-commit install

up:
	docker compose up -d

down:
	docker compose down

data:
	$(call todo,02-04)

ingest:
	$(call todo,06)

eval-retrieval:
	$(call todo,08)

eval-intent:
	$(call todo,09)

eval-e2e:
	$(call todo,13)

sweep:
	$(call todo,13)

serve:
	$(call todo,14)

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

typecheck:
	$(RUN) mypy

test:
	$(RUN) pytest

notes-check:
	$(RUN) python scripts/check_notes.py

notes:
	$(RUN) python scripts/check_notes.py --build

check: lint typecheck test notes-check
