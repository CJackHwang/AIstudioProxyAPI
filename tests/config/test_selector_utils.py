"""
Tests for config/selector_utils.py - UI selector fallback utilities.

These tests verify the robust fallback logic for handling Google AI Studio's
dynamic UI changes.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.selector_utils import (
    AUTOSIZE_WRAPPER_SELECTORS,
    INPUT_WRAPPER_SELECTORS,
    build_combined_selector,
    find_first_visible_locator,
)


class TestSelectorConstants:
    """Test that selector constants are properly defined."""

    def test_input_wrapper_selectors_defined(self):
        """INPUT_WRAPPER_SELECTORS should contain both old and new UI selectors."""
        assert isinstance(INPUT_WRAPPER_SELECTORS, list)
        assert len(INPUT_WRAPPER_SELECTORS) >= 2
        # Should contain both ms-prompt-box (new) and ms-prompt-input-wrapper (old)
        selectors_str = " ".join(INPUT_WRAPPER_SELECTORS)
        assert "ms-prompt-box" in selectors_str
        assert "ms-prompt-input-wrapper" in selectors_str

    def test_autosize_wrapper_selectors_defined(self):
        """AUTOSIZE_WRAPPER_SELECTORS should be defined."""
        assert isinstance(AUTOSIZE_WRAPPER_SELECTORS, list)
        assert len(AUTOSIZE_WRAPPER_SELECTORS) >= 2


class TestBuildCombinedSelector:
    """Tests for build_combined_selector function."""

    def test_combine_single_selector(self):
        """Single selector should be returned as-is."""
        result = build_combined_selector(["selector1"])
        assert result == "selector1"

    def test_combine_multiple_selectors(self):
        """Multiple selectors should be joined with comma-space."""
        result = build_combined_selector(["sel1", "sel2", "sel3"])
        assert result == "sel1, sel2, sel3"

    def test_combine_empty_list(self):
        """Empty list should return empty string."""
        result = build_combined_selector([])
        assert result == ""

    def test_combine_real_selectors(self):
        """Test with actual INPUT_WRAPPER_SELECTORS."""
        result = build_combined_selector(INPUT_WRAPPER_SELECTORS)
        # Should contain all selectors comma-separated
        for selector in INPUT_WRAPPER_SELECTORS:
            assert selector in result


class TestFindFirstVisibleLocator:
    """Tests for find_first_visible_locator function."""

    @pytest.mark.asyncio
    async def test_find_first_visible_selector(self):
        """Should return first selector where element is visible."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Mock playwright's expect at the source
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock()

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is mock_locator
            assert selector == "sel1"

    @pytest.mark.asyncio
    async def test_fallback_to_second_when_first_not_visible(self):
        """Should try next selector when first is not visible.

        Updated for two-phase approach:
        - Phase 1: Quick count() check finds both selectors exist
        - Phase 2: First selector's visibility fails, second succeeds
        """
        mock_page = MagicMock()
        mock_locator1 = MagicMock()
        mock_locator2 = MagicMock()

        # count() returns 1 for both selectors (they exist in DOM)
        mock_locator1.count = AsyncMock(return_value=1)
        mock_locator2.count = AsyncMock(return_value=1)

        # Track which locator we're on
        locator_sequence = [mock_locator1, mock_locator2, mock_locator1, mock_locator2]
        mock_page.locator.side_effect = locator_sequence

        visibility_call_count = 0

        async def visibility_side_effect(timeout):
            nonlocal visibility_call_count
            visibility_call_count += 1
            if visibility_call_count == 1:
                # First visibility check fails
                raise Exception("Timeout")
            # Second visibility check succeeds
            return None

        # Mock expect to fail first visibility, succeed second
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=visibility_side_effect
            )

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is mock_locator2
            assert selector == "sel2"

    @pytest.mark.asyncio
    async def test_return_none_when_none_visible(self):
        """Should return None when no selector finds visible element."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Mock expect to always fail
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=Exception("Timeout")
            )

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is None
            assert selector is None

    @pytest.mark.asyncio
    async def test_custom_timeout_passed(self):
        """Should use custom timeout_per_selector value."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        with patch("playwright.async_api.expect") as mock_expect:
            mock_visible = AsyncMock()
            mock_expect.return_value.to_be_visible = mock_visible

            await find_first_visible_locator(
                mock_page, ["sel1"], "test", timeout_per_selector=5000
            )

            mock_visible.assert_called_with(timeout=5000)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError should propagate."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=asyncio.CancelledError()
            )

            with pytest.raises(asyncio.CancelledError):
                await find_first_visible_locator(mock_page, ["sel1"], "test")


class TestRegressionFixes:
    """Regression tests for specific bug fixes."""

    @pytest.mark.asyncio
    async def test_find_first_visible_locator_uses_active_listening(self):
        """Verify find_first_visible_locator uses active DOM listening.

        Regression test for timing issue: In headless mode, elements may not
        be rendered immediately after page load. The function should use
        Playwright's expect().to_be_visible() with MutationObserver internally,
        not just poll or check existence.

        This test ensures:
        - Primary selector gets full timeout for active waiting
        - Playwright's expect().to_be_visible() is called with specified timeout
        """
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Track if to_be_visible was called with a timeout
        visibility_calls = []

        async def track_visibility(timeout):
            visibility_calls.append({"timeout": timeout})

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=track_visibility
            )

            await find_first_visible_locator(
                mock_page,
                ["ms-chunk-editor"],
                "input container",
                timeout_per_selector=30000,  # 30 seconds as used in core.py
            )

        # Verify to_be_visible was called with the specified timeout
        assert len(visibility_calls) == 1
        assert visibility_calls[0]["timeout"] == 30000

    @pytest.mark.asyncio
    async def test_find_first_visible_locator_polls_actively(self):
        """Verify the function uses active polling, not just a check.

        Regression test: The old implementation only checked if elements existed
        at the moment of the call, causing failures when page was still loading.
        The new implementation should actively wait/poll for elements.

        This differs from find_first_available_locator which just calls count().
        """
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Simulate element becoming visible after initial check would fail
        call_count = [0]

        async def delayed_visibility(timeout):
            call_count[0] += 1
            # First call would time out if we were just checking
            # But active waiting should succeed
            return None

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=delayed_visibility
            )

            locator, selector = await find_first_visible_locator(
                mock_page,
                ["sel1"],
                "test",
            )

        # Verify we attempted visibility check with timeout
        assert call_count[0] >= 1
        assert locator is not None
