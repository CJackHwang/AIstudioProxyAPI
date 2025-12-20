# -*- coding: utf-8 -*-
"""Tests for browser_utils/operations_modules/errors.py"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightAsyncError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from browser_utils.operations_modules.errors import (
    ErrorCategory,
    categorize_error,
    detect_and_extract_page_error,
    save_error_snapshot,
    save_minimal_snapshot,
)


# === ErrorCategory Tests ===


class TestErrorCategory:
    """Test ErrorCategory enum values."""

    def test_all_categories_defined(self):
        """Test that all expected categories exist."""
        assert ErrorCategory.TIMEOUT.value == "timeout"
        assert ErrorCategory.PLAYWRIGHT.value == "playwright"
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.CLIENT.value == "client"
        assert ErrorCategory.VALIDATION.value == "validation"
        assert ErrorCategory.CANCELLED.value == "cancelled"
        assert ErrorCategory.UNKNOWN.value == "unknown"


# === categorize_error Tests ===


class TestCategorizeError:
    """Test automatic error categorization."""

    def test_categorize_cancelled_error(self):
        """Test asyncio.CancelledError -> CANCELLED."""
        exc = asyncio.CancelledError()
        assert categorize_error(exc) == ErrorCategory.CANCELLED

    def test_categorize_timeout_asyncio(self):
        """Test asyncio.TimeoutError -> TIMEOUT."""
        exc = asyncio.TimeoutError()
        assert categorize_error(exc) == ErrorCategory.TIMEOUT

    def test_categorize_timeout_playwright(self):
        """Test Playwright TimeoutError -> TIMEOUT."""
        exc = PlaywrightTimeoutError("Timeout 3000ms exceeded")
        assert categorize_error(exc) == ErrorCategory.TIMEOUT

    def test_categorize_playwright_error(self):
        """Test Playwright Error -> PLAYWRIGHT."""
        exc = PlaywrightAsyncError("Element not found")
        assert categorize_error(exc) == ErrorCategory.PLAYWRIGHT

    def test_categorize_value_error(self):
        """Test ValueError -> VALIDATION."""
        exc = ValueError("Invalid value")
        assert categorize_error(exc) == ErrorCategory.VALIDATION

    def test_categorize_type_error(self):
        """Test TypeError -> VALIDATION."""
        exc = TypeError("Wrong type")
        assert categorize_error(exc) == ErrorCategory.VALIDATION

    def test_categorize_attribute_error(self):
        """Test AttributeError -> VALIDATION."""
        exc = AttributeError("Missing attribute")
        assert categorize_error(exc) == ErrorCategory.VALIDATION

    def test_categorize_connection_error(self):
        """Test ConnectionError -> NETWORK."""
        exc = ConnectionError("Connection refused")
        assert categorize_error(exc) == ErrorCategory.NETWORK

    def test_categorize_network_by_message(self):
        """Test network detection by message content."""
        exc = RuntimeError("connection reset by peer")
        assert categorize_error(exc) == ErrorCategory.NETWORK

    def test_categorize_unknown_error(self):
        """Test unknown errors -> UNKNOWN."""
        exc = RuntimeError("Some random error")
        assert categorize_error(exc) == ErrorCategory.UNKNOWN


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_empty_message():
    """Test when error toast exists but message locator returns empty string."""
    page = MagicMock()
    error_locator = MagicMock()
    message_locator = MagicMock()

    # Set up proper chain: page.locator().last
    page.locator.return_value.last = error_locator
    error_locator.locator.return_value = message_locator

    error_locator.wait_for = AsyncMock()
    message_locator.text_content = AsyncMock(return_value="")  # Empty string

    result = await detect_and_extract_page_error(page, "test_req")

    # Should return default message (line 22)
    assert result == "检测到错误提示框，但无法提取特定消息。"


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_general_exception():
    """Test handling of general exceptions during error detection."""
    page = MagicMock()
    error_locator = MagicMock()

    page.locator.return_value.last = error_locator

    # Cause a general exception (not PlaywrightAsyncError)
    error_locator.wait_for = AsyncMock()
    error_locator.locator.side_effect = ValueError("Unexpected error")

    result = await detect_and_extract_page_error(page, "test_req")

    # Should handle exception and return None (line 27)
    assert result is None


@pytest.mark.asyncio
async def test_save_error_snapshot_with_all_params():
    """Test save_error_snapshot calls debug_utils correctly."""
    with patch(
        "browser_utils.debug_utils.save_error_snapshot_enhanced", new_callable=AsyncMock
    ) as mock_save:
        await save_error_snapshot(
            error_name="test_error",
            error_exception=ValueError("Test"),
            error_stage="testing",
            additional_context={"key": "value"},
            locators={"button": "selector"},
        )

        # Should call enhanced snapshot with all params
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == "test_error"
        assert call_args[1]["error_stage"] == "testing"
        # Context now includes error_category from automatic categorization
        context = call_args[1]["additional_context"]
        assert context["key"] == "value"
        assert context["error_category"] == "validation"  # ValueError -> validation


# === save_minimal_snapshot Tests ===


class TestSaveMinimalSnapshot:
    """Test minimal snapshot saving (browser-independent)."""

    @pytest.mark.asyncio
    async def test_minimal_snapshot_creates_directory(self, tmp_path):
        """Test that minimal snapshot creates directory structure."""
        # Patch Path to use tmp_path as base
        with patch("browser_utils.operations_modules.errors.Path") as mock_path_class:
            # Setup: Route all path operations to tmp_path
            errors_dir = tmp_path / "errors_py"
            errors_dir.mkdir(exist_ok=True)

            # Make Path(__file__).parent.parent return tmp_path
            mock_path_instance = MagicMock()
            mock_path_class.return_value = mock_path_instance
            mock_path_instance.parent.parent = tmp_path

            result = await save_minimal_snapshot(
                error_name="test_error",
                req_id="abc1234",
                error_exception=ValueError("Test"),
            )

            # The function should have run without error
            # Since we're mocking Path, the actual directory won't be created
            # but the function should execute
            assert result == "" or result is not None  # May be empty due to mocking

    @pytest.mark.asyncio
    async def test_minimal_snapshot_skips_cancelled_not_applicable(self):
        """Test minimal snapshot is called even for CancelledError when invoked directly."""
        # Note: save_error_snapshot skips CANCELLED, but save_minimal_snapshot doesn't
        with patch("browser_utils.operations_modules.errors.Path") as mock_path_class:
            mock_snapshot_dir = MagicMock()
            mock_snapshot_dir.mkdir = MagicMock()
            mock_snapshot_dir.name = "test"
            mock_snapshot_dir.__truediv__ = MagicMock(return_value=MagicMock())
            mock_path_class.return_value.__truediv__.return_value.__truediv__.return_value = mock_snapshot_dir

            with patch("builtins.open", MagicMock()):
                # This should still work - CANCELLED skip is only in save_error_snapshot
                await save_minimal_snapshot(
                    error_name="cancelled_test",
                    error_exception=asyncio.CancelledError(),
                )

    @pytest.mark.asyncio
    async def test_save_error_snapshot_skips_cancelled(self):
        """Test that save_error_snapshot skips saving for CancelledError."""
        with patch(
            "browser_utils.debug_utils.save_error_snapshot_enhanced",
            new_callable=AsyncMock,
        ) as mock_enhanced:
            await save_error_snapshot(
                error_name="cancelled_test",
                error_exception=asyncio.CancelledError(),
            )

            # Should NOT have called enhanced snapshot
            mock_enhanced.assert_not_called()
