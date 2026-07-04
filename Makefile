.PHONY: all test verify lint integration

PY ?= python

all:
	$(PY) -m spis.run --stage all

integration:
	$(PY) -m spis.run --stage all
	$(PY) -m pytest tests -q -m integration
	$(PY) scripts/run_all_verifiers.py

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

verify:
	$(PY) scripts/run_all_verifiers.py
