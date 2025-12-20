import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from browser_utils.page_controller_modules.parameters import ParameterController
from config import (
    MAT_CHIP_REMOVE_BUTTON_SELECTOR,
    STOP_SEQUENCE_INPUT_SELECTOR,
    TEMPERATURE_INPUT_SELECTOR,
    TOP_P_INPUT_SELECTOR,
)
from models import ClientDisconnectedError


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.locator = MagicMock()
    # Setup default locator behavior to return an AsyncMock that can be awaited/called
    locator_mock = AsyncMock()
    locator_mock.input_value.return_value = "0.5"
    locator_mock.get_attribute.return_value = "false"
    locator_mock.count.return_value = 0
    page.locator.return_value = locator_mock
    return page


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def controller(mock_page, mock_logger):
    return ParameterController(mock_page, mock_logger, "test_req_id")


@pytest.fixture
def mock_check_disconnect():
    return MagicMock(return_value=False)


@pytest.fixture
def mock_lock():
    return asyncio.Lock()


@pytest.fixture(autouse=True)
def mock_expect_async():
    with patch("browser_utils.page_controller_modules.parameters.expect_async") as mock:
        mock.return_value.to_be_visible = AsyncMock()
        mock.return_value.to_have_class = AsyncMock()
        yield mock


@pytest.fixture(autouse=True)
def mock_save_snapshot():
    with patch(
        "browser_utils.operations.save_error_snapshot", new_callable=AsyncMock
    ) as mock:
        yield mock


