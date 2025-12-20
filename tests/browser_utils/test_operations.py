from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightAsyncError

from browser_utils.operations import (
    _get_final_response_content,
    _get_injected_models,
    _handle_model_list_response,
    _parse_userscript_models,
    _wait_for_response_completion,
    detect_and_extract_page_error,
    get_raw_text_content,
    get_response_via_copy_button,
    get_response_via_edit_button,
)


@pytest.fixture(autouse=True)
def mock_async_sleep():
    """Mock asyncio.sleep in interactions module to skip real delays (0.3-0.5s waits)."""
    with patch(
        "browser_utils.operations_modules.interactions.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


def make_mock_page():
    """Create a properly configured mock page with sync/async methods.

    page.locator() is SYNC (returns immediately).
    locator methods like .hover(), .click() are ASYNC.
    locator chaining like .get_by_label(), .locator() are SYNC.

    Uses return_value pattern to allow test overrides like:
    mock_page.locator.return_value.last = custom_locator
    """
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.evaluate = AsyncMock()

    # Create a default locator with proper async/sync method setup
    default_locator = MagicMock()
    # Async action methods
    default_locator.hover = AsyncMock()
    default_locator.click = AsyncMock()
    default_locator.fill = AsyncMock()
    default_locator.wait_for = AsyncMock()
    default_locator.inner_text = AsyncMock()
    default_locator.text_content = AsyncMock()
    default_locator.get_attribute = AsyncMock()
    default_locator.input_value = AsyncMock()
    default_locator.is_visible = AsyncMock()
    default_locator.is_disabled = AsyncMock()
    default_locator.count = AsyncMock(return_value=1)
    # Sync chaining methods
    default_locator.get_by_label = MagicMock(return_value=default_locator)
    default_locator.get_by_role = MagicMock(return_value=default_locator)
    default_locator.locator = MagicMock(return_value=default_locator)
    # .first and .last properties return the same locator (can be overridden in tests)
    default_locator.first = default_locator
    default_locator.last = default_locator

    # Use return_value so tests can override with .return_value.last = ...
    page.locator = MagicMock(return_value=default_locator)
    page.get_by_role = MagicMock(return_value=default_locator)
    return page


@pytest.mark.asyncio
async def test_get_raw_text_content_pre_element():
    """Test getting text from pre element."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock()
    pre_element.inner_text = AsyncMock(return_value="pre content")

    result = await get_raw_text_content(element, "old", "req_id")
    assert result == "pre content"


@pytest.mark.asyncio
async def test_get_raw_text_content_fallback():
    """Test fallback to element text when pre not found."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock(side_effect=PlaywrightAsyncError("Not found"))
    element.inner_text = AsyncMock(return_value="element content")

    result = await get_raw_text_content(element, "old", "req_id")
    assert result == "element content"


def test_parse_userscript_models():
    """Test parsing models from userscript."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test-model',
            displayName: 'Test Model',
            description: 'A test model'
        }
    ];
    """
    models = _parse_userscript_models(script)
    assert len(models) == 1
    assert models[0]["name"] == "models/test-model"


def test_parse_userscript_models_empty():
    """Test parsing empty or invalid userscript."""
    script = "const SCRIPT_VERSION = 'v1.0';"
    models = _parse_userscript_models(script)
    assert models == []


@patch("os.environ.get")
@patch("os.path.exists")
@patch("builtins.open")
def test_get_injected_models(
    mock_open: MagicMock, mock_exists: MagicMock, mock_env: MagicMock
):
    """Test getting injected models."""
    mock_env.return_value = "true"
    mock_exists.return_value = True

    script_content = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test-model',
            displayName: 'Test Model',
            description: 'A test model'
        }
    ];
    """
    mock_open.return_value.__enter__.return_value.read.return_value = script_content

    models = _get_injected_models()
    assert len(models) == 1
    assert models[0]["id"] == "test-model"
    assert models[0]["injected"] is True


@pytest.mark.asyncio
async def test_handle_model_list_response_success():
    """Test handling successful model list response."""
    response = MagicMock()
    response.url = "https://ai.google.dev/api/models"
    response.ok = True
    response.json = AsyncMock(
        return_value={
            "models": [
                {
                    "name": "models/gemini-pro",
                    "displayName": "Gemini Pro",
                    "description": "Best model",
                }
            ]
        }
    )

    mock_server = MagicMock()
    mock_server.parsed_model_list = []
    mock_server.global_model_list_raw_json = None
    mock_server.model_list_fetch_event = None

    with patch.dict("sys.modules", {"server": mock_server}):
        await _handle_model_list_response(response)


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_found(mock_page: MagicMock):
    """Test detecting page error."""
    error_locator = MagicMock()
    message_locator = MagicMock()

    mock_page.locator.return_value.last = error_locator
    error_locator.locator.return_value = message_locator

    error_locator.wait_for = AsyncMock()
    message_locator.text_content = AsyncMock(return_value="Error message")

    result = await detect_and_extract_page_error(mock_page, "req_id")
    assert result == "Error message"


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_not_found(mock_page: MagicMock):
    """Test detecting page error when none exists."""
    error_locator = MagicMock()
    mock_page.locator.return_value.last = error_locator
    error_locator.wait_for = AsyncMock(side_effect=PlaywrightAsyncError("Timeout"))

    result = await detect_and_extract_page_error(mock_page, "req_id")
    assert result is None


@pytest.mark.asyncio
async def test_get_response_via_edit_button_success(mock_page: MagicMock):
    """Test getting response via edit button."""
    check_disconnect = MagicMock()

    # Setup locator chain
    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(return_value=edit_btn)
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Add count() for defensive checks

    # Setup async actions
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(return_value="Response content")

    # Mock playwright expect
    with patch("playwright.async_api.expect", new_callable=MagicMock) as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result == "Response content"


@pytest.mark.asyncio
async def test_get_response_via_copy_button_success(mock_page: MagicMock):
    """Test getting response via copy button."""
    check_disconnect = MagicMock()

    # Setup locators
    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg

    more_opts = MagicMock()
    last_msg.get_by_label.return_value = more_opts

    copy_btn = MagicMock()
    mock_page.get_by_role.return_value = copy_btn

    # Setup actions
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value="Copied content")

    with patch("playwright.async_api.expect", new_callable=MagicMock) as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Copied content"


@pytest.mark.asyncio
async def test_wait_for_response_completion_success(mock_page: MagicMock):
    """Test waiting for response completion."""
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    # Setup states
    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=True)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=1000,
        initial_wait_ms=0,
    )
    assert result is True


@pytest.mark.asyncio
async def test_get_final_response_content_edit_success():
    """Test getting final content via edit button."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    with patch(
        "browser_utils.operations_modules.interactions.get_response_via_edit_button",
        new_callable=AsyncMock,
    ) as mock_edit:
        mock_edit.return_value = "Content"

        result = await _get_final_response_content(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Content"


@pytest.mark.asyncio
async def test_get_final_response_content_fallback_copy():
    """Test fallback to copy button when edit fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    with (
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_edit_button",
            new_callable=AsyncMock,
        ) as mock_edit,
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_copy_button",
            new_callable=AsyncMock,
        ) as mock_copy,
    ):
        mock_edit.return_value = None
        mock_copy.return_value = "Content"

        result = await _get_final_response_content(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Content"


# ==================== New Tests for Improved Coverage ====================


@pytest.mark.asyncio
async def test_get_raw_text_content_pre_error_with_debug():
    """Test pre element inner_text error with debug logging enabled."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock()
    pre_element.inner_text = AsyncMock(
        side_effect=PlaywrightAsyncError("Failed to get inner text")
    )

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await get_raw_text_content(element, "old", "req_id")
        assert result == "old"


@pytest.mark.asyncio
async def test_get_raw_text_content_element_error_with_debug():
    """Test element inner_text error with debug logging enabled."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock(side_effect=PlaywrightAsyncError("Not found"))
    element.inner_text = AsyncMock(
        side_effect=PlaywrightAsyncError("Failed to get text")
    )

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await get_raw_text_content(element, "old", "req_id")
        assert result == "old"


@pytest.mark.asyncio
async def test_get_raw_text_content_element_not_attached_with_debug():
    """Test response element not attached with debug logging."""
    element = MagicMock()
    element.wait_for = AsyncMock(
        side_effect=PlaywrightAsyncError("Element not attached")
    )

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await get_raw_text_content(element, "previous", "req_id")
        assert result == "previous"


@pytest.mark.asyncio
async def test_get_raw_text_content_unexpected_error():
    """Test unexpected error in get_raw_text_content."""
    element = MagicMock()
    element.wait_for = AsyncMock(side_effect=RuntimeError("Unexpected"))

    result = await get_raw_text_content(element, "prev", "req_id")
    assert result == "prev"


@pytest.mark.asyncio
async def test_get_raw_text_content_text_updated_with_debug():
    """Test text update logging when DEBUG_LOGS_ENABLED is True."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock()
    pre_element.inner_text = AsyncMock(return_value="new text content")

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await get_raw_text_content(element, "old text", "req_id")
        assert result == "new text content"


@pytest.mark.asyncio
async def test_get_raw_text_content_cancelled_error():
    """Test CancelledError is properly re-raised."""
    import asyncio

    element = MagicMock()
    element.wait_for = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await get_raw_text_content(element, "old", "req_id")


@pytest.mark.asyncio
async def test_get_response_via_edit_button_hover_failure():
    """Test edit button flow when hover fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    finish_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(
        side_effect=lambda label: edit_btn if label == "Edit" else finish_btn
    )
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)

    # Hover fails but we continue
    last_msg.hover = AsyncMock(side_effect=RuntimeError("Hover failed"))
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(return_value="Response")

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Response"


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_hover():
    """Test CancelledError during hover."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_edit_button_failure():
    """Test when edit button is not visible or click fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.hover = AsyncMock()

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=PlaywrightAsyncError("Not visible")
        )
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_edit_click():
    """Test CancelledError when clicking edit button."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.hover = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(side_effect=asyncio.CancelledError)
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_data_value_error():
    """Test when get_attribute for data-value fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    finish_btn = MagicMock()
    autosize_textarea = MagicMock()
    actual_textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(
        side_effect=lambda label: edit_btn if label == "Edit" else finish_btn
    )

    # Set up locator to return different objects based on selector
    def locator_side_effect(selector):
        if "ms-autosize-textarea" in selector:
            return autosize_textarea
        return actual_textarea

    last_msg.locator = MagicMock(side_effect=locator_side_effect)
    autosize_textarea.count = AsyncMock(return_value=1)
    actual_textarea.count = AsyncMock(return_value=1)
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    # data-value fails, input_value succeeds
    autosize_textarea.get_attribute = AsyncMock(
        side_effect=PlaywrightAsyncError("Attribute error")
    )
    actual_textarea.input_value = AsyncMock(return_value="Input value content")
    finish_btn.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result == "Input value content"


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_data_value():
    """Test CancelledError during get_attribute."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(side_effect=asyncio.CancelledError)

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_input_value_fallback():
    """Test fallback to input_value when data-value is None."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    finish_btn = MagicMock()
    autosize_textarea = MagicMock()
    actual_textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(
        side_effect=lambda label: edit_btn if label == "Edit" else finish_btn
    )

    # Set up locator to return different objects based on selector
    def locator_side_effect(selector):
        if "ms-autosize-textarea" in selector:
            return autosize_textarea
        return actual_textarea

    last_msg.locator = MagicMock(side_effect=locator_side_effect)
    autosize_textarea.count = AsyncMock(return_value=1)
    actual_textarea.count = AsyncMock(return_value=1)
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    # data-value returns None, fallback to input_value
    autosize_textarea.get_attribute = AsyncMock(return_value=None)
    actual_textarea.input_value = AsyncMock(return_value="Fallback content")
    finish_btn.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result == "Fallback content"


@pytest.mark.asyncio
async def test_get_response_via_edit_button_input_value_error():
    """Test when both data-value and input_value fail."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()
    actual_textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = actual_textarea
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    # Both methods fail
    textarea.get_attribute = AsyncMock(return_value=None)
    actual_textarea.input_value = AsyncMock(
        side_effect=PlaywrightAsyncError("Input error")
    )

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_input_value():
    """Test CancelledError during input_value."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    autosize_textarea = MagicMock()
    actual_textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn

    # Set up locator to return different objects based on selector
    def locator_side_effect(selector):
        if "ms-autosize-textarea" in selector:
            return autosize_textarea
        return actual_textarea

    last_msg.locator = MagicMock(side_effect=locator_side_effect)
    autosize_textarea.count = AsyncMock(return_value=1)  # Element exists
    actual_textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    autosize_textarea.get_attribute = AsyncMock(return_value=None)
    actual_textarea.input_value = AsyncMock(side_effect=asyncio.CancelledError)

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_textarea_error():
    """Test when textarea locator fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=PlaywrightAsyncError("Textarea not visible")
        )
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_textarea():
    """Test CancelledError during textarea visibility check."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        # First call succeeds (edit button), second fails (textarea)
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=[None, asyncio.CancelledError]
        )
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_finish_button_failure():
    """Test when finish edit button fails to click."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    finish_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(
        side_effect=lambda label: edit_btn if label == "Edit" else finish_btn
    )
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(return_value="Content")
    finish_btn.click = AsyncMock(side_effect=PlaywrightAsyncError("Click failed"))

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        # Should still return content even if finish button fails
        assert result == "Content"
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_during_finish():
    """Test CancelledError when clicking finish button."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    finish_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(
        side_effect=lambda label: edit_btn if label == "Edit" else finish_btn
    )
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea
    textarea.count = AsyncMock(return_value=1)  # Element exists
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(return_value="Content")

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        # Multiple calls: edit visible, textarea visible, finish visible (cancelled)
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=[None, None, asyncio.CancelledError]
        )
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_skip_finish_on_textarea_failure():
    """Test that finish button is skipped when textarea reading fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = edit_btn
    last_msg.locator.return_value = textarea
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        # Edit button visible, textarea not visible
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=[
                None,
                PlaywrightAsyncError("Textarea not visible"),
            ]
        )
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        # Should return None and skip finish button
        assert result is None


