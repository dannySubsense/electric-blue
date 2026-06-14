.PHONY: gate smoke fmt lint test dev

gate:
	black --check .
	ruff check .
	pytest -m "not smoke"

fmt:
	black .

lint:
	ruff check .

test:
	pytest -m "not smoke"

smoke:
	pytest -m smoke

dev:
	pip install -e ".[local,dev]"
	pre-commit install
