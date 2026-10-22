.PHONY: help install test lint demo benchmark audit examples verify clean

PYTHON ?= python3

help:
	@echo "Modus Light — Sovereign Enterprise Agent Runtime (Community Edition)"
	@echo "Available commands:"
	@echo "  make install    - Install package in editable development mode"
	@echo "  make test       - Run the unit test suite across all 5 core engines"
	@echo "  make lint       - Run flake8 over src, tests and examples"
	@echo "  make demo       - Run the interactive 6-step customer test drive"
	@echo "  make benchmark  - Run the 10-vector capability benchmark suite"
	@echo "  make audit      - Run the compliance smoke audit"
	@echo "  make examples   - Run all 5 end-to-end example scripts"
	@echo "  make verify     - Run lint, tests, benchmark, audit and examples"
	@echo "  make clean      - Remove build and bytecode cache artifacts"

install:
	$(PYTHON) -m pip install -e .

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m flake8 src tests examples

demo:
	PYTHONPATH=src $(PYTHON) -m modus_light.cli demo

benchmark:
	PYTHONPATH=src $(PYTHON) -m modus_light.cli benchmark

audit:
	PYTHONPATH=src $(PYTHON) -m modus_light.cli audit

examples:
	$(PYTHON) examples/01_quickstart.py
	$(PYTHON) examples/02_finops_killswitch.py
	$(PYTHON) examples/03_zanzibar_rebac.py
	$(PYTHON) examples/04_actor_supervision.py
	$(PYTHON) examples/05_customer_test_drive.py

verify: lint test benchmark audit examples
	@echo "All verification gates passed."

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