@pytest.mark.asyncio
async def test_get_response_via_edit_button_client_disconnected():
    """Test ClientDisconnectedError is re-raised."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    check_disconnect = MagicMock(side_effect=ClientDisconnectedError("Disconnected"))

    with pytest.raises(ClientDisconnectedError):
        await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_cancelled_top_level():
    """Test top-level CancelledError handling."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await get_response_via_edit_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_edit_button_unexpected_error():
    """Test unexpected exception handling."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock(side_effect=RuntimeError("Unexpected error"))

    with patch(
        "browser_utils.operations_modules.interactions.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_copy_button_more_options_failure():
    """Test when more options button fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    last_msg.hover = AsyncMock()

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=PlaywrightAsyncError("Not visible")
        )
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_copy_button_cancelled_during_more_options():
    """Test CancelledError when clicking more options."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock(side_effect=asyncio.CancelledError)
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_copy_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_copy_button_copy_button_failure():
    """Test when copy markdown button fails."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        # More options visible, copy button not visible
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=[None, PlaywrightAsyncError("Copy button not visible")]
        )
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_copy_button_cancelled_during_copy_click():
    """Test CancelledError when clicking copy button."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        # More options visible, then cancelled on copy button
        mock_expect_obj.to_be_visible = AsyncMock(
            side_effect=[None, asyncio.CancelledError]
        )
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_copy_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_copy_button_copy_not_successful():
    """Test when copy_success flag is False."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        copy_btn.click = AsyncMock(side_effect=PlaywrightAsyncError("Silent failure"))

        with patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ):
            result = await get_response_via_copy_button(
                mock_page, "req_id", check_disconnect
            )
            assert result is None


