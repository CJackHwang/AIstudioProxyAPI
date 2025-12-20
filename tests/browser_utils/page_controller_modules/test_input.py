import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, mock_open, patch

import pytest
from playwright.async_api import TimeoutError

from browser_utils.page_controller_modules.input import InputController

# Mock constants - patch them in the config module where they're defined
CONSTANTS = {
    "PROMPT_TEXTAREA_SELECTOR": "textarea.prompt",
    "SUBMIT_BUTTON_SELECTOR": "button.submit",
    "RESPONSE_CONTAINER_SELECTOR": "div.response",
}


# Patch constants in the config module (where they're imported from)
@pytest.fixture(autouse=True)
def mock_constants():
    """Patch constants where they are used in the input module."""
    with patch.multiple("browser_utils.page_controller_modules.input", **CONSTANTS):  # type: ignore[call-overload, arg-type]
        yield


@pytest.fixture(autouse=True)
def mock_timeouts():
    """Patch timeouts to be short for testing."""
    with patch("config.timeouts.SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", 100):
        yield


@pytest.fixture(autouse=True)
def mock_async_sleep():
    """Mock asyncio.sleep in the input module to skip real delays (2s waits)."""
    with patch(
        "browser_utils.page_controller_modules.input.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


@pytest.fixture
def mock_page_controller():
    controller = MagicMock()
    controller.page = MagicMock()
    controller.logger = MagicMock()
    controller.req_id = "test-req-id"

    # Setup page methods
    def create_locator_mock(*args, **kwargs):
        """Create a properly configured locator mock with count() and first."""
        loc = MagicMock()
        loc.count = AsyncMock(return_value=1)  # Default: element exists
        loc.first = MagicMock()
        loc.first.count = AsyncMock(return_value=1)
        return loc

    controller.page.locator = MagicMock(side_effect=create_locator_mock)
    controller.page.evaluate = AsyncMock()
    controller.page.keyboard = MagicMock()
    controller.page.keyboard.press = AsyncMock()
    controller._check_disconnect = AsyncMock()
    return controller


@pytest.fixture
def input_controller(mock_page_controller):
    return InputController(
        mock_page_controller.page,
        mock_page_controller.logger,
        mock_page_controller.req_id,
    )


@pytest.fixture
def mock_expect_async():
    with patch("browser_utils.page_controller_modules.input.expect_async") as mock:
        assertion_mock = MagicMock()
        assertion_mock.to_be_visible = AsyncMock()
        assertion_mock.to_be_hidden = AsyncMock()
        assertion_mock.to_be_enabled = AsyncMock()
        mock.return_value = assertion_mock
        yield mock


@pytest.fixture
def mock_save_snapshot():
    with patch(
        "browser_utils.page_controller_modules.input.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_success(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test successful prompt submission."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Locators
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()
    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)  # Element exists
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()
    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)
    submit_btn.click = AsyncMock()

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif (
            "autosize" in selector
            or "text-wrapper" in selector
            or "ms-prompt-box" in selector
            or "ms-prompt-input-wrapper" in selector
        ):
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock upload logic (skip it for this test)
    with (
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ),
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ) as mock_dialog,
    ):
        await input_controller.submit_prompt("Hello World", [], mock_check_disconnect)

        # Verify text filled
        assert prompt_area.evaluate.called
        assert (
            autosize.first.evaluate.called
        )  # Changed: first.evaluate instead of evaluate
        # Verify submit button wait
        assert submit_btn.is_enabled.called
        # Verify click
        assert submit_btn.click.called
        mock_dialog.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_with_files(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit prompt with file upload."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Shared locator mock that handles all locator calls
    shared_locator = MagicMock()
    shared_locator.is_enabled = AsyncMock(return_value=True)
    shared_locator.click = AsyncMock()
    shared_locator.evaluate = AsyncMock()  # For prompt filling
    shared_locator.count = AsyncMock(return_value=1)  # Element exists
    shared_locator.first = MagicMock()
    shared_locator.first.evaluate = AsyncMock()

    # Override the fixture's side_effect with our shared locator
    mock_page_controller.page.locator = MagicMock(return_value=shared_locator)

    with (
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ) as mock_upload,
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        mock_upload.return_value = True

        await input_controller.submit_prompt(
            "With files", ["file1.png"], mock_check_disconnect
        )

        mock_upload.assert_awaited_with(["file1.png"])


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_success_input(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test upload menu via hidden input."""
    trigger_element = MagicMock()
    trigger_element.click = AsyncMock()

    trigger_locator = MagicMock()
    trigger_locator.first = trigger_element
    trigger_locator.count = AsyncMock(return_value=1)

    menu_container = MagicMock()

    upload_btn = MagicMock()  # Element
    upload_btn.is_visible = AsyncMock(return_value=True)

    menu_item = MagicMock()  # Locator
    menu_item.first = upload_btn
    menu_item.count = AsyncMock(return_value=1)

    input_loc = MagicMock()
    input_loc.count = AsyncMock(return_value=1)
    input_loc.set_input_files = AsyncMock()

    upload_btn.locator.return_value = input_loc

    def locator_side_effect(selector):
        if (
            'aria-label="Insert assets' in selector
            or 'data-test-id="add-media-button"' in selector
        ):
            return trigger_locator
        elif "cdk-overlay-container" in selector:
            return menu_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock finding the upload button inside menu container
    menu_container.locator.return_value = menu_item

    result = await input_controller._open_upload_menu_and_choose_file(["file1.png"])

    assert result is True
    assert (
        trigger_element.click.called
    )  # Changed: check element.click not locator.click
    assert input_loc.set_input_files.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_success_file_chooser(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test upload menu via file chooser (fallback)."""
    trigger_element = MagicMock()
    trigger_element.click = AsyncMock()

    trigger_locator = MagicMock()
    trigger_locator.first = trigger_element
    trigger_locator.count = AsyncMock(return_value=1)

    menu_container = MagicMock()

    upload_btn = MagicMock()  # Element
    upload_btn.click = AsyncMock()
    upload_btn.is_visible = AsyncMock(return_value=True)

    upload_btn_list = MagicMock()  # Locator
    upload_btn_list.count = AsyncMock(return_value=1)
    upload_btn_list.first = upload_btn

    input_loc = MagicMock()
    input_loc.count = AsyncMock(return_value=0)  # No hidden input, trigger fallback

    # Locator setup
    upload_btn.locator.return_value = input_loc
    menu_container.locator.return_value = upload_btn_list

    def locator_side_effect(selector):
        if (
            'aria-label="Insert assets' in selector
            or 'data-test-id="add-media-button"' in selector
        ):
            return trigger_locator
        elif "cdk-overlay-container" in selector:
            return menu_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock expect_file_chooser
    file_chooser = MagicMock()
    file_chooser.set_files = AsyncMock()
    fc_info = MagicMock()
    fc_info.value = file_chooser

    # expect_file_chooser context manager
    # We need to ensure __aenter__ returns fc_info
    # And fc_info.value must be awaitable and return file_chooser

    # Create a Future for fc_info.value
    f = asyncio.Future()
    f.set_result(file_chooser)

    fc_info = MagicMock()
    # Mock the value property to return the future
    type(fc_info).value = PropertyMock(return_value=f)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fc_info)
    cm.__aexit__ = AsyncMock(return_value=None)
    mock_page_controller.page.expect_file_chooser.return_value = cm

    result = await input_controller._open_upload_menu_and_choose_file(["file1.png"])

    assert result is True
    assert (
        trigger_element.click.called
    )  # Changed: check element.click not locator.click
    assert upload_btn.click.called
    assert file_chooser.set_files.called


@pytest.mark.skip(reason="Method _simulate_drag_drop_files not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_files(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _simulate_drag_drop_files."""
    target = MagicMock()
    target.evaluate = AsyncMock()

    with (
        patch("builtins.open", mock_open(read_data=b"file_content")),
        patch("os.path.exists", return_value=True),
    ):
        await input_controller._simulate_drag_drop_files(target, ["/tmp/test.png"])

        assert target.evaluate.called
        # Check that evaluate was called with script containing "DataTransfer"
        args = target.evaluate.call_args[0]
        assert "DataTransfer" in args[0]
        assert args[1][0]["name"] == "test.png"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_enter_submit(input_controller, mock_page_controller):
    """Test _try_enter_submit."""
    mock_check_disconnect = MagicMock(return_value=False)
    prompt_area = MagicMock()
    prompt_area.press = AsyncMock()
    prompt_area.focus = AsyncMock()
    prompt_area.input_value = AsyncMock(
        side_effect=["test content", ""]
    )  # Method 1: cleared

    with (
        patch(
            "browser_utils.page_controller_modules.input.expect_async"
        ) as mock_expect,
        patch("os.environ.get", return_value="Windows"),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await input_controller._try_enter_submit(
            prompt_area, mock_check_disconnect
        )

        assert result is True
        # It tries page.keyboard.press("Enter") first
        assert (
            mock_page_controller.page.keyboard.press.called or prompt_area.press.called
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_combo_submit(input_controller, mock_page_controller):
    """Test _try_combo_submit."""
    mock_check_disconnect = MagicMock(return_value=False)
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.input_value = AsyncMock(side_effect=["test", ""])  # Method 1: cleared

    # Mock user agent for non-Mac
    mock_page_controller.page.evaluate.return_value = "Windows"

    with patch("os.environ.get", return_value="Windows"):
        result = await input_controller._try_combo_submit(
            prompt_area, mock_check_disconnect
        )

        assert result is True
        # Check Control+Enter for Windows
        assert mock_page_controller.page.keyboard.press.call_count >= 1
        args = mock_page_controller.page.keyboard.press.call_args[0]
        assert "Control+Enter" in args[0]


@pytest.mark.asyncio
@pytest.mark.skip(reason="Method _ensure_files_attached not implemented")
@pytest.mark.timeout(5)
async def test_ensure_files_attached(input_controller, mock_page_controller):
    """Test _ensure_files_attached."""
    wrapper = MagicMock()
    # Return count > 0 to simulate success
    wrapper.evaluate = AsyncMock(return_value={"inputs": 1, "chips": 0, "blobs": 0})

    result = await input_controller._ensure_files_attached(wrapper, expected_min=1)

    assert result is True
    assert wrapper.evaluate.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_timeout(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit prompt timeout waiting for button enabled."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Locators
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    # is_enabled always returns False or raises
    submit_btn.is_enabled = AsyncMock(return_value=False)

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock config timeout to be very short for test
    with (
        patch("config.timeouts.SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", 100),
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ),
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        with pytest.raises(TimeoutError, match="Submit button not enabled"):
            await input_controller.submit_prompt("test", [], mock_check_disconnect)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_retry_logic(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test retry logic: Button Click Fail -> Enter Submit Success."""
    mock_check_disconnect = MagicMock(return_value=False)

    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)
    # Click raises exception
    submit_btn.click = AsyncMock(side_effect=Exception("Click failed"))

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock _try_enter_submit to succeed
    # Use explicit AsyncMock assignment instead of patch.object new_callable if causing issues
    with (
        patch.object(
            input_controller, "_try_enter_submit", new_callable=AsyncMock
        ) as mock_enter,
        patch.object(
            input_controller, "_try_combo_submit", new_callable=AsyncMock
        ) as mock_combo,
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        mock_enter.return_value = True

        await input_controller.submit_prompt("test", [], mock_check_disconnect)

        assert submit_btn.click.called
        assert mock_enter.called
        assert not mock_combo.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_all_fail(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test retry logic: All fail."""
    mock_check_disconnect = MagicMock(return_value=False)

    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)
    submit_btn.click = AsyncMock(side_effect=Exception("Click failed"))

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    with (
        patch.object(
            input_controller, "_try_enter_submit", new_callable=AsyncMock
        ) as mock_enter,
        patch.object(
            input_controller, "_try_combo_submit", new_callable=AsyncMock
        ) as mock_combo,
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        mock_enter.return_value = False
        mock_combo.return_value = False

        # Relax regex to match whatever exception is raised
        with pytest.raises(Exception) as excinfo:
            await input_controller.submit_prompt("test", [], mock_check_disconnect)

        assert "Submit failed" in str(excinfo.value)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _handle_post_upload_dialog."""
    overlay = MagicMock()
    overlay.count = AsyncMock(return_value=1)

    agree_btn = MagicMock()
    agree_btn.count = AsyncMock(return_value=1)
    agree_btn.first.is_visible = AsyncMock(return_value=True)
    agree_btn.first.click = AsyncMock()

    overlay.locator.return_value = agree_btn

    mock_page_controller.page.locator.side_effect = (
        lambda s: overlay if "cdk-overlay-container" in s else MagicMock()
    )

    await input_controller._handle_post_upload_dialog()

    assert agree_btn.first.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_browser_os_detection(input_controller, mock_page_controller):
    """Test OS detection via userAgent."""
    mock_check_disconnect = MagicMock(return_value=False)
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()

    # Mock OS environ to None to trigger browser detection
    with patch("os.environ.get", return_value=None):
        # Mock userAgentData to fail
        mock_page_controller.page.evaluate.side_effect = [
            Exception("No userAgentData"),  # First call fails
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",  # Second call returns string
        ]

        # We expect Meta+Enter for Mac
        result = await input_controller._try_combo_submit(
            prompt_area, mock_check_disconnect
        )

        assert (
            result is True
        )  # verification defaults to True on error if original content check fails/skipped

        # Verify key press
        assert mock_page_controller.page.keyboard.press.call_count >= 1
        args = mock_page_controller.page.keyboard.press.call_args[0]
        assert "Meta+Enter" in args[0]


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_files_read_error(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _simulate_drag_drop_files with file read error."""
    target = MagicMock()

    with (
        patch("builtins.open", side_effect=OSError("Read error")),
        patch("os.path.exists", return_value=True),
    ):
        # Should raise exception because no files could be read -> payloads empty
        with pytest.raises(Exception, match="无可用文件用于拖放"):
            await input_controller._simulate_drag_drop_files(target, ["/tmp/bad.png"])


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_files_fallback(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _simulate_drag_drop_files fallback to secondary candidates."""
    target = MagicMock()
    # First candidate (target) raises error on visibility check
    mock_expect_async.return_value.to_be_visible.side_effect = [
        Exception("Not visible"),  # Target
        None,  # Second candidate (textarea) - visible
    ]

    # Second candidate
    textarea = MagicMock()
    textarea.evaluate = AsyncMock()

    # Locator side effect for candidates
    def locator_side_effect(selector):
        if "textarea" in selector:
            return textarea
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    with (
        patch("builtins.open", mock_open(read_data=b"data")),
        patch("os.path.exists", return_value=True),
    ):
        await input_controller._simulate_drag_drop_files(target, ["/tmp/test.png"])

        # Target should have been checked
        # Textarea should have been evaluated
        assert textarea.evaluate.called
        assert "DataTransfer" in textarea.evaluate.call_args[0][0]


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_files_body_fallback(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _simulate_drag_drop_files fallback to document.body."""
    target = MagicMock()

    # All candidates fail visibility
    mock_expect_async.return_value.to_be_visible.side_effect = Exception("Not visible")

    with (
        patch("builtins.open", mock_open(read_data=b"data")),
        patch("os.path.exists", return_value=True),
    ):
        await input_controller._simulate_drag_drop_files(target, ["/tmp/test.png"])

        # page.evaluate (body fallback) should be called
        assert mock_page_controller.page.evaluate.called
        args = mock_page_controller.page.evaluate.call_args[0]
        assert "document.body" in args[0]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_retry_logic(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test upload menu retry logic (first click fails)."""
    trigger_element = MagicMock()
    trigger_element.click = AsyncMock()

    trigger_locator = MagicMock()
    trigger_locator.first = trigger_element

    menu_container = MagicMock()

    # Expectation side effects:
    # 1. to_be_visible (first attempt on trigger) -> returns None
    # 2. to_be_visible (first menu check) -> raises Exception
    # 3. to_be_visible (second menu check after retry) -> returns None
    # 4. to_be_visible (upload button) -> returns None
    mock_expect_async.return_value.to_be_visible.side_effect = [
        None,  # trigger visible
        Exception("Menu not visible"),  # first menu check fails
        None,  # second menu check succeeds
        None,  # upload button visible
    ]

    # Mock for menu locator (div[role='menu'])
    menu_locator = MagicMock()
    menu_locator.first = MagicMock()  # The menu element itself

    # Mock for upload button locator
    upload_btn = MagicMock()
    upload_btn.count = AsyncMock(return_value=1)
    upload_btn.first = MagicMock()  # The button element
    upload_btn.first.locator.return_value.count = AsyncMock(return_value=1)  # Has input
    upload_btn.first.locator.return_value.set_input_files = AsyncMock()
    upload_btn.first.is_visible = AsyncMock(return_value=True)

    def menu_container_locator_side_effect(selector):
        if "div[role='menu']" in selector and "button" not in selector:
            return menu_locator
        else:
            return upload_btn

    menu_container.locator.side_effect = menu_container_locator_side_effect

    def locator_side_effect(selector):
        if (
            'aria-label="Insert assets' in selector
            or 'data-test-id="add-media-button"' in selector
        ):
            return trigger_locator
        elif "cdk-overlay-container" in selector:
            return menu_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    result = await input_controller._open_upload_menu_and_choose_file(["file.png"])

    assert result is True
    assert trigger_element.click.call_count == 2


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_ensure_files_attached_timeout(input_controller, mock_page_controller):
    """Test _ensure_files_attached timeout."""
    wrapper = MagicMock()
    # Always return 0 files
    wrapper.evaluate = AsyncMock(return_value={"inputs": 0, "chips": 0, "blobs": 0})

    # Short timeout
    result = await input_controller._ensure_files_attached(
        wrapper, expected_min=1, timeout_ms=100
    )

    assert result is False
    assert wrapper.evaluate.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_click_agree(
    input_controller, mock_page_controller
):
    """Test _handle_post_upload_dialog clicks an agree button."""
    overlay_container = MagicMock()
    overlay_container.count = AsyncMock(return_value=1)

    # Mock finding 'Agree' button
    agree_btn = MagicMock()
    agree_btn.count = AsyncMock(return_value=1)
    agree_btn.first.is_visible = AsyncMock(return_value=True)
    agree_btn.first.click = AsyncMock()

    def locator_side_effect(selector):
        if "cdk-overlay-container" in selector:
            return overlay_container
        # The code iterates through agree_texts and calls overlay_container.locator(...)
        # We assume the first one 'Agree' will match our mock
        if "button:has-text('Agree')" in selector:
            return agree_btn
        return MagicMock()

    overlay_container.locator.side_effect = locator_side_effect
    mock_page_controller.page.locator.side_effect = (
        lambda s: overlay_container if "cdk-overlay-container" in s else MagicMock()
    )

    await input_controller._handle_post_upload_dialog()

    # Verify click
    assert agree_btn.first.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_click_copyright(
    input_controller, mock_page_controller
):
    """Test _handle_post_upload_dialog clicks copyright button when no agree button found."""
    overlay_container = MagicMock()
    overlay_container.count = AsyncMock(return_value=1)

    # No agree buttons found - create a mock that returns count 0 for everything by default
    empty_locator = MagicMock()
    empty_locator.count = AsyncMock(return_value=0)
    overlay_container.locator.return_value = empty_locator

    # Mock finding copyright button
    copyright_btn = MagicMock()
    copyright_btn.count = AsyncMock(return_value=1)
    copyright_btn.first.is_visible = AsyncMock(return_value=True)
    copyright_btn.first.click = AsyncMock()

    def page_locator_side_effect(selector):
        if "cdk-overlay-container" in selector:
            return overlay_container
        if "copyright" in selector:
            return copyright_btn
        return MagicMock()

    mock_page_controller.page.locator.side_effect = page_locator_side_effect

    await input_controller._handle_post_upload_dialog()

    assert copyright_btn.first.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_enter_submit_mac_detection(input_controller, mock_page_controller):
    """Test _try_enter_submit with unknown OS (simplified after refactor)."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.press = AsyncMock()
    prompt_area.input_value = AsyncMock(
        side_effect=["test", ""]
    )  # Cleared after submit

    # After refactoring, OS detection from browser was removed as unused
    # Test now verifies basic enter submit behavior with unknown OS
    with patch("os.environ.get", return_value="Unknown"):
        result = await input_controller._try_enter_submit(prompt_area, lambda x: None)

    # Verify submission succeeded (input cleared)
    assert result is True
    assert prompt_area.focus.called
    assert prompt_area.input_value.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_enter_submit_validation_fallback(
    input_controller, mock_page_controller
):
    """Test _try_enter_submit validation fallback (Method 2 and 3)."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.press = AsyncMock()
    # Method 1 fails: content still same
    prompt_area.input_value = AsyncMock(return_value="test")

    submit_btn = MagicMock()
    # Method 2 fails: button not disabled
    submit_btn.is_disabled = AsyncMock(return_value=False)

    response_container = MagicMock()
    # Method 3 succeeds: new container visible
    response_container.count = AsyncMock(return_value=1)

    # Configure last container
    last_container = MagicMock()
    last_container.is_visible = AsyncMock(return_value=True)
    response_container.last = last_container

    def locator_side_effect(selector):
        if "submit" in selector:
            return submit_btn
        if "div.response" in selector:
            return response_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect
    mock_page_controller.page.keyboard.press = AsyncMock()

    with patch("os.environ.get", return_value="Windows"):
        result = await input_controller._try_enter_submit(prompt_area, lambda x: None)

    assert result is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_combo_submit_fallback_keypress(
    input_controller, mock_page_controller
):
    """Test _try_combo_submit fallback to down/press/up when press fails."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()

    # AsyncMock with side_effect for multiple calls
    # Provide enough values for potential extra calls
    input_value_mock = AsyncMock(side_effect=["test", "", "", ""])
    prompt_area.input_value = input_value_mock

    # Mock press failure for the first call (combo), succeed for second (single key in fallback)
    mock_page_controller.page.keyboard.press.side_effect = [
        Exception("Press failed"),
        None,
    ]
    mock_page_controller.page.keyboard.down = AsyncMock()
    mock_page_controller.page.keyboard.up = AsyncMock()

    with patch("os.environ.get", return_value="Windows"):
        result = await input_controller._try_combo_submit(prompt_area, lambda x: None)

    assert result is True
    assert mock_page_controller.page.keyboard.down.called
    assert mock_page_controller.page.keyboard.up.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_failure(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test _open_upload_menu_and_choose_file failures (not visible, item not found)."""
    trigger = MagicMock()
    trigger.click = AsyncMock()
    menu_container = MagicMock()

    # Case 1: Menu never becomes visible
    mock_expect_async.return_value.to_be_visible.side_effect = Exception("Not visible")

    def locator_side_effect(selector):
        if 'aria-label="Insert assets' in selector:
            return trigger
        elif "cdk-overlay-container" in selector:
            return menu_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    result = await input_controller._open_upload_menu_and_choose_file(["file.png"])
    assert result is False

    # Case 2: Menu visible, but 'Upload File' not found
    mock_expect_async.return_value.to_be_visible.side_effect = None  # Visible now

    # Mock upload button count to 0 (both aria-label and text fallback)
    upload_btn = MagicMock()
    upload_btn.count = AsyncMock(return_value=0)

    menu_container.locator.return_value = upload_btn

    result = await input_controller._open_upload_menu_and_choose_file(["file.png"])
    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_exception(input_controller, mock_page_controller):
    """Test _open_upload_menu_and_choose_file generic exception handling."""
    # Force exception at the start
    mock_page_controller.page.locator.side_effect = Exception("Unexpected error")

    result = await input_controller._open_upload_menu_and_choose_file(["file.png"])
    assert result is False
    assert input_controller.logger.error.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_is_enabled_exception(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit_prompt handling exception during button enabled check."""
    mock_check_disconnect = MagicMock(return_value=False)

    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()
    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    # first call raises exception (ignored), second returns True
    submit_btn.is_enabled = AsyncMock(side_effect=[Exception("Not ready"), True])
    submit_btn.click = AsyncMock()

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    with (
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ),
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        await input_controller.submit_prompt("test", [], mock_check_disconnect)

        assert submit_btn.is_enabled.call_count == 2
        assert submit_btn.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_cancellation(input_controller, mock_page_controller):
    """Test submit_prompt handling CancelledError."""
    # Simulate cancellation during locator lookup
    mock_page_controller.page.locator.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await input_controller.submit_prompt("test", [], lambda x: None)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_exceptions_snapshots(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit_prompt taking snapshots on errors."""
    mock_check_disconnect = MagicMock(return_value=False)

    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()
    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()
    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)

    # Case 1: Click error
    submit_btn.click = AsyncMock(side_effect=Exception("Click fail"))

    def locator_side_effect(selector):
        if selector == CONSTANTS["PROMPT_TEXTAREA_SELECTOR"]:
            return prompt_area
        elif selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # We need _try_enter_submit to fail too to trigger full failure logic
    with (
        patch(
            "browser_utils.page_controller_modules.input.save_error_snapshot",
            new_callable=AsyncMock,
        ) as mock_snapshot,
        patch.object(input_controller, "_try_enter_submit", return_value=False),
        patch.object(input_controller, "_try_combo_submit", return_value=False),
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ),
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        with pytest.raises(Exception):
            await input_controller.submit_prompt("test", [], mock_check_disconnect)

        # Verify snapshots
        # 1. submit_button_click_fail
        # 2. input_submit_error
        assert mock_snapshot.call_count >= 2
        args_list = [args[0] for args, _ in mock_snapshot.call_args_list]
        assert any("submit_button_click_fail" in a for a in args_list)
        assert any("input_submit_error" in a for a in args_list)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_enter_submit_validation_fail(input_controller, mock_page_controller):
    """Test _try_enter_submit returns False when all validations fail."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.press = AsyncMock()
    prompt_area.input_value = AsyncMock(return_value="test")  # Content same

    submit_btn = MagicMock()
    submit_btn.is_disabled = AsyncMock(return_value=False)  # Not disabled

    response_container = MagicMock()
    response_container.count = AsyncMock(return_value=0)  # No response

    def locator_side_effect(selector):
        if "submit" in selector:
            return submit_btn
        if "div.response" in selector:
            return response_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    with patch("os.environ.get", return_value="Windows"):
        result = await input_controller._try_enter_submit(prompt_area, lambda x: None)

    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_enter_submit_press_exception(input_controller, mock_page_controller):
    """Test _try_enter_submit handling exception during key press."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.press = AsyncMock(side_effect=Exception("Element press fail"))
    prompt_area.input_value = AsyncMock(return_value="test")

    mock_page_controller.page.keyboard.press.side_effect = Exception(
        "Global press fail"
    )

    with patch("os.environ.get", return_value="Windows"):
        # Should catch exceptions and proceed to validation (which fails here)
        result = await input_controller._try_enter_submit(prompt_area, lambda x: None)

    assert result is False
    assert mock_page_controller.page.keyboard.press.called
    assert prompt_area.press.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_try_combo_submit_exceptions(input_controller, mock_page_controller):
    """Test _try_combo_submit exception handling."""
    prompt_area = MagicMock()
    prompt_area.focus = AsyncMock()
    prompt_area.input_value = AsyncMock(return_value="test")

    # 1. Inner exception (key press fails)
    mock_page_controller.page.keyboard.press.side_effect = Exception("Press fail")
    mock_page_controller.page.keyboard.down.side_effect = Exception(
        "Down fail"
    )  # Fallback also fails

    with patch("os.environ.get", return_value="Windows"):
        result = await input_controller._try_combo_submit(prompt_area, lambda x: None)
        assert result is False  # Validation fails

    # 2. Outer exception (e.g. focus fails)
    prompt_area.focus.side_effect = Exception("Focus fail")
    result = await input_controller._try_combo_submit(prompt_area, lambda x: None)
    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_fail_after_retry(
    input_controller, mock_page_controller
):
    """Test failure when menu fails to open after retry."""
    trigger_element = MagicMock()
    trigger_element.click = AsyncMock()

    trigger_locator = MagicMock()
    trigger_locator.first = trigger_element

    menu_container = MagicMock()
    menu_locator = MagicMock()
    menu_locator.first = MagicMock()

    def menu_container_locator_side_effect(selector):
        if "div[role='menu']" in selector:
            return menu_locator
        return MagicMock()

    menu_container.locator.side_effect = menu_container_locator_side_effect

    def locator_side_effect(selector):
        if (
            'aria-label="Insert assets' in selector
            or 'data-test-id="add-media-button"' in selector
        ):
            return trigger_locator
        elif "cdk-overlay-container" in selector:
            return menu_container
        return MagicMock()

    matcher = MagicMock()
    # First call (trigger visible) succeeds, all menu checks fail
    matcher.to_be_visible = AsyncMock(
        side_effect=[None, Exception("Not visible"), Exception("Not visible")]
    )

    with patch(
        "browser_utils.page_controller_modules.input.expect_async", return_value=matcher
    ):
        mock_page_controller.page.locator.side_effect = locator_side_effect

        result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])

        assert result is False
        assert trigger_element.click.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_no_upload_button(
    input_controller, mock_page_controller
):
    """Test failure when 'Upload File' button is not found."""
    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.input.expect_async", return_value=matcher
    ):
        upload_btn = MagicMock()
        upload_btn.count = AsyncMock(return_value=0)  # Not found

        menu_container = MagicMock()
        menu_container.locator.return_value = upload_btn

        mock_page_controller.page.locator.side_effect = (
            lambda s: menu_container if "cdk-overlay-container" in s else MagicMock()
        )

        result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])

        assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_exceptions(
    input_controller, mock_page_controller
):
    """Test exception handling in _handle_post_upload_dialog."""
    # Setup overlay container
    overlay = MagicMock()
    overlay.count = AsyncMock(return_value=1)

    # Setup button loop that raises exception then finds nothing
    btn = MagicMock()
    btn.count = AsyncMock(side_effect=Exception("Locator error"))

    overlay.locator.return_value = btn
    mock_page_controller.page.locator.return_value = overlay

    # Should not raise exception
    await input_controller._handle_post_upload_dialog()


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_file_read_error(input_controller):
    """Test _simulate_drag_drop_files handling file read error."""
    # If read fails, it logs warning and skips. If no files left, raises exception.
    with patch("builtins.open", side_effect=Exception("Read failed")):
        with pytest.raises(Exception, match="无可用文件用于拖放"):
            await input_controller._simulate_drag_drop_files(
                MagicMock(), ["bad_file.jpg"]
            )


@pytest.mark.skip(reason="Method not implemented")
@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_fallback_to_body(
    input_controller, mock_page_controller
):
    """Test _simulate_drag_drop_files fallback to document.body."""
    target = MagicMock()

    # All candidates fail visibility check
    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock(side_effect=Exception("Not visible"))

    with (
        patch("builtins.open", mock_open(read_data=b"data")),
        patch(
            "browser_utils.page_controller_modules.input.expect_async",
            return_value=matcher,
        ),
    ):
        # page.evaluate should be called for fallback
        mock_page_controller.page.evaluate = AsyncMock()

        await input_controller._simulate_drag_drop_files(target, ["test.jpg"])

        mock_page_controller.page.evaluate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_wait_button_enabled_timeout(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit_prompt raising TimeoutError when button doesn't enable."""
    # Setup basics
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=False)  # Never enabled

    def locator_side_effect(selector):
        if "submit" in selector:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        else:
            return prompt_area

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock timeout constant to be very short
    with (
        patch("config.timeouts.SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", 100),
        patch.object(
            input_controller,
            "_open_upload_menu_and_choose_file",
            new_callable=AsyncMock,
        ),
        patch.object(
            input_controller, "_handle_post_upload_dialog", new_callable=AsyncMock
        ),
    ):
        with pytest.raises(TimeoutError, match="Submit button not enabled"):
            await input_controller.submit_prompt("test", [], lambda x: None)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_all_methods_fail(
    input_controller, mock_page_controller, mock_expect_async
):
    """Test submit_prompt raising exception when all submit methods fail."""
    # Setup
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    autosize = MagicMock()
    autosize.count = AsyncMock(return_value=1)
    autosize.first = MagicMock()
    autosize.first.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)
    submit_btn.click = AsyncMock(side_effect=Exception("Click failed"))

    def locator_side_effect(selector):
        if "submit" in selector:
            return submit_btn
        elif "autosize" in selector or "text-wrapper" in selector:
            return autosize
        else:
            return prompt_area

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock internal submit methods to fail
    input_controller._try_enter_submit = AsyncMock(return_value=False)
    input_controller._try_combo_submit = AsyncMock(return_value=False)
    input_controller._handle_post_upload_dialog = AsyncMock()
    input_controller._open_upload_menu_and_choose_file = AsyncMock()

    with pytest.raises(
        Exception, match="Submit failed: Button, Enter, and Combo key all failed"
    ):
        await input_controller.submit_prompt("test", [], lambda x: None)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_outer_exception(input_controller, mock_page_controller):
    """Test _open_upload_menu_and_choose_file handles outer exception."""
    # Mock locator to raise generic exception immediately
    mock_page_controller.page.locator.side_effect = Exception("Fatal error")

    result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])
    assert result is False
