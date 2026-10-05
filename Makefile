# Thin wrapper over scripts/tasks.py so `make setup/test/lint/gate/nightly`
# work identically on Linux CI and Windows Git Bash (where make is often absent:
# use `python scripts/tasks.py <task>` there).
PYTHON ?= python

.PHONY: setup test lint gate nightly clean format

setup:
	$(PYTHON) scripts/tasks.py setup

test:
	$(PYTHON) scripts/tasks.py test

lint:
	$(PYTHON) scripts/tasks.py lint

gate:
	$(PYTHON) scripts/tasks.py gate

nightly:
	$(PYTHON) scripts/tasks.py nightly

format:
	.venv/Scripts/python -m ruff format framework clients sut tests scripts 2>/dev/null || \
	.venv/bin/python -m ruff format framework clients sut tests scripts

clean:
	$(PYTHON) scripts/tasks.py clean
