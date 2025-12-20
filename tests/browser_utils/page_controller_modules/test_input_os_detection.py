from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_utils.page_controller_modules.input import InputController


# Re-use fixtures from test_input.py pattern
@pytest.fixture
def mock_page_controller():
    controller = MagicMock()
    controller.page = MagicMock()
    controller.page.keyboard.press = AsyncMock()
    controller.page.keyboard.down = AsyncMock()
    controller.page.keyboard.up = AsyncMock()
    controller.page.evaluate = AsyncMock()
    controller.logger = MagicMock()
    controller.req_id = "test_req_id"
    return controller


@pytest.fixture
def mock_constants():
    with patch(
        "browser_utils.page_controller_modules.input.SUBMIT_BUTTON_SELECTOR",
        "button[data-testid='send-button']",
    ):
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
def input_controller(mock_page_controller, mock_constants):
    return InputController(
        mock_page_controller.page,
        mock_page_controller.logger,
        mock_page_controller.req_id,
    )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_combo_submit_os_detection_env_darwin(
    input_controller, mock_page_controller
):
    """Test OS detection via environment variable (Darwin)."""
    textarea = MagicMock()
    textarea.focus = AsyncMock()
    textarea.input_value = AsyncMock(return_value="some text")

    # check_disconnect must return False to avoid ClientDisconnectedError
    check_disconnect = MagicMock(return_value=False)

    with patch.dict("os.environ", {"HOST_OS_FOR_SHORTCUT": "Darwin"}):
        # We expect Meta+Enter
        await input_controller._try_combo_submit(textarea, check_disconnect)

        # Verify key press
        # print(f"DEBUG: press calls: {mock_page_controller.page.keyboard.press.call_args_list}")
        # print(f"DEBUG: logger warning calls: {mock_page_controller.logger.warning.call_args_list}")
        mock_page_controller.page.keyboard.press.assert_called_with("Meta+Enter")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_combo_submit_os_detection_env_windows(
    input_controller, mock_page_controller
):
    """Test OS detection via environment variable (Windows)."""
    textarea = MagicMock()
    textarea.focus = AsyncMock()
    textarea.input_value = AsyncMock(return_value="some text")

    check_disconnect = MagicMock(return_value=False)

    with patch.dict("os.environ", {"HOST_OS_FOR_SHORTCUT": "Windows"}):
        # We expect Control+Enter
        await input_controller._try_combo_submit(textarea, check_disconnect)

        # Verify key press
        mock_page_controller.page.keyboard.press.assert_called_with("Control+Enter")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_combo_submit_os_detection_ua_mac(input_controller, mock_page_controller):
    """Test OS detection via userAgentData (Mac)."""
    textarea = MagicMock()
    textarea.focus = AsyncMock()
    textarea.input_value = AsyncMock(return_value="some text")
    check_disconnect = MagicMock(return_value=False)

    # Mock environment to be empty so it falls back to browser detection
    with patch.dict("os.environ", {}, clear=True):
        # Mock evaluate for userAgentData
        # First call checks userAgentData.platform
        mock_page_controller.page.evaluate.return_value = "macOS"

        await input_controller._try_combo_submit(textarea, check_disconnect)

        mock_page_controller.page.keyboard.press.assert_called_with("Meta+Enter")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_combo_submit_os_detection_ua_fallback_mac(
    input_controller, mock_page_controller
):
    """Test OS detection via userAgent fallback (Mac)."""
    textarea = MagicMock()
    textarea.focus = AsyncMock()
    textarea.input_value = AsyncMock(return_value="some text")
    check_disconnect = MagicMock(return_value=False)

    with patch.dict("os.environ", {}, clear=True):
        # First evaluate (userAgentData) raises exception
        # Second evaluate (userAgent) returns string
        mock_page_controller.page.evaluate.side_effect = [
            Exception("No userAgentData"),
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
        ]

        await input_controller._try_combo_submit(textarea, check_disconnect)

        mock_page_controller.page.keyboard.press.assert_called_with("Meta+Enter")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_combo_submit_os_detection_ua_fallback_other(
    input_controller, mock_page_controller
):
    """Test OS detection via userAgent fallback (Other)."""
    textarea = MagicMock()
    textarea.focus = AsyncMock()
    textarea.input_value = AsyncMock(return_value="some text")
    check_disconnect = MagicMock(return_value=False)

    with patch.dict("os.environ", {}, clear=True):
        # First evaluate (userAgentData) raises exception
        # Second evaluate (userAgent) returns string
        mock_page_controller.page.evaluate.side_effect = [
            Exception("No userAgentData"),
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
        ]

        await input_controller._try_combo_submit(textarea, check_disconnect)

        mock_page_controller.page.keyboard.press.assert_called_with("Control+Enter")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_agree(input_controller, mock_page_controller):
    """Test handling of post-upload dialog (Agree button)."""
    # Setup locators
    overlay_container = MagicMock()
    overlay_container.count = AsyncMock(return_value=1)

    agree_btn = MagicMock()
    agree_btn.count = AsyncMock(return_value=1)
    agree_btn.first.is_visible = AsyncMock(return_value=True)
    agree_btn.first.click = AsyncMock()

    # Configure locator chain
    mock_page_controller.page.locator.side_effect = (
        lambda s: overlay_container if "cdk-overlay-container" in s else MagicMock()
    )
    overlay_container.locator.side_effect = (
        lambda s: agree_btn if "Agree" in s else MagicMock()
    )

    await input_controller._handle_post_upload_dialog()

    # Should click the agree button
    assert agree_btn.first.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_copyright(
    input_controller, mock_page_controller
):
    """Test handling of post-upload dialog (Copyright button)."""
    # Setup locators
    overlay_container = MagicMock()
    overlay_container.count = AsyncMock(return_value=1)

    # Agree buttons not found/visible
    agree_btn = MagicMock()
    agree_btn.count = AsyncMock(return_value=0)

    copyright_btn = MagicMock()
    copyright_btn.count = AsyncMock(return_value=1)
    copyright_btn.first.is_visible = AsyncMock(return_value=True)
    copyright_btn.first.click = AsyncMock()

    # Configure locator chain
    def page_locator_side_effect(selector):
        if "cdk-overlay-container" in selector:
            return overlay_container
        if "copyright" in selector:
            return copyright_btn
        return MagicMock()

    mock_page_controller.page.locator.side_effect = page_locator_side_effect
    overlay_container.locator.return_value = agree_btn  # All agree buttons fail

    await input_controller._handle_post_upload_dialog()

    assert copyright_btn.first.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_backdrop(
    input_controller, mock_page_controller
):
    """Test waiting for backdrop to disappear."""
    overlay_container = MagicMock()
    # Container must exist for the function to proceed
    overlay_container.count = AsyncMock(return_value=1)

    # Mock button searches to find nothing so we fall through to backdrop check
    overlay_container.locator.return_value.count = AsyncMock(return_value=0)

    backdrop = MagicMock()
    backdrop.count = AsyncMock(return_value=1)

    mock_matcher = MagicMock()
    mock_matcher.to_be_hidden = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.input.expect_async",
        return_value=mock_matcher,
    ):

        def page_locator_side_effect(selector):
            if "cdk-overlay-container" in selector:
                return overlay_container
            if "cdk-overlay-backdrop" in selector:
                return backdrop
            return MagicMock()

        mock_page_controller.page.locator.side_effect = page_locator_side_effect

        await input_controller._handle_post_upload_dialog()

        mock_matcher.to_be_hidden.assert_called()
