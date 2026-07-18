.PHONY: help venv install test lint build-wheel build-binary smoke clean

PY ?= python3
VENV ?= .venv

help:
	@printf "%s\n" "Targets:" \
	  "  venv          Create virtualenv (${VENV})" \
	  "  install       Install CLI in editable mode" \
	  "  test          Run pytest" \
	  "  lint          Run ruff (if installed)" \
	  "  build-wheel    Build wheel/sdist into dist/" \
	  "  build-binary   Build standalone binary into dist/ (PyInstaller)" \
	  "  smoke         Run basic CLI smoke check" \
	  "  clean         Remove build artifacts"

venv:
	@$(PY) -m venv "$(VENV)"
	@"$(VENV)/bin/pip" install -U pip

install: venv
	@"$(VENV)/bin/pip" install -e .

test: install
	@"$(VENV)/bin/pip" install -e ".[test]"
	@"$(VENV)/bin/pytest" -q

lint: install
	@"$(VENV)/bin/pip" install -U ruff
	@"$(VENV)/bin/ruff" check tillio_cli

build-wheel: install
	@"$(VENV)/bin/pip" install -U build
	@"$(VENV)/bin/python" -m build

build-binary: install
	@"$(VENV)/bin/pip" install -U pyinstaller
	@"$(VENV)/bin/pyinstaller" --onefile --name tillio tillio_cli/main.py
	@printf "%s\n" "Built: dist/tillio"

smoke: build-binary
	@./dist/tillio --help >/dev/null
	@printf "%s\n" "Smoke OK: ./dist/tillio --help"

clean:
	@rm -rf build dist *.spec "$(VENV)"
