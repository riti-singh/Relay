.PHONY: install run test lint typecheck eval adapter-eval check frontend-install frontend-run frontend-test frontend-build

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

run:
	.venv/bin/uvicorn relay.main:app --reload

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

typecheck:
	.venv/bin/mypy src

eval:
	.venv/bin/python -m relay.eval --output evaluation-results.json

adapter-eval:
	.venv/bin/python -m relay.adapter_eval --output adapter-evaluation-results.json

check: lint typecheck test

frontend-install:
	cd frontend && pnpm install

frontend-run:
	cd frontend && pnpm dev

frontend-test:
	cd frontend && pnpm test

frontend-build:
	cd frontend && pnpm build