@pytest.mark.asyncio
async def test_get_response_via_copy_button_clipboard_empty():
    """Test when clipboard content is empty."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value="")  # Empty clipboard

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None


@pytest.mark.asyncio
async def test_get_response_via_copy_button_clipboard_read_error():
    """Test clipboard read failure."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(
        side_effect=PlaywrightAsyncError("clipboard-read permission denied")
    )

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_copy_button_clipboard_read_other_error():
    """Test clipboard read with non-permission error."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(side_effect=PlaywrightAsyncError("Network error"))

    with (
        patch("playwright.async_api.expect") as mock_expect,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_get_response_via_copy_button_cancelled_during_clipboard():
    """Test CancelledError during clipboard read."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    more_opts = MagicMock()
    copy_btn = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label.return_value = more_opts
    mock_page.get_by_role.return_value = copy_btn
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(side_effect=asyncio.CancelledError)

    with patch("playwright.async_api.expect") as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        with pytest.raises(asyncio.CancelledError):
            await get_response_via_copy_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_copy_button_client_disconnected():
    """Test ClientDisconnectedError is re-raised."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    check_disconnect = MagicMock(side_effect=ClientDisconnectedError("Disconnected"))

    with pytest.raises(ClientDisconnectedError):
        await get_response_via_copy_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_copy_button_cancelled_top_level():
    """Test top-level CancelledError handling."""
    import asyncio

    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await get_response_via_copy_button(mock_page, "req_id", check_disconnect)


@pytest.mark.asyncio
async def test_get_response_via_copy_button_unexpected_error():
    """Test unexpected exception handling."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg
    last_msg.hover = AsyncMock(side_effect=RuntimeError("Unexpected"))

    with patch(
        "browser_utils.operations_modules.interactions.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_response_completion_client_disconnect_early():
    """Test client disconnect at loop start."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock(side_effect=ClientDisconnectedError("Disconnected"))

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=1000,
        initial_wait_ms=0,
    )

    assert result is False


@pytest.mark.asyncio
async def test_wait_for_response_completion_timeout():
    """Test timeout before completion."""
    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    # Always return non-completion state
    prompt_area.input_value = AsyncMock(return_value="text")
    submit_btn.is_disabled = AsyncMock(return_value=False)

    with patch(
        "browser_utils.operations_modules.interactions.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await _wait_for_response_completion(
            mock_page,
            prompt_area,
            submit_btn,
            edit_btn,
            "req_id",
            check_disconnect,
            timeout_ms=100,
            initial_wait_ms=0,
        )

        assert result is False
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_response_completion_client_disconnect_after_timeout_check():
    """Test client disconnect after timeout check."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()

    call_count = [0]

    def check_with_delay(msg):
        call_count[0] += 1
        if call_count[0] > 1:
            raise ClientDisconnectedError("Disconnected")

    check_disconnect = MagicMock(side_effect=check_with_delay)

    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=5000,
        initial_wait_ms=0,
    )

    assert result is False


