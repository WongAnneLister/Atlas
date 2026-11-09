# Every entry point has a target here (AGENTS.md §4).
# Targets for code that does not exist yet print a notice and exit 0.

UV ?= uv
RUN := $(UV) run

.PHONY: setup up down data data-download data-licenses data-docs data-validate-docs data-orders \
        eval-docs eval-orders \
        ingest eval-retrieval eval-intent eval-e2e sweep serve \
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

data: data-download data-licenses data-docs
	$(MAKE) data-orders

data-download:
	$(RUN) python -m support_agent.data.download

data-licenses:
	$(RUN) python -m support_agent.data.licenses

data-docs:
	$(RUN) python -m support_agent.data.build_docs
	$(RUN) python -m support_agent.data.validate_docs
	$(RUN) python eval/docs_build.py

data-validate-docs:
	$(RUN) python -m support_agent.data.validate_docs

eval-docs:
	$(RUN) python eval/docs_build.py

data-orders:
	$(RUN) python -m support_agent.orders.seed
	$(RUN) python eval/orders_seed.py

eval-orders:
	$(RUN) python eval/orders_seed.py

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
