.PHONY: check lint test type-check install-dev

check: lint test type-check
	@echo "All checks passed!"

lint:
	ruff check jewellery_evaluator/ jewellery_inventory_management/ tests/

test:
	pytest tests/ -v

type-check:
	mypy jewellery_evaluator/utils.py --ignore-missing-imports

install-dev:
	pip install -r requirements-dev.txt
