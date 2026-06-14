.PHONY: gate smoke fmt lint test

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
