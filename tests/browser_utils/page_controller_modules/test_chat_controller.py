import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError

from browser_utils.page_controller_modules.chat import ChatController

# Mock config constants
CONSTANTS = {
    "CLEAR_CHAT_BUTTON_SELECTOR": "button.clear",
    "CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR": "button.confirm",
    "CLEAR_CHAT_VERIFY_TIMEOUT_MS": 1000,
    "CLICK_TIMEOUT_MS": 1000,
    "OVERLAY_SELECTOR": "div.overlay",
    "RESPONSE_CONTAINER_SELECTOR": "div.response",
    "SUBMIT_BUTTON_SELECTOR": "button.submit",
    "WAIT_FOR_ELEMENT_TIMEOUT_MS": 1000,
}


@pytest.fixture(autouse=True)
def mock_constants():
    with patch.multiple("browser_utils.page_controller_modules.chat", **CONSTANTS):
        yield


@pytest.fixture
def mock_page_controller():
    controller = MagicMock()
    controller.page = MagicMock()
    controller.logger = MagicMock()
    controller.req_id = "test-req-id"
    # Setup page methods as AsyncMock
    controller.page.locator = MagicMock()
    controller.page.keyboard = MagicMock()
    controller.page.keyboard.press = AsyncMock()
    controller._check_disconnect = AsyncMock()
    return controller


@pytest.fixture
def chat_controller(mock_page_controller):
    # The BaseController __init__ requires (page, logger, req_id)
    # We'll just pass mock objects from mock_page_controller
    return ChatController(
        mock_page_controller.page,
        mock_page_controller.logger,
        mock_page_controller.req_id,
    )


@pytest.fixture
def mock_expect_async():
    with patch("browser_utils.page_controller_modules.chat.expect_async") as mock:
        # Create a mock object that supports .to_be_enabled(), .to_be_disabled(), etc.
        # These methods should return an awaitable (AsyncMock)
        assertion_mock = MagicMock()
        assertion_mock.to_be_enabled = AsyncMock()
        assertion_mock.to_be_disabled = AsyncMock()
        assertion_mock.to_be_visible = AsyncMock()
        assertion_mock.to_be_hidden = AsyncMock()

        mock.return_value = assertion_mock
        yield mock


