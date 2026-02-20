.PHONY: build publish clean install dev

VERSION := $(shell python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
TOKEN := $(shell python3 -c "import configparser; c=configparser.ConfigParser(); c.read('$(HOME)/.pypirc'); print(c['pypi']['password'])")

build: clean
	uv build

publish: build
	uv publish --token "$(TOKEN)"
	@echo "\n✓ Published paste-cli v$(VERSION) to PyPI"
	@echo "  pip install paste-cli"

install: build
	uv tool uninstall paste-cli 2>/dev/null || true
	uv tool install dist/paste_cli-$(VERSION)-py3-none-any.whl
	pst stop 2>/dev/null || true
	pst start
	@echo "\n✓ Installed paste-cli v$(VERSION) locally"

dev:
	uv sync
	uv run pst stop 2>/dev/null || true
	uv run pst start
	@echo "\n✓ Dev daemon running"

clean:
	rm -rf dist/
