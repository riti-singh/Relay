.PHONY: install run test lint typecheck eval check

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

check: lint typecheck test
