"""
Pytest configuration and fixtures for AIstudioProxyAPI tests
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    test_env = {
        "DEBUG_LOGS_ENABLED": "false",
        "TRACE_LOGS_ENABLED": "false",
        "AUTO_SAVE_AUTH": "false",
        "AUTO_CONFIRM_LOGIN": "true",
        "ENABLE_SCRIPT_INJECTION": "false",
        "SERVER_LOG_LEVEL": "INFO",
        "PORT": "2048",
    }
    
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    
    return test_env


@pytest.fixture
def mock_playwright():
    """Mock Playwright browser instance."""
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
    mock_browser.is_connected.return_value = True
    mock_page.is_closed.return_value = False
    
    return {
        "browser": mock_browser,
        "page": mock_page,
        "context": mock_context,
    }


@pytest.fixture
def sample_api_keys(temp_dir: Path) -> Path:
    """Create a sample API keys file for testing."""
    key_file = temp_dir / "key.txt"
    key_file.write_text("test-key-1\ntest-key-2\n# This is a comment\n\ntest-key-3\n")
    return key_file


@pytest.fixture
def mock_queue():
    """Mock multiprocessing queue."""
    return MagicMock()


@pytest.fixture
def clean_global_state():
    """Clean global state before and after tests."""
    # This fixture would be used to reset global variables
    # Implementation depends on how we refactor the global state
    yield
    # Cleanup after test
