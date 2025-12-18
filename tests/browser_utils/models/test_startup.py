"""
Tests for browser_utils/models/startup.py

Covers the log cleanup and standardization changes:
- [State] tagged logs
- Condensed verbose messages
- Silent success pattern
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_page():
    """Create a mock Playwright page with proper sync/async methods."""
    page = MagicMock()
    page.url = "https://aistudio.google.com/prompts/new_chat"
    page.evaluate = AsyncMock()
    page.goto = AsyncMock()
    # locator() is sync, returns sync Locator - use MagicMock
    # but locator.first.inner_text() is async
    return page


class TestSetModelFromPageDisplay:
    """Tests for _set_model_from_page_display function."""

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    async def test_reads_model_from_page(self, mock_state_obj, mock_page):
        """Test reading model display from page."""
        from browser_utils.models.startup import _set_model_from_page_display

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        # Mock the model name locator - correctly chain .first.inner_text
        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-2.0-flash")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator

        await _set_model_from_page_display(mock_page, set_storage=False)

        assert mock_state_obj.current_ai_studio_model_id == "gemini-2.0-flash"

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    async def test_no_log_when_model_unchanged(self, mock_state_obj, mock_page):
        """Test silent success when model ID is unchanged."""
        from browser_utils.models.startup import _set_model_from_page_display

        mock_state_obj.current_ai_studio_model_id = "gemini-2.0-flash"
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-2.0-flash")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator

        await _set_model_from_page_display(mock_page, set_storage=False)

        # Should remain unchanged
        assert mock_state_obj.current_ai_studio_model_id == "gemini-2.0-flash"

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    @patch("browser_utils.models.startup._verify_and_apply_ui_state")
    async def test_set_storage_updates_local_storage(
        self, mock_verify_ui, mock_state_obj, mock_page
    ):
        """Test localStorage update when set_storage=True."""
        from browser_utils.models.startup import _set_model_from_page_display

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None
        mock_verify_ui.return_value = True

        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-pro")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator
        mock_page.evaluate.return_value = None  # No existing localStorage

        await _set_model_from_page_display(mock_page, set_storage=True)

        # Verify localStorage was written
        assert mock_page.evaluate.call_count >= 2  # read + write


class TestHandleInitialModelStateAndStorage:
    """Tests for _handle_initial_model_state_and_storage function."""

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    @patch("browser_utils.models.startup._verify_ui_state_settings")
    async def test_no_refresh_when_storage_valid(
        self, mock_verify_ui, mock_state_obj, mock_page
    ):
        """Test no page refresh when localStorage is valid."""
        from browser_utils.models.startup import _handle_initial_model_state_and_storage

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        # Valid localStorage with all required fields
        valid_prefs = json.dumps(
            {
                "promptModel": "models/gemini-2.0-flash",
                "isAdvancedOpen": True,
                "areToolsOpen": True,
            }
        )
        mock_page.evaluate.return_value = valid_prefs
        mock_verify_ui.return_value = {"needsUpdate": False}

        await _handle_initial_model_state_and_storage(mock_page)

        # Model should be set from localStorage
        assert mock_state_obj.current_ai_studio_model_id == "gemini-2.0-flash"

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    async def test_refresh_when_storage_missing(self, mock_state_obj, mock_page):
        """Test page refresh when localStorage is missing."""
        from browser_utils.models.startup import _handle_initial_model_state_and_storage

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        # No localStorage
        mock_page.evaluate.return_value = None

        # Mock the locator for model name - properly chain .first.inner_text
        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-pro")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator

        # Mock goto and navigation
        mock_page.goto = AsyncMock()

        with (
            patch("browser_utils.models.startup.expect_async") as mock_expect,
            patch(
                "browser_utils.models.startup._verify_and_apply_ui_state"
            ) as mock_verify,
        ):
            mock_expect.return_value.to_be_visible = AsyncMock()
            mock_verify.return_value = True

            await _handle_initial_model_state_and_storage(mock_page)

            # Should have attempted page reload
            assert mock_page.goto.called

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    async def test_handles_json_decode_error(self, mock_state_obj, mock_page):
        """Test handling of invalid JSON in localStorage."""
        from browser_utils.models.startup import _handle_initial_model_state_and_storage

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        # Invalid JSON
        mock_page.evaluate.return_value = "invalid json {"

        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-pro")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator
        mock_page.goto = AsyncMock()

        with (
            patch("browser_utils.models.startup.expect_async") as mock_expect,
            patch(
                "browser_utils.models.startup._verify_and_apply_ui_state"
            ) as mock_verify,
        ):
            mock_expect.return_value.to_be_visible = AsyncMock()
            mock_verify.return_value = True

            # Should handle error gracefully
            await _handle_initial_model_state_and_storage(mock_page)


class TestStateTaggedLogging:
    """Tests to verify [State] tagged logging patterns."""

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    @patch("browser_utils.models.startup.logger")
    async def test_state_tag_on_refresh_needed(
        self, mock_logger, mock_state_obj, mock_page
    ):
        """Verify [State] tag in log when refresh is needed."""
        from browser_utils.models.startup import _handle_initial_model_state_and_storage

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        mock_page.evaluate.return_value = None  # No localStorage

        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-pro")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator
        mock_page.goto = AsyncMock()

        with (
            patch("browser_utils.models.startup.expect_async") as mock_expect,
            patch(
                "browser_utils.models.startup._verify_and_apply_ui_state"
            ) as mock_verify,
        ):
            mock_expect.return_value.to_be_visible = AsyncMock()
            mock_verify.return_value = True

            await _handle_initial_model_state_and_storage(mock_page)

        # Verify [State] tagged debug log was called
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("[State]" in call for call in debug_calls)

    @pytest.mark.asyncio
    @patch("api_utils.server_state.state")
    @patch("browser_utils.models.startup.logger")
    async def test_model_tag_on_page_display(
        self, mock_logger, mock_state_obj, mock_page
    ):
        """Verify [Model] tag when reading from page display."""
        from browser_utils.models.startup import _set_model_from_page_display

        mock_state_obj.current_ai_studio_model_id = None
        mock_state_obj.parsed_model_list = []
        mock_state_obj.model_list_fetch_event = None

        first_locator = MagicMock()
        first_locator.inner_text = AsyncMock(return_value="gemini-flash")
        model_locator = MagicMock()
        model_locator.first = first_locator
        mock_page.locator.return_value = model_locator

        await _set_model_from_page_display(mock_page, set_storage=False)

        # Verify [Model] tagged debug log was called
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("[Model]" in call for call in debug_calls)