@pytest.mark.asyncio
async def test_adjust_temperature_cache_hit(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    page_params_cache = {"temperature": 0.7}

    await controller._adjust_temperature(
        0.7, page_params_cache, mock_lock, mock_check_disconnect
    )

    # Should not interact with page
    mock_page.locator.assert_not_called()
    assert page_params_cache["temperature"] == 0.7


@pytest.mark.asyncio
async def test_adjust_temperature_update_success(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    page_params_cache = {"temperature": 0.5}
    target_temp = 0.8

    # Mock locator interactions
    temp_locator = AsyncMock()
    # First read: 0.5, Second read (after update): 0.8
    temp_locator.input_value.side_effect = ["0.5", "0.8"]
    mock_page.locator.return_value = temp_locator

    await controller._adjust_temperature(
        target_temp, page_params_cache, mock_lock, mock_check_disconnect
    )

    mock_page.locator.assert_called_with(TEMPERATURE_INPUT_SELECTOR)
    temp_locator.fill.assert_called_with(str(target_temp), timeout=5000)
    assert page_params_cache["temperature"] == target_temp


@pytest.mark.asyncio
async def test_adjust_temperature_verify_fail(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    page_params_cache = {}
    target_temp = 0.8

    temp_locator = AsyncMock()
    # First read: 0.5, Second read (after update): 0.5 (update failed)
    temp_locator.input_value.side_effect = ["0.5", "0.5"]
    mock_page.locator.return_value = temp_locator

    await controller._adjust_temperature(
        target_temp, page_params_cache, mock_lock, mock_check_disconnect
    )

    assert "temperature" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_temperature_value_error(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    page_params_cache = {}

    temp_locator = AsyncMock()
    temp_locator.input_value.return_value = "invalid"
    mock_page.locator.return_value = temp_locator

    await controller._adjust_temperature(
        0.5, page_params_cache, mock_lock, mock_check_disconnect
    )

    assert "temperature" not in page_params_cache


@pytest.mark.asyncio
async def test_adjust_max_tokens_from_model_config(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    page_params_cache = {}
    parsed_model_list = [{"id": "model-a", "supported_max_output_tokens": 1024}]

    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = ["512", "1024"]
    mock_page.locator.return_value = tokens_locator

    await controller._adjust_max_tokens(
        2048,  # Requesting more than supported
        page_params_cache,
        mock_lock,
        "model-a",
        parsed_model_list,
        mock_check_disconnect,
    )

    # Should be clamped to 1024
    tokens_locator.fill.assert_called_with("1024", timeout=5000)
    assert page_params_cache["max_output_tokens"] == 1024


@pytest.mark.asyncio
async def test_adjust_max_tokens_verify_fail(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    page_params_cache = {}

    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = ["100", "100"]
    mock_page.locator.return_value = tokens_locator

    await controller._adjust_max_tokens(
        200, page_params_cache, mock_lock, None, [], mock_check_disconnect
    )

    assert "max_output_tokens" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_stop_sequences(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test stop sequence adjustment with removal and addition."""
    page_params_cache = {}
    stop_sequences = ["stop1", "stop2"]

    input_locator = AsyncMock()

    # Mock for specific remove buttons (for removal of old1, old2)
    remove_old1_btn = AsyncMock()
    remove_old1_btn.count = AsyncMock(return_value=1)
    remove_old2_btn = AsyncMock()
    remove_old2_btn.count = AsyncMock(return_value=1)

    def get_locator(selector):
        if selector == STOP_SEQUENCE_INPUT_SELECTOR:
            return input_locator
        elif selector == 'mat-chip button.remove-button[aria-label="Remove old1"]':
            return remove_old1_btn
        elif selector == 'mat-chip button.remove-button[aria-label="Remove old2"]':
            return remove_old2_btn
        # Default for other selectors
        return AsyncMock()

    mock_page.locator.side_effect = get_locator

    # Patch _get_current_stop_sequences to return existing stops first, then final state
    call_count = [0]

    async def mock_get_current():
        call_count[0] += 1
        if call_count[0] == 1:
            # Initial state: has old1 and old2
            return {"old1", "old2"}
        else:
            # After removal and addition: has stop1 and stop2
            return {"stop1", "stop2"}

    with patch.object(controller, "_get_current_stop_sequences", mock_get_current):
        await controller._adjust_stop_sequences(
            stop_sequences, page_params_cache, mock_lock, mock_check_disconnect
        )

    # Should remove existing chips (old1, old2)
    assert remove_old1_btn.first.click.call_count == 1
    assert remove_old2_btn.first.click.call_count == 1

    # Should add new sequences
    assert input_locator.fill.call_count == 2
    input_locator.fill.assert_has_calls(
        [call("stop1", timeout=3000), call("stop2", timeout=3000)], any_order=True
    )
    assert input_locator.press.call_count == 2

    assert page_params_cache["stop_sequences"] == {"stop1", "stop2"}


@pytest.mark.asyncio
async def test_adjust_top_p_update(controller, mock_check_disconnect, mock_page):
    target_top_p = 0.9

    locator = AsyncMock()
    locator.input_value.side_effect = ["0.5", "0.9"]
    mock_page.locator.return_value = locator

    await controller._adjust_top_p(target_top_p, mock_check_disconnect)

    mock_page.locator.assert_called_with(TOP_P_INPUT_SELECTOR)
    locator.fill.assert_called_with(str(target_top_p), timeout=5000)


@pytest.mark.asyncio
async def test_ensure_tools_panel_expanded(
    controller, mock_check_disconnect, mock_page
):
    # Setup: panel is collapsed
    collapse_btn = AsyncMock()
    # locator() is sync, so we need to mock it as MagicMock on the AsyncMock
    collapse_btn.locator = MagicMock()

    grandparent = AsyncMock()
    grandparent.get_attribute.return_value = "some-class"  # not expanded

    collapse_btn.locator.return_value = grandparent
    mock_page.locator.return_value = collapse_btn

    await controller._ensure_tools_panel_expanded(mock_check_disconnect)

    collapse_btn.click.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_tools_panel_already_expanded(
    controller, mock_check_disconnect, mock_page
):
    # Setup: panel is expanded
    collapse_btn = AsyncMock()
    # locator() is sync
    collapse_btn.locator = MagicMock()

    grandparent = AsyncMock()
    grandparent.get_attribute.return_value = "some-class expanded"

    collapse_btn.locator.return_value = grandparent
    mock_page.locator.return_value = collapse_btn

    await controller._ensure_tools_panel_expanded(mock_check_disconnect)

    collapse_btn.click.assert_not_called()


@pytest.mark.asyncio
async def test_open_url_content(controller, mock_check_disconnect, mock_page):
    # Setup: switch is off
    switch = AsyncMock()
    switch.get_attribute.return_value = "false"
    mock_page.locator.return_value = switch

    await controller._open_url_content(mock_check_disconnect)

    switch.click.assert_called_once()


@pytest.mark.asyncio
async def test_should_enable_google_search(controller):
    # Case 1: No tools -> Default (True/False based on config, assuming True for test if config not mocked, but config is imported)
    # We need to check what ENABLE_GOOGLE_SEARCH is in config.
    # In parameters.py it imports ENABLE_GOOGLE_SEARCH.
    # Let's assume we want to test the logic based on tools param.

    # Case 2: Tools with googleSearch
    params_with_search = {"tools": [{"function": {"name": "googleSearch"}}]}
    assert controller._should_enable_google_search(params_with_search) is True

    # Case 3: Tools with google_search_retrieval
    params_with_retrieval = {"tools": [{"google_search_retrieval": {}}]}
    assert controller._should_enable_google_search(params_with_retrieval) is True

    # Case 4: Tools without search
    params_no_search = {"tools": [{"function": {"name": "otherTool"}}]}
    assert controller._should_enable_google_search(params_no_search) is False


@pytest.mark.asyncio
async def test_adjust_google_search(controller, mock_check_disconnect, mock_page):
    # Setup: Request wants search enabled, currently disabled
    request_params = {"tools": [{"function": {"name": "googleSearch"}}]}

    toggle = AsyncMock()
    toggle.get_attribute.side_effect = [
        "false",
        "true",
    ]  # Initial check, then check after click
    mock_page.locator.return_value = toggle

    # Mock _supports_google_search to return True so the function doesn't skip early
    with patch.object(controller, "_supports_google_search", return_value=True):
        await controller._adjust_google_search(
            request_params, "gemini-2.0-flash", mock_check_disconnect
        )

    toggle.click.assert_called_once()


@pytest.mark.asyncio
async def test_adjust_parameters_full_flow(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    # Mock all internal adjust methods to verify orchestration
    with (
        patch.object(
            controller, "_adjust_temperature", new_callable=AsyncMock
        ) as mock_temp,
        patch.object(
            controller, "_adjust_max_tokens", new_callable=AsyncMock
        ) as mock_tokens,
        patch.object(
            controller, "_adjust_stop_sequences", new_callable=AsyncMock
        ) as mock_stop,
        patch.object(controller, "_adjust_top_p", new_callable=AsyncMock) as mock_top_p,
        patch.object(
            controller, "_ensure_tools_panel_expanded", new_callable=AsyncMock
        ) as mock_panel,
        patch.object(controller, "_open_url_content", new_callable=AsyncMock),
        patch.object(
            controller, "_adjust_google_search", new_callable=AsyncMock
        ) as mock_search,
    ):
        # Mock _handle_thinking_budget if it were to exist (dynamically added in real usage)
        controller._handle_thinking_budget = AsyncMock()

        request_params = {
            "temperature": 0.9,
            "max_output_tokens": 100,
            "stop": ["stop"],
            "top_p": 0.95,
        }
        page_params_cache = {}

        await controller.adjust_parameters(
            request_params,
            page_params_cache,
            mock_lock,
            "model-id",
            [],
            mock_check_disconnect,
        )

        mock_temp.assert_called_once()
        mock_tokens.assert_called_once()
        mock_stop.assert_called_once()
        mock_top_p.assert_called_once()
        mock_panel.assert_called_once()
        # mock_url called if ENABLE_URL_CONTEXT is True.
        # We can't easily control ENABLE_URL_CONTEXT here without patching config before import or reloading module.
        # But we can check if it was called or not based on default.

        controller._handle_thinking_budget.assert_called_once()
        mock_search.assert_called_once()


@pytest.mark.asyncio
async def test_client_disconnected_error(controller, mock_lock, mock_check_disconnect):
    mock_check_disconnect.side_effect = lambda stage: True

    with pytest.raises(ClientDisconnectedError):
        await controller.adjust_parameters(
            {}, {}, mock_lock, None, [], mock_check_disconnect
        )


@pytest.mark.asyncio
async def test_adjust_temperature_clamping(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test temperature clamping warning (line 117)."""
    page_params_cache = {}

    temp_locator = AsyncMock()
    temp_locator.input_value.side_effect = ["0.5", "2.0"]
    mock_page.locator.return_value = temp_locator

    # Request temperature > 2.0, should be clamped
    await controller._adjust_temperature(
        3.5, page_params_cache, mock_lock, mock_check_disconnect
    )

    # Should clamp to 2.0 and log warning
    temp_locator.fill.assert_called_with("2.0", timeout=5000)
    assert page_params_cache["temperature"] == 2.0


@pytest.mark.asyncio
async def test_adjust_temperature_page_already_matches(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test when page temperature already matches request (lines 148-151)."""
    page_params_cache = {}
    target_temp = 0.8

    temp_locator = AsyncMock()
    # Page already has the correct value
    temp_locator.input_value.return_value = "0.8"
    mock_page.locator.return_value = temp_locator

    await controller._adjust_temperature(
        target_temp, page_params_cache, mock_lock, mock_check_disconnect
    )

    # Should NOT call fill (no need to update)
    temp_locator.fill.assert_not_called()
    # Should update cache
    assert page_params_cache["temperature"] == 0.8


@pytest.mark.asyncio
async def test_adjust_temperature_general_exception(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test general exception handling in temperature adjustment (lines 189-197)."""
    page_params_cache = {"temperature": 0.5}

    temp_locator = AsyncMock()
    # Simulate Playwright exception
    temp_locator.input_value.side_effect = Exception("Playwright error")
    mock_page.locator.return_value = temp_locator

    await controller._adjust_temperature(
        0.8, page_params_cache, mock_lock, mock_check_disconnect
    )

    # Should clear cache and save snapshot
    assert "temperature" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_temperature_cancelled_error(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test CancelledError is re-raised (line 190-191)."""
    page_params_cache = {}

    temp_locator = AsyncMock()
    temp_locator.input_value.side_effect = asyncio.CancelledError()
    mock_page.locator.return_value = temp_locator

    with pytest.raises(asyncio.CancelledError):
        await controller._adjust_temperature(
            0.8, page_params_cache, mock_lock, mock_check_disconnect
        )


@pytest.mark.asyncio
async def test_adjust_temperature_client_disconnected_exception(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test ClientDisconnectedError is re-raised (line 196-197)."""
    page_params_cache = {}

    temp_locator = AsyncMock()
    temp_locator.input_value.side_effect = ClientDisconnectedError(
        "test_req", "test stage"
    )
    mock_page.locator.return_value = temp_locator

    with pytest.raises(ClientDisconnectedError):
        await controller._adjust_temperature(
            0.8, page_params_cache, mock_lock, mock_check_disconnect
        )

    # Should still save snapshot before re-raising
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_max_tokens_invalid_supported_tokens(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test handling of invalid supported_max_output_tokens (lines 231-237)."""
    page_params_cache = {}
    parsed_model_list = [
        {"id": "model-a", "supported_max_output_tokens": -100},  # Invalid: negative
        {
            "id": "model-b",
            "supported_max_output_tokens": "invalid",
        },  # Invalid: non-numeric
    ]

    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = ["100", "1000"]
    mock_page.locator.return_value = tokens_locator

    # Test with model-a (negative value)
    await controller._adjust_max_tokens(
        1000,
        page_params_cache,
        mock_lock,
        "model-a",
        parsed_model_list,
        mock_check_disconnect,
    )

    # Should log warning and use default max (65536)
    assert page_params_cache["max_output_tokens"] == 1000

    # Test with model-b (non-numeric value)
    page_params_cache = {}
    tokens_locator.input_value.side_effect = ["100", "1000"]

    await controller._adjust_max_tokens(
        1000,
        page_params_cache,
        mock_lock,
        "model-b",
        parsed_model_list,
        mock_check_disconnect,
    )

    # Should handle ValueError/TypeError gracefully
    assert page_params_cache["max_output_tokens"] == 1000


@pytest.mark.asyncio
async def test_adjust_max_tokens_cache_hit(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test max tokens cache hit (lines 252-255)."""
    page_params_cache = {"max_output_tokens": 2048}

    await controller._adjust_max_tokens(
        2048, page_params_cache, mock_lock, None, [], mock_check_disconnect
    )

    # Should not interact with page
    mock_page.locator.assert_not_called()
    assert page_params_cache["max_output_tokens"] == 2048


@pytest.mark.asyncio
async def test_adjust_max_tokens_page_already_matches(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test when page max tokens already matches request (lines 271-274)."""
    page_params_cache = {}
    target_tokens = 4096

    tokens_locator = AsyncMock()
    # Page already has the correct value
    tokens_locator.input_value.return_value = "4096"
    mock_page.locator.return_value = tokens_locator

    await controller._adjust_max_tokens(
        target_tokens, page_params_cache, mock_lock, None, [], mock_check_disconnect
    )

    # Should NOT call fill (no need to update)
    tokens_locator.fill.assert_not_called()
    # Should update cache
    assert page_params_cache["max_output_tokens"] == 4096


@pytest.mark.asyncio
async def test_adjust_parameters_url_context_disabled(
    controller, mock_lock, mock_check_disconnect
):
    """Test adjust_parameters when ENABLE_URL_CONTEXT is False (line 92)."""
    with (
        patch.object(controller, "_adjust_temperature", new_callable=AsyncMock),
        patch.object(controller, "_adjust_max_tokens", new_callable=AsyncMock),
        patch.object(controller, "_adjust_stop_sequences", new_callable=AsyncMock),
        patch.object(controller, "_adjust_top_p", new_callable=AsyncMock),
        patch.object(
            controller, "_ensure_tools_panel_expanded", new_callable=AsyncMock
        ),
        patch.object(
            controller, "_open_url_content", new_callable=AsyncMock
        ) as mock_url,
        patch.object(controller, "_adjust_google_search", new_callable=AsyncMock),
        patch(
            "browser_utils.page_controller_modules.parameters.ENABLE_URL_CONTEXT", False
        ),
    ):
        controller._handle_thinking_budget = AsyncMock()

        await controller.adjust_parameters(
            {}, {}, mock_lock, None, [], mock_check_disconnect
        )

        # Should NOT call _open_url_content when ENABLE_URL_CONTEXT is False
        mock_url.assert_not_called()


@pytest.mark.asyncio
async def test_adjust_max_tokens_value_error(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test ValueError handling in max tokens adjustment (lines 307-311)."""
    page_params_cache = {}

    tokens_locator = AsyncMock()
    tokens_locator.input_value.return_value = "invalid_number"
    mock_page.locator.return_value = tokens_locator

    await controller._adjust_max_tokens(
        1000, page_params_cache, mock_lock, None, [], mock_check_disconnect
    )

    # Should clear cache and save snapshot
    assert "max_output_tokens" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_max_tokens_general_exception(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test general exception handling in max tokens (lines 312-320)."""
    page_params_cache = {}

    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = Exception("Playwright error")
    mock_page.locator.return_value = tokens_locator

    await controller._adjust_max_tokens(
        1000, page_params_cache, mock_lock, None, [], mock_check_disconnect
    )

    # Should clear cache and save snapshot
    assert "max_output_tokens" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_max_tokens_cancelled_error(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test CancelledError is re-raised in max tokens."""
    page_params_cache = {}

    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = asyncio.CancelledError()
    mock_page.locator.return_value = tokens_locator

    with pytest.raises(asyncio.CancelledError):
        await controller._adjust_max_tokens(
            1000, page_params_cache, mock_lock, None, [], mock_check_disconnect
        )


@pytest.mark.asyncio
async def test_adjust_stop_sequences_single_string(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test stop sequences with single string input normalizes to set."""
    page_params_cache = {}

    input_locator = AsyncMock()

    def get_locator(selector):
        if selector == STOP_SEQUENCE_INPUT_SELECTOR:
            return input_locator
        return AsyncMock()

    mock_page.locator.side_effect = get_locator

    # Patch _get_current_stop_sequences: initially empty, then has STOP after addition
    call_count = [0]

    async def mock_get_current():
        call_count[0] += 1
        if call_count[0] == 1:
            return set()  # Initially empty
        else:
            return {"STOP"}  # After addition

    with patch.object(controller, "_get_current_stop_sequences", mock_get_current):
        # Pass single string instead of list
        await controller._adjust_stop_sequences(
            "STOP", page_params_cache, mock_lock, mock_check_disconnect
        )

    # Should normalize to set and add it
    input_locator.fill.assert_called_once()
    assert page_params_cache["stop_sequences"] == {"STOP"}


@pytest.mark.asyncio
async def test_adjust_stop_sequences_page_matches_request(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test when page state already matches request - no changes needed."""
    page_params_cache = {}

    # Patch _get_current_stop_sequences: page already has the requested stops
    async def mock_get_current():
        return {"stop1", "stop2"}

    with patch.object(controller, "_get_current_stop_sequences", mock_get_current):
        await controller._adjust_stop_sequences(
            ["stop1", "stop2"], page_params_cache, mock_lock, mock_check_disconnect
        )

    # Should only call _get_current_stop_sequences, no add/remove operations
    # The locator for input should not be called
    assert page_params_cache["stop_sequences"] == {"stop1", "stop2"}


@pytest.mark.asyncio
async def test_adjust_stop_sequences_removal_exception(
    controller, mock_lock, mock_check_disconnect, mock_page
):
    """Test exception during chip removal (lines 377-378)."""
    page_params_cache = {}

    input_locator = AsyncMock()
    remove_btn_locator = AsyncMock()
    remove_btn_locator.count.side_effect = [
        2,
        2,
    ]  # Has chips, then exception during removal
    remove_btn_locator.first.click = AsyncMock(side_effect=Exception("Click failed"))

    def get_locator(selector):
        if selector == STOP_SEQUENCE_INPUT_SELECTOR:
            return input_locator
        elif selector == MAT_CHIP_REMOVE_BUTTON_SELECTOR:
            return remove_btn_locator
        return AsyncMock()

    mock_page.locator.side_effect = get_locator

    await controller._adjust_stop_sequences(
        ["new_stop"], page_params_cache, mock_lock, mock_check_disconnect
    )

    # Should handle exception and continue
    assert "stop_sequences" in page_params_cache


@pytest.mark.asyncio
async def test_adjust_stop_sequences_general_exception(
    controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test general exception during stop sequence adjustment."""
    page_params_cache = {}

    # Patch _get_current_stop_sequences to succeed initially
    # but then cause an error in the locator for input
    input_locator = AsyncMock()
    input_locator.fill.side_effect = Exception("Fill failed")

    def get_locator(selector):
        if selector == STOP_SEQUENCE_INPUT_SELECTOR:
            return input_locator
        return AsyncMock()

    mock_page.locator.side_effect = get_locator

    # First call returns empty, second would verify but exception is raised first
    call_count = [0]

    async def mock_get_current():
        call_count[0] += 1
        return set()

    with patch.object(controller, "_get_current_stop_sequences", mock_get_current):
        await controller._adjust_stop_sequences(
            ["stop"], page_params_cache, mock_lock, mock_check_disconnect
        )

    # Should clear cache and save snapshot
    assert "stop_sequences" not in page_params_cache
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_top_p_clamping(controller, mock_check_disconnect, mock_page):
    """Test top_p clamping warning (line 407)."""
    locator = AsyncMock()
    locator.input_value.side_effect = ["0.5", "1.0"]
    mock_page.locator.return_value = locator

    # Request top_p > 1.0, should be clamped
    await controller._adjust_top_p(1.5, mock_check_disconnect)

    # Should clamp to 1.0 and log warning
    locator.fill.assert_called_with("1.0", timeout=5000)


@pytest.mark.asyncio
async def test_adjust_top_p_value_error(
    controller, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test top_p ValueError handling (lines 543-547)."""
    locator = AsyncMock()
    locator.input_value.return_value = "invalid"
    mock_page.locator.return_value = locator

    await controller._adjust_top_p(0.9, mock_check_disconnect)

    # Should save snapshot on ValueError
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_top_p_general_exception(
    controller, mock_check_disconnect, mock_page, mock_save_snapshot
):
    """Test top_p general exception handling (lines 548-556)."""
    locator = AsyncMock()
    locator.input_value.side_effect = Exception("Playwright error")
    mock_page.locator.return_value = locator

    await controller._adjust_top_p(0.9, mock_check_disconnect)

    # Should save snapshot on exception
    mock_save_snapshot.assert_called()


@pytest.mark.asyncio
async def test_adjust_top_p_cancelled_error(
    controller, mock_check_disconnect, mock_page
):
    """Test top_p CancelledError is re-raised (line 549-550)."""
    locator = AsyncMock()
    locator.input_value.side_effect = asyncio.CancelledError()
    mock_page.locator.return_value = locator

    with pytest.raises(asyncio.CancelledError):
        await controller._adjust_top_p(0.9, mock_check_disconnect)


@pytest.mark.asyncio
async def test_adjust_top_p_client_disconnected(
    controller, mock_check_disconnect, mock_page
):
    """Test top_p ClientDisconnectedError is re-raised (lines 555-556)."""
    locator = AsyncMock()
    locator.input_value.side_effect = ClientDisconnectedError("test_req", "test stage")
    mock_page.locator.return_value = locator

    with pytest.raises(ClientDisconnectedError):
        await controller._adjust_top_p(0.9, mock_check_disconnect)


@pytest.mark.asyncio
async def test_ensure_tools_panel_expanded_exception(
    controller, mock_check_disconnect, mock_page
):
    """Test tools panel expansion exception handling (lines 585-591)."""
    collapse_btn = AsyncMock()
    collapse_btn.locator = MagicMock()
    collapse_btn.locator.return_value.get_attribute.side_effect = Exception(
        "Playwright error"
    )
    mock_page.locator.return_value = collapse_btn

    # Should not raise, just log error
    await controller._ensure_tools_panel_expanded(mock_check_disconnect)


@pytest.mark.asyncio
async def test_ensure_tools_panel_expanded_cancelled_error(
    controller, mock_check_disconnect, mock_page
):
    """Test tools panel CancelledError is re-raised (line 586-587)."""
    collapse_btn = AsyncMock()
    collapse_btn.locator = MagicMock()
    collapse_btn.locator.return_value.get_attribute.side_effect = (
        asyncio.CancelledError()
    )
    mock_page.locator.return_value = collapse_btn

    with pytest.raises(asyncio.CancelledError):
        await controller._ensure_tools_panel_expanded(mock_check_disconnect)


@pytest.mark.asyncio
async def test_ensure_tools_panel_expanded_client_disconnected(
    controller, mock_check_disconnect, mock_page
):
    """Test tools panel ClientDisconnectedError is re-raised (lines 590-591)."""
    collapse_btn = AsyncMock()
    collapse_btn.locator = MagicMock()
    collapse_btn.locator.return_value.get_attribute.side_effect = (
        ClientDisconnectedError("test_req", "test stage")
    )
    mock_page.locator.return_value = collapse_btn

    with pytest.raises(ClientDisconnectedError):
        await controller._ensure_tools_panel_expanded(mock_check_disconnect)


@pytest.mark.asyncio
async def test_open_url_content_exception(controller, mock_check_disconnect, mock_page):
    """Test URL content exception handling (lines 610-615)."""
    switch = AsyncMock()
    switch.get_attribute.side_effect = Exception("Playwright error")
    mock_page.locator.return_value = switch

    # Should not raise, just log error
    await controller._open_url_content(mock_check_disconnect)


@pytest.mark.asyncio
async def test_open_url_content_cancelled_error(
    controller, mock_check_disconnect, mock_page
):
    """Test URL content CancelledError is re-raised (line 611-612)."""
    switch = AsyncMock()
    switch.get_attribute.side_effect = asyncio.CancelledError()
    mock_page.locator.return_value = switch

    with pytest.raises(asyncio.CancelledError):
        await controller._open_url_content(mock_check_disconnect)


@pytest.mark.asyncio
async def test_open_url_content_client_disconnected(
    controller, mock_check_disconnect, mock_page
):
    """Test URL content ClientDisconnectedError is re-raised (lines 614-615)."""
    switch = AsyncMock()
    switch.get_attribute.side_effect = ClientDisconnectedError("test_req", "test stage")
    mock_page.locator.return_value = switch

    with pytest.raises(ClientDisconnectedError):
        await controller._open_url_content(mock_check_disconnect)


@pytest.mark.asyncio
async def test_adjust_google_search_model_not_supported(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search skipped for unsupported models (lines 661-663)."""
    request_params = {"tools": [{"function": {"name": "googleSearch"}}]}

    # Model doesn't support Google Search
    with patch.object(controller, "_supports_google_search", return_value=False):
        await controller._adjust_google_search(
            request_params, "gemini-2.0-flash-lite", mock_check_disconnect
        )

    # Should not interact with page
    mock_page.locator.assert_not_called()


@pytest.mark.asyncio
async def test_adjust_google_search_toggle_not_visible(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search when toggle not visible (AssertionError case, lines 715-716)."""
    request_params = {}
    toggle = AsyncMock()
    mock_page.locator.return_value = toggle

    with (
        patch.object(controller, "_supports_google_search", return_value=True),
        patch(
            "browser_utils.page_controller_modules.parameters.expect_async"
        ) as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock(
            side_effect=AssertionError("Locator expected to be visible")
        )

        # Should not raise, just log debug message
        await controller._adjust_google_search(
            request_params, "gemini-flash", mock_check_disconnect
        )


@pytest.mark.asyncio
async def test_adjust_google_search_general_exception(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search general exception (lines 717-718)."""
    request_params = {}
    toggle = AsyncMock()
    toggle.get_attribute.side_effect = RuntimeError("Unexpected error")
    mock_page.locator.return_value = toggle

    with patch.object(controller, "_supports_google_search", return_value=True):
        # Should not raise, just log error
        await controller._adjust_google_search(
            request_params, "gemini-flash", mock_check_disconnect
        )


@pytest.mark.asyncio
async def test_adjust_google_search_cancelled_error(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search CancelledError is re-raised (line 711-712)."""
    request_params = {}
    toggle = AsyncMock()
    toggle.get_attribute.side_effect = asyncio.CancelledError()
    mock_page.locator.return_value = toggle

    with patch.object(controller, "_supports_google_search", return_value=True):
        with pytest.raises(asyncio.CancelledError):
            await controller._adjust_google_search(
                request_params, "gemini-flash", mock_check_disconnect
            )


@pytest.mark.asyncio
async def test_adjust_google_search_client_disconnected(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search ClientDisconnectedError is re-raised (lines 719-720)."""
    request_params = {}
    toggle = AsyncMock()
    toggle.get_attribute.side_effect = ClientDisconnectedError("test_req", "test stage")
    mock_page.locator.return_value = toggle

    with patch.object(controller, "_supports_google_search", return_value=True):
        with pytest.raises(ClientDisconnectedError):
            await controller._adjust_google_search(
                request_params, "gemini-flash", mock_check_disconnect
            )


@pytest.mark.asyncio
async def test_adjust_google_search_update_failed(
    controller, mock_check_disconnect, mock_page
):
    """Test Google Search toggle update verification failure (lines 704-708)."""
    request_params = {"tools": [{"function": {"name": "googleSearch"}}]}

    toggle = AsyncMock()
    # Initially off, stays off after click (update failed)
    toggle.get_attribute.side_effect = ["false", "false"]
    mock_page.locator.return_value = toggle

    with patch.object(controller, "_supports_google_search", return_value=True):
        await controller._adjust_google_search(
            request_params, "gemini-flash", mock_check_disconnect
        )

    # Should log warning about failed update
    toggle.click.assert_called_once()


@pytest.mark.asyncio
async def test_supports_google_search_gemini20(controller):
    """Test _supports_google_search returns False for Gemini 2.0."""
    assert controller._supports_google_search("gemini-2.0-flash") is False
    assert controller._supports_google_search("gemini2.0-flash-exp") is False


@pytest.mark.asyncio
async def test_supports_google_search_other_models(controller):
    """Test _supports_google_search returns True for other models."""
    assert controller._supports_google_search("gemini-2.5-flash") is True
    assert controller._supports_google_search("gemini-3-pro") is True
    assert controller._supports_google_search(None) is True