@pytest.fixture
def mock_enable_temp_chat():
    with patch(
        "browser_utils.page_controller_modules.chat.enable_temporary_chat_mode",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_save_snapshot():
    with patch(
        "browser_utils.page_controller_modules.chat.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_history_success(
    chat_controller, mock_page_controller, mock_expect_async, mock_enable_temp_chat
):
    """Test successful chat clearing flow."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Setup locators
    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)
    response_container = MagicMock()

    # Mock locator calls
    def locator_side_effect(selector):
        if selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif selector == CONSTANTS["CLEAR_CHAT_BUTTON_SELECTOR"]:
            return clear_btn
        elif selector == CONSTANTS["CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR"]:
            return confirm_btn
        elif selector == CONSTANTS["OVERLAY_SELECTOR"]:
            return overlay
        elif selector == CONSTANTS["RESPONSE_CONTAINER_SELECTOR"]:
            return response_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock response container .last
    response_container.last = response_container

    # Mock url
    mock_page_controller.page.url = "https://example.com/c/123"

    # Mock _execute_chat_clear and _verify_chat_cleared to simplify main flow test
    # (We will test them separately, but here we want to ensure they are called)
    with (
        patch.object(
            chat_controller, "_execute_chat_clear", new_callable=AsyncMock
        ) as mock_exec,
        patch.object(
            chat_controller, "_verify_chat_cleared", new_callable=AsyncMock
        ) as mock_verify,
    ):
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Verify submit button flow
        assert submit_btn.click.called

        # Verify clear execution
        mock_exec.assert_awaited_once()
        mock_verify.assert_awaited_once()
        mock_enable_temp_chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_history_new_chat_skip(
    chat_controller, mock_page_controller, mock_expect_async
):
    """Test that clear chat is skipped if already on new_chat page."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Mock submit button check passes
    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    mock_page_controller.page.locator.return_value = submit_btn

    # Mock clear button check fails (not enabled)
    mock_expect_async.return_value.to_be_enabled.side_effect = Exception("Not enabled")

    # Mock URL to be new_chat
    mock_page_controller.page.url = "https://example.com/prompts/new_chat"

    with patch.object(
        chat_controller, "_execute_chat_clear", new_callable=AsyncMock
    ) as mock_exec:
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Should catch exception, log info, and NOT call execute
        mock_exec.assert_not_called()
        # Verify we logged the skip message
        # We can't easily check log message content with MagicMock unless we configure it,
        # but we verify the flow didn't proceed.


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_visible(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear when overlay is initially visible."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)  # Visible!

    # Setup expect_async mock for disappear check
    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._execute_chat_clear(
            clear_btn, confirm_btn, overlay, mock_check_disconnect
        )

        # Should click confirm directly
        confirm_btn.click.assert_awaited()
        clear_btn.click.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_hidden_initially(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear when overlay is initially hidden."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()

    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()

    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)  # Hidden initially

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()  # Overlay appears
        mock_expect.return_value.to_be_hidden = AsyncMock()  # Overlay disappears

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Should click clear first
            clear_btn.click.assert_awaited()
            # Then check overlay visible
            mock_expect.return_value.to_be_visible.assert_awaited()
            # Then click confirm
            confirm_btn.click.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops(chat_controller, mock_page_controller):
    """Test _dismiss_backdrops logic."""
    backdrop = MagicMock()
    # First call returns count 1 (exists), second call returns 0 (gone)
    backdrop.count = AsyncMock(side_effect=[1, 0])

    mock_page_controller.page.locator.return_value = backdrop

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._dismiss_backdrops()

        # Should have pressed Escape
        mock_page_controller.page.keyboard.press.assert_awaited_with("Escape")
        # Should have checked hidden
        mock_expect.return_value.to_be_hidden.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_chat_cleared_success(chat_controller, mock_page_controller):
    """Test _verify_chat_cleared success."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._verify_chat_cleared(mock_check_disconnect)

        mock_expect.return_value.to_be_hidden.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_chat_cleared_failure(chat_controller, mock_page_controller):
    """Test _verify_chat_cleared failure (should log warning but not raise)."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=Exception("Still visible")
        )

        # Should not raise exception
        await chat_controller._verify_chat_cleared(mock_check_disconnect)

        # Verify warning logged
        mock_page_controller.logger.warning.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_retries(chat_controller, mock_page_controller):
    """Test _execute_chat_clear retries and force clicks."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    # First click fails, second (force) succeeds
    clear_btn.click = AsyncMock(side_effect=[Exception("Click failed"), None])
    clear_btn.scroll_into_view_if_needed = AsyncMock()

    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()

    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_expect.return_value.to_be_hidden = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ) as mock_dismiss:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Verify retry logic
            assert clear_btn.click.call_count == 2
            # Check second call had force=True
            call_args = clear_btn.click.call_args_list[1]
            assert call_args.kwargs.get("force") is True
            # Check dismiss backdrops called
            mock_dismiss.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_wait_disappear_timeout(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear timeout waiting for dialog to disappear."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # to_be_hidden always raises TimeoutError
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=TimeoutError("Timeout")
        )

        with pytest.raises(Exception) as excinfo:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

        assert "达到最大重试次数" in str(excinfo.value)


# ==================== New Tests for Improved Coverage ====================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_submit_button_cancelled_error(
    chat_controller, mock_page_controller, mock_expect_async
):
    """Test CancelledError handling during submit button check (lines 46-50)."""
    mock_check_disconnect = MagicMock(return_value=False)

    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    mock_page_controller.page.locator.return_value = submit_btn

    # Submit button enabled check succeeds, but disabled check raises CancelledError
    mock_expect_async.return_value.to_be_enabled.side_effect = None
    mock_expect_async.return_value.to_be_disabled.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await chat_controller.clear_chat_history(mock_check_disconnect)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_button_not_enabled_non_new_chat(
    chat_controller, mock_page_controller, mock_expect_async
):
    """Test warning log when clear button not enabled on non-new_chat page (line 77)."""
    mock_check_disconnect = MagicMock(return_value=False)

    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    mock_page_controller.page.locator.return_value = submit_btn

    # Clear button check fails
    mock_expect_async.return_value.to_be_enabled.side_effect = Exception("Not enabled")

    # URL is NOT new_chat
    mock_page_controller.page.url = "https://example.com/prompts/some_other_page"

    with patch.object(
        chat_controller, "_execute_chat_clear", new_callable=AsyncMock
    ) as mock_exec:
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Should NOT call execute
        mock_exec.assert_not_called()
        # Verify warning was logged (line 77)
        assert mock_page_controller.logger.warning.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_error_snapshot_non_disconnect(
    chat_controller, mock_page_controller, mock_save_snapshot
):
    """Test error snapshot saving for non-disconnect errors (lines 96-126)."""
    mock_check_disconnect = MagicMock(return_value=False)

    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    overlay = MagicMock()

    def locator_side_effect(selector):
        if "submit" in selector:
            return submit_btn
        elif "clear" in selector:
            return clear_btn
        elif "confirm" in selector:
            return confirm_btn
        else:
            return overlay

    mock_page_controller.page.locator.side_effect = locator_side_effect
    mock_page_controller.page.url = "https://example.com/c/123"

    # Simulate error in _execute_chat_clear
    test_error = ValueError("Test error")

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # Submit button check passes
        mock_expect.return_value.to_be_enabled = AsyncMock()
        mock_expect.return_value.to_be_disabled = AsyncMock(
            side_effect=Exception("ignore")
        )

        with patch.object(
            chat_controller, "_execute_chat_clear", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.side_effect = test_error

            with patch(
                "browser_utils.page_controller_modules.chat.enable_temporary_chat_mode",
                new_callable=AsyncMock,
            ):
                try:
                    await chat_controller.clear_chat_history(mock_check_disconnect)
                    pytest.fail("Should have raised ValueError")
                except ValueError:
                    pass

                # Verify save_error_snapshot was called (lines 111-125)
                mock_save_snapshot.assert_awaited_once()
                call_args = mock_save_snapshot.call_args
                assert "clear_chat_error_" in call_args[0][0]
                assert call_args.kwargs["error_exception"] == test_error


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_error_snapshot_disconnect_skip(
    chat_controller, mock_page_controller, mock_save_snapshot
):
    """Test that ClientDisconnectedError skips snapshot saving (lines 102-104)."""
    from models import ClientDisconnectedError

    mock_check_disconnect = MagicMock(return_value=False)

    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    clear_btn = MagicMock()
    mock_page_controller.page.locator.return_value = clear_btn

    # Simulate ClientDisconnectedError
    disconnect_error = ClientDisconnectedError("Client gone")

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_enabled = AsyncMock()
        mock_expect.return_value.to_be_disabled = AsyncMock(
            side_effect=Exception("ignore")
        )

        with patch.object(
            chat_controller, "_execute_chat_clear", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.side_effect = disconnect_error

            with patch(
                "browser_utils.page_controller_modules.chat.enable_temporary_chat_mode",
                new_callable=AsyncMock,
            ):
                try:
                    await chat_controller.clear_chat_history(mock_check_disconnect)
                    pytest.fail("Should have raised ClientDisconnectedError")
                except ClientDisconnectedError:
                    pass

                # Verify save_error_snapshot was NOT called
                mock_save_snapshot.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_timeout_check(
    chat_controller, mock_page_controller
):
    """Test TimeoutError handling in overlay visibility check (lines 141-143)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    # is_visible raises TimeoutError
    overlay.is_visible = AsyncMock(side_effect=TimeoutError("Timeout"))

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_expect.return_value.to_be_hidden = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Should continue to clear button click path
            clear_btn.click.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_exception_check(
    chat_controller, mock_page_controller
):
    """Test generic Exception handling in overlay visibility check.

    Note: The implementation has a duplicate 'except Exception:' block, so the
    warning log is never reached. The exception is silently caught without logging.
    """
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    # is_visible raises generic exception
    overlay.is_visible = AsyncMock(side_effect=ValueError("Some error"))

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_expect.return_value.to_be_hidden = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # The exception is caught silently and proceeds to clear button path
            clear_btn.click.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_dismiss_backdrops_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in first _dismiss_backdrops call (lines 164-165)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(
        chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
    ) as mock_dismiss:
        mock_dismiss.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_scroll_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in scroll_into_view_if_needed (lines 171-172)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    # scroll raises CancelledError
    clear_btn.scroll_into_view_if_needed = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(chat_controller, "_dismiss_backdrops", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_scroll_exception_pass(
    chat_controller, mock_page_controller
):
    """Test Exception in scroll_into_view_if_needed is caught (line 173-174)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    # scroll raises exception but should be caught
    clear_btn.scroll_into_view_if_needed = AsyncMock(
        side_effect=ValueError("Scroll error")
    )
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_expect.return_value.to_be_hidden = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Should continue despite scroll error
            clear_btn.click.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_first_click_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in first clear button click (line 176-177)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    # First click raises CancelledError
    clear_btn.click = AsyncMock(side_effect=asyncio.CancelledError())
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(chat_controller, "_dismiss_backdrops", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_retry_dismiss_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in retry _dismiss_backdrops (lines 184-185)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    # First click fails
    clear_btn.click = AsyncMock(side_effect=ValueError("Click failed"))
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(
        chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
    ) as mock_dismiss:
        # First call succeeds, second call raises CancelledError
        mock_dismiss.side_effect = [None, asyncio.CancelledError()]

        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_force_click_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in force click (lines 192-193)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    # First click fails, force click raises CancelledError
    clear_btn.click = AsyncMock(
        side_effect=[ValueError("Click failed"), asyncio.CancelledError()]
    )
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(chat_controller, "_dismiss_backdrops", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_force_click_failure(
    chat_controller, mock_page_controller, mock_save_snapshot
):
    """Test force click failure raises error (lines 194-196)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    # Both clicks fail
    clear_btn.click = AsyncMock(
        side_effect=[ValueError("Click failed"), ValueError("Force click failed")]
    )
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch.object(chat_controller, "_dismiss_backdrops", new_callable=AsyncMock):
        with pytest.raises(ValueError) as excinfo:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

        assert "Force click failed" in str(excinfo.value)
        # Verify error logged
        mock_page_controller.logger.error.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_appear_timeout(
    chat_controller, mock_page_controller, mock_save_snapshot
):
    """Test overlay appear timeout saves snapshot (lines 207-211)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # Overlay appear timeout
        mock_expect.return_value.to_be_visible = AsyncMock(
            side_effect=TimeoutError("Timeout")
        )

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            try:
                await chat_controller._execute_chat_clear(
                    clear_btn, confirm_btn, overlay, mock_check_disconnect
                )
                pytest.fail("Should have raised Exception")
            except Exception as e:
                assert "等待清空聊天确认遮罩层超时" in str(e)

            # Verify snapshot saved
            mock_save_snapshot.assert_awaited_once()
            assert "clear_chat_overlay_timeout_" in mock_save_snapshot.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_confirm_scroll_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in confirm button scroll (line 222)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    # Confirm scroll raises CancelledError
    confirm_btn.scroll_into_view_if_needed = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            with pytest.raises(asyncio.CancelledError):
                await chat_controller._execute_chat_clear(
                    clear_btn, confirm_btn, overlay, mock_check_disconnect
                )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_confirm_click_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in confirm button click (lines 227-228)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    # Confirm click raises CancelledError
    confirm_btn.click = AsyncMock(side_effect=asyncio.CancelledError())
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            with pytest.raises(asyncio.CancelledError):
                await chat_controller._execute_chat_clear(
                    clear_btn, confirm_btn, overlay, mock_check_disconnect
                )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_confirm_force_click_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in confirm button force click (lines 237-238)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    # First click fails, force click raises CancelledError
    confirm_btn.click = AsyncMock(
        side_effect=[ValueError("Click failed"), asyncio.CancelledError()]
    )
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            with pytest.raises(asyncio.CancelledError):
                await chat_controller._execute_chat_clear(
                    clear_btn, confirm_btn, overlay, mock_check_disconnect
                )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_confirm_force_click_failure(
    chat_controller, mock_page_controller
):
    """Test confirm button force click failure (lines 239-243)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    # Both clicks fail
    confirm_btn.click = AsyncMock(
        side_effect=[ValueError("Click failed"), ValueError("Force click failed")]
    )
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            with pytest.raises(ValueError) as excinfo:
                await chat_controller._execute_chat_clear(
                    clear_btn, confirm_btn, overlay, mock_check_disconnect
                )

            assert "Force click failed" in str(excinfo.value)
            mock_page_controller.logger.error.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_disappear_client_disconnected(
    chat_controller, mock_page_controller
):
    """Test ClientDisconnectedError during dialog disappear wait (lines 279-281)."""
    from models import ClientDisconnectedError

    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # First to_be_hidden raises ClientDisconnectedError
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=ClientDisconnectedError("Client gone")
        )

        try:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )
            pytest.fail("Should have raised ClientDisconnectedError")
        except ClientDisconnectedError:
            pass

        # Verify info log about disconnect
        mock_page_controller.logger.info.assert_any_call(
            "客户端在等待清空确认对话框消失时断开连接。"
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_disappear_cancelled_error(
    chat_controller, mock_page_controller
):
    """Test CancelledError during dialog disappear wait (lines 282-284)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # First to_be_hidden raises CancelledError wrapped in other exception
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

        with pytest.raises(asyncio.CancelledError):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_disappear_other_error_retry(
    chat_controller, mock_page_controller
):
    """Test other error during disappear with retry (lines 285-291)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # First 2 attempts raise ValueError, third succeeds
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=[ValueError("Error 1"), ValueError("Error 2"), None, None]
        )

        await chat_controller._execute_chat_clear(
            clear_btn, confirm_btn, overlay, mock_check_disconnect
        )

        # Should have logged warnings
        assert mock_page_controller.logger.warning.call_count >= 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_disappear_other_error_max_retries(
    chat_controller, mock_page_controller
):
    """Test other error during disappear reaching max retries (line 290-291)."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # All 3 attempts raise ValueError
        test_error = ValueError("Persistent error")
        mock_expect.return_value.to_be_hidden = AsyncMock(side_effect=test_error)

        try:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            assert "Persistent error" in str(e)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_count_cancelled(chat_controller, mock_page_controller):
    """Test CancelledError in backdrop.count() (lines 308-309)."""
    backdrop = MagicMock()
    backdrop.count = AsyncMock(side_effect=asyncio.CancelledError())
    mock_page_controller.page.locator.return_value = backdrop

    with pytest.raises(asyncio.CancelledError):
        await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_count_exception(chat_controller, mock_page_controller):
    """Test Exception in backdrop.count() sets cnt to 0 (lines 310-311)."""
    backdrop = MagicMock()
    # count raises exception
    backdrop.count = AsyncMock(side_effect=ValueError("Count error"))
    mock_page_controller.page.locator.return_value = backdrop

    # Should not raise, just continues with cnt=0
    await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_keyboard_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in keyboard.press() (lines 324-325)."""
    backdrop = MagicMock()
    backdrop.count = AsyncMock(return_value=1)
    mock_page_controller.page.locator.return_value = backdrop
    mock_page_controller.page.keyboard.press = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    with pytest.raises(asyncio.CancelledError):
        await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_expect_hidden_cancelled(
    chat_controller, mock_page_controller
):
    """Test CancelledError in expect backdrop hidden (lines 320-321)."""
    backdrop = MagicMock()
    backdrop.count = AsyncMock(return_value=1)
    mock_page_controller.page.locator.return_value = backdrop

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

        with pytest.raises(asyncio.CancelledError):
            await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_expect_hidden_exception(
    chat_controller, mock_page_controller
):
    """Test Exception in expect backdrop hidden is caught (lines 322-323)."""
    backdrop = MagicMock()
    # First call returns 1, second returns 0
    backdrop.count = AsyncMock(side_effect=[1, 0])
    mock_page_controller.page.locator.return_value = backdrop

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=ValueError("Hidden check error")
        )

        # Should not raise
        await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_keyboard_exception(
    chat_controller, mock_page_controller
):
    """Test Exception in keyboard.press() is caught (lines 326-327)."""
    backdrop = MagicMock()
    backdrop.count = AsyncMock(side_effect=[1, 0])
    mock_page_controller.page.locator.return_value = backdrop
    mock_page_controller.page.keyboard.press = AsyncMock(
        side_effect=ValueError("Keyboard error")
    )

    # Should not raise
    await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_outer_cancelled(chat_controller, mock_page_controller):
    """Test CancelledError at outer try level (lines 330-331)."""
    # Locator itself raises CancelledError
    mock_page_controller.page.locator = MagicMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops_outer_exception(chat_controller, mock_page_controller):
    """Test Exception at outer try level is caught (lines 332-333)."""
    # Locator raises exception
    mock_page_controller.page.locator = MagicMock(
        side_effect=ValueError("Locator error")
    )

    # Should not raise
    await chat_controller._dismiss_backdrops()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_chat_cleared_cancelled_error(
    chat_controller, mock_page_controller
):
    """Test CancelledError in _verify_chat_cleared (line 346-347)."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

        with pytest.raises(asyncio.CancelledError):
            await chat_controller._verify_chat_cleared(mock_check_disconnect)


# ==================== [Chat] Tag Logging Verification Tests ====================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_chat_tag_on_clear_start(
    chat_controller, mock_page_controller, mock_expect_async
):
    """Verify [Chat] tag used in logging when clearing chat starts."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Setup minimal mocks to trigger early return
    mock_expect_async.return_value.to_be_enabled.side_effect = Exception("Not enabled")
    mock_page_controller.page.url = "https://example.com/prompts/new_chat"

    await chat_controller.clear_chat_history(mock_check_disconnect)

    # Verify [Chat] tag was used (check debug calls)
    debug_calls = [
        str(call) for call in mock_page_controller.logger.debug.call_args_list
    ]
    assert any("[Chat]" in str(call) for call in debug_calls)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_chat_tag_on_button_available(
    chat_controller, mock_page_controller, mock_expect_async, mock_enable_temp_chat
):
    """Verify [Chat] 清空按钮可用 log is issued."""
    mock_check_disconnect = MagicMock(return_value=False)

    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    clear_btn = MagicMock()
    mock_page_controller.page.locator.return_value = clear_btn
    mock_page_controller.page.url = "https://example.com/c/123"

    with (
        patch.object(chat_controller, "_execute_chat_clear", new_callable=AsyncMock),
        patch.object(chat_controller, "_verify_chat_cleared", new_callable=AsyncMock),
    ):
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Verify [Chat] 清空按钮可用 log
        debug_calls = [
            str(call) for call in mock_page_controller.logger.debug.call_args_list
        ]
        assert any(
            "清空按钮可用" in str(call) or "[Chat]" in str(call) for call in debug_calls
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_chat_tag_on_verify_success(chat_controller, mock_page_controller):
    """Verify [Chat] 验证通过 log on successful verification."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._verify_chat_cleared(mock_check_disconnect)

        # Verify [Chat] 验证通过 log
        debug_calls = [
            str(call) for call in mock_page_controller.logger.debug.call_args_list
        ]
        assert any(
            "验证通过" in str(call) or "[Chat]" in str(call) for call in debug_calls
        )
