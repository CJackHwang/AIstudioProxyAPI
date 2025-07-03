.PHONY: help install install-dev update clean lint format type-check test test-cov run dev setup pre-commit

# Default target
help:
	@echo "Available commands:"
	@echo "  install      - Install production dependencies"
	@echo "  install-dev  - Install development dependencies"
	@echo "  update       - Update dependencies"
	@echo "  clean        - Clean cache and temporary files"
	@echo "  lint         - Run linting (flake8)"
	@echo "  format       - Format code (black + isort)"
	@echo "  type-check   - Run type checking (mypy)"
	@echo "  test         - Run tests"
	@echo "  test-cov     - Run tests with coverage"
	@echo "  run          - Run the server"
	@echo "  dev          - Run in development mode"
	@echo "  setup        - Initial project setup"
	@echo "  pre-commit   - Install pre-commit hooks"

# Installation
install:
	poetry install --only main

install-dev:
	poetry install --with dev

update:
	poetry update

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/ .mypy_cache/

# Code quality
lint:
	poetry run flake8 .

format:
	poetry run black .
	poetry run isort .

type-check:
	poetry run mypy .

# Testing
test:
	poetry run pytest

test-cov:
	poetry run pytest --cov=api_utils --cov=browser_utils --cov=config --cov=models --cov=logging_utils --cov=stream --cov-report=html --cov-report=term

# Running
run:
	poetry run python server.py

dev:
	poetry run python launch_camoufox.py --debug

# Setup
setup: install-dev pre-commit
	@echo "Project setup complete!"

pre-commit:
	poetry run pre-commit install

# Quality check (run all checks)
check: lint type-check test
	@echo "All checks passed!"

# CI pipeline simulation
ci: clean install-dev check test-cov
	@echo "CI pipeline completed successfully!"