@pytest.mark.asyncio
async def test_wait_for_response_completion_submit_button_timeout():
    """Test submit button is_disabled timeout."""
    from playwright.async_api import TimeoutError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    prompt_area.input_value = AsyncMock(return_value="")

    call_count = [0]

    async def submit_timeout(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise TimeoutError("Timeout")
        return True

    submit_btn.is_disabled = submit_timeout
    edit_btn.is_visible = AsyncMock(return_value=True)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=5000,
        initial_wait_ms=0,
    )

    assert result is True


@pytest.mark.asyncio
async def test_wait_for_response_completion_client_disconnect_after_button_check():
    """Test client disconnect after button state check."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()

    call_count = [0]

    def check_with_delay(msg):
        call_count[0] += 1
        if call_count[0] > 2:
            raise ClientDisconnectedError("Disconnected")

    check_disconnect = MagicMock(side_effect=check_with_delay)

    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=5000,
        initial_wait_ms=0,
    )

    assert result is False


@pytest.mark.asyncio
async def test_wait_for_response_completion_debug_logging():
    """Test debug logging for main conditions."""
    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    call_count = [0]

    async def input_value_side_effect():
        call_count[0] += 1
        return ""

    prompt_area.input_value = input_value_side_effect
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=True)

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await _wait_for_response_completion(
            mock_page,
            prompt_area,
            submit_btn,
            edit_btn,
            "req_id",
            check_disconnect,
            timeout_ms=5000,
            initial_wait_ms=0,
        )

        assert result is True


@pytest.mark.asyncio
async def test_wait_for_response_completion_edit_button_timeout():
    """Test edit button is_visible timeout with debug logging."""
    from playwright.async_api import TimeoutError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)

    call_count = [0]

    async def edit_visible_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] < 3:
            raise TimeoutError("Edit button not visible yet")
        return True

    edit_btn.is_visible = edit_visible_side_effect

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await _wait_for_response_completion(
            mock_page,
            prompt_area,
            submit_btn,
            edit_btn,
            "req_id",
            check_disconnect,
            timeout_ms=5000,
            initial_wait_ms=0,
        )

        assert result is True


@pytest.mark.asyncio
async def test_wait_for_response_completion_client_disconnect_after_edit_check():
    """Test client disconnect after edit button check."""
    from models import ClientDisconnectedError

    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()

    call_count = [0]

    def check_with_delay(msg):
        call_count[0] += 1
        if call_count[0] > 3:
            raise ClientDisconnectedError("Disconnected")

    check_disconnect = MagicMock(side_effect=check_with_delay)

    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=False)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=5000,
        initial_wait_ms=0,
    )

    assert result is False


@pytest.mark.asyncio
async def test_wait_for_response_completion_heuristic_completion():
    """Test heuristic completion when conditions met 3+ times."""
    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=False)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        timeout_ms=5000,
        initial_wait_ms=0,
    )

    assert result is True


@pytest.mark.asyncio
async def test_wait_for_response_completion_conditions_not_met_with_debug():
    """Test debug logging when main conditions not met."""
    mock_page = make_mock_page()
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    call_count = [0]

    async def input_value_side_effect():
        call_count[0] += 1
        if call_count[0] < 2:
            return "text"
        return ""

    prompt_area.input_value = input_value_side_effect
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=True)

    with patch("config.DEBUG_LOGS_ENABLED", True):
        result = await _wait_for_response_completion(
            mock_page,
            prompt_area,
            submit_btn,
            edit_btn,
            "req_id",
            check_disconnect,
            timeout_ms=5000,
            initial_wait_ms=0,
        )

        assert result is True


@pytest.mark.asyncio
async def test_get_final_response_content_all_methods_fail():
    """Test when both edit and copy methods fail."""
    mock_page = make_mock_page()
    check_disconnect = MagicMock()

    with (
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_edit_button",
            new_callable=AsyncMock,
        ) as mock_edit,
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_copy_button",
            new_callable=AsyncMock,
        ) as mock_copy,
        patch(
            "browser_utils.operations_modules.interactions.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        mock_edit.return_value = None
        mock_copy.return_value = None

        result = await _get_final_response_content(
            mock_page, "req_id", check_disconnect
        )

        assert result is None
        mock_save.assert_called_once()
