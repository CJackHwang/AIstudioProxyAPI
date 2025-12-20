import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

# Mock server module before importing model_management components if needed
# But we already imported them. Let's patch where necessary.
from browser_utils.model_management import (
    _force_ui_state_settings,
    _force_ui_state_with_retry,
    _handle_initial_model_state_and_storage,
    _set_model_from_page_display,
    _verify_and_apply_ui_state,
    _verify_ui_state_settings,
    load_excluded_models,
    switch_ai_studio_model,
)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    # locator is synchronous in Playwright
    page.locator = MagicMock()
    # Default evaluate returns None (empty localStorage)
    page.evaluate.return_value = None
    return page


@pytest.fixture
def mock_server():
    mock = MagicMock()
    mock.processing_lock = MagicMock()
    mock.processing_lock.__aenter__ = AsyncMock(return_value=None)
    mock.processing_lock.__aexit__ = AsyncMock(return_value=None)
    mock.excluded_model_ids = set()
    mock.current_ai_studio_model_id = "initial-model"
    mock.parsed_model_list = []
    # Use AsyncMock for async event, not MagicMock
    mock.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock.model_list_fetch_event.is_set.return_value = True
    return mock


@pytest.mark.asyncio
@pytest.mark.timeout(5)
@pytest.mark.parametrize(
    "evaluate_result,evaluate_side_effect,expected_exists,expected_needs_update,expected_advanced,expected_tools,expected_error_contains,test_id",
    [
        (
            json.dumps({"isAdvancedOpen": True, "areToolsOpen": True}),
            None,
            True,
            False,
            True,
            True,
            None,
            "valid",
        ),
        (
            json.dumps({"isAdvancedOpen": False, "areToolsOpen": True}),
            None,
            True,
            True,
            None,
            None,
            None,
            "needs_update",
        ),
        (None, None, False, True, None, None, "localStorage不存在", "missing"),
        ("invalid-json", None, False, True, None, None, "JSON解析失败", "json_error"),
        (
            None,
            Exception("Eval Error"),
            False,
            True,
            None,
            None,
            "验证失败",
            "eval_error",
        ),
    ],
)
async def test_verify_ui_state_settings(
    mock_page,
    evaluate_result,
    evaluate_side_effect,
    expected_exists,
    expected_needs_update,
    expected_advanced,
    expected_tools,
    expected_error_contains,
    test_id,
):
    """Test UI state settings verification with various scenarios."""
    if evaluate_side_effect:
        mock_page.evaluate.side_effect = evaluate_side_effect
    else:
        mock_page.evaluate.return_value = evaluate_result

    with patch("browser_utils.models.ui_state.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is expected_exists
    assert result["needsUpdate"] is expected_needs_update

    if expected_advanced is not None:
        assert result["isAdvancedOpen"] is expected_advanced
    if expected_tools is not None:
        assert result["areToolsOpen"] is expected_tools
    if expected_error_contains:
        assert expected_error_contains in result["error"]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_success(mock_page):
    # Initial state: needs update
    initial_prefs = {"isAdvancedOpen": False}

    with (
        patch("browser_utils.models.ui_state._verify_ui_state_settings") as mock_verify,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_verify.side_effect = [
            {"needsUpdate": True, "prefs": initial_prefs},  # First call
            {"needsUpdate": False},  # Second call
        ]

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is True
        # Check if setItem was called
        assert mock_page.evaluate.call_count == 1
        args = mock_page.evaluate.call_args[0]
        assert "localStorage.setItem" in args[0]
        # Check if prefs were updated to True
        saved_prefs = json.loads(args[1])
        assert saved_prefs["isAdvancedOpen"] is True
        assert saved_prefs["areToolsOpen"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_no_update_needed(mock_page):
    with (
        patch("browser_utils.models.ui_state._verify_ui_state_settings") as mock_verify,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_verify.return_value = {"needsUpdate": False}

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is True
        mock_page.evaluate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_fail_verify(mock_page):
    with (
        patch("browser_utils.models.ui_state._verify_ui_state_settings") as mock_verify,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_verify.side_effect = [
            {"needsUpdate": True, "prefs": {}},
            {"needsUpdate": True},  # Still needs update after set
        ]

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is False
        mock_page.evaluate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_with_retry_success(mock_page):
    with (
        patch("browser_utils.models.ui_state._force_ui_state_settings") as mock_force,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_force.side_effect = [False, True]  # Fail first, succeed second

        result = await _force_ui_state_with_retry(
            mock_page, "req1", max_retries=3, retry_delay=0.01
        )

        assert result is True
        assert mock_force.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_with_retry_fail(mock_page):
    with (
        patch("browser_utils.models.ui_state._force_ui_state_settings") as mock_force,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_force.return_value = False

        result = await _force_ui_state_with_retry(
            mock_page, "req1", max_retries=2, retry_delay=0.01
        )

        assert result is False
        assert mock_force.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_and_apply_ui_state_needs_update(mock_page):
    with (
        patch("browser_utils.models.ui_state._verify_ui_state_settings") as mock_verify,
        patch("browser_utils.models.ui_state._force_ui_state_with_retry") as mock_retry,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_verify.return_value = {
            "exists": True,
            "isAdvancedOpen": False,
            "areToolsOpen": False,
            "needsUpdate": True,
        }
        mock_retry.return_value = True

        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True
        mock_retry.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_and_apply_ui_state_ok(mock_page):
    with (
        patch("browser_utils.models.ui_state._verify_ui_state_settings") as mock_verify,
        patch("browser_utils.models.ui_state._force_ui_state_with_retry") as mock_retry,
        patch("browser_utils.models.ui_state.logger"),
    ):
        mock_verify.return_value = {
            "exists": True,
            "isAdvancedOpen": True,
            "areToolsOpen": True,
            "needsUpdate": False,
        }

        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True
        mock_retry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_load_excluded_models(tmp_path):
    # Create a dummy exclusion file
    d = tmp_path / "config"
    d.mkdir()
    p = d / "excluded_models.txt"
    p.write_text("model-a\nmodel-b\n", encoding="utf-8")

    # Mock server state
    mock_state = MagicMock()
    mock_state.excluded_model_ids = set()

    with (
        patch("api_utils.server_state.state", mock_state),
        patch("os.path.exists") as mock_exists,
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch("browser_utils.models.switcher.logger"),
    ):
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.__enter__.return_value = ["model-a\n", "model-b\n"]
        mock_open.return_value = mock_file

        load_excluded_models("excluded_models.txt")

        assert "model-a" in mock_state.excluded_model_ids
        assert "model-b" in mock_state.excluded_model_ids


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_already_set(mock_page):
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    prefs = {"promptModel": full_model_path}

    mock_page.evaluate.return_value = json.dumps(prefs)
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    with (
        patch("browser_utils.models.switcher.logger"),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

    assert result is True
    # Should not navigate if already on new_chat
    mock_page.goto.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_success(mock_page):
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"

    initial_prefs = {"promptModel": "models/other-model"}

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.logger"),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Stateful evaluate mock
        evaluate_mock = AsyncMock()
        mock_page.evaluate = evaluate_mock

        call_count = 0

        async def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check
                    return json.dumps(initial_prefs)
                if call_count == 2:  # Final verification
                    return json.dumps({"promptModel": full_model_path})
            return None

        evaluate_mock.side_effect = evaluate_side_effect

        # Mock page elements
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(
            return_value=model_id
        )  # Matches target
        mock_page.locator.return_value = mock_locator

        # Mock incognito button
        mock_incognito = MagicMock()
        mock_incognito.get_attribute = AsyncMock(return_value="ms-button-active")

        def locator_side_effect(selector):
            if 'data-test-id="model-name"' in selector:
                return mock_locator
            if "Temporary chat toggle" in selector:
                return mock_incognito
            return MagicMock()

        mock_page.locator.side_effect = locator_side_effect

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        assert result is True
        mock_page.goto.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display(mock_page):
    # Mock server state
    mock_state = MagicMock()
    mock_state.current_ai_studio_model_id = "old-model"

    # CRITICAL: Use AsyncMock for async event, not MagicMock
    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set.return_value = True  # Event is already set, no wait needed
    mock_state.model_list_fetch_event = mock_event
    mock_state.parsed_model_list = []

    # Mock locator
    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new-model")
    mock_page.locator.return_value = mock_locator

    with (
        patch("api_utils.server_state.state", mock_state),
        patch("browser_utils.models.startup.logger"),
    ):
        await _set_model_from_page_display(mock_page, set_storage=False)

    assert mock_state.current_ai_studio_model_id == "new-model"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_needs_reload(mock_page):
    # Mock empty localStorage -> needs reload
    mock_page.evaluate.return_value = None
    mock_page.url = "http://test.url"

    # Mock server
    mock_server = MagicMock()

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._set_model_from_page_display"
        ) as mock_set_model,
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.logger"),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        # Should call _set_model_from_page_display twice
        assert mock_set_model.call_count == 2
        assert mock_set_model.call_args_list[0][1]["set_storage"] is True
        assert mock_set_model.call_args_list[1][1]["set_storage"] is False

        # Should reload page
        mock_page.goto.assert_called_with(
            "http://test.url", wait_until="domcontentloaded", timeout=40000
        )


@pytest.mark.asyncio
async def test_switch_ai_studio_model_revert_logic(mock_page):
    """Test the revert logic when model switch fails validation."""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    initial_prefs = {"promptModel": "models/original-model"}
    original_prefs_str = json.dumps(initial_prefs)

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.logger"),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Setup stateful evaluate mock to simulate storage state changes
        call_count = 0

        async def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check
                    return original_prefs_str
                elif call_count == 2:  # Final verification (switched)
                    return json.dumps({"promptModel": full_model_path})
                elif call_count == 3:  # Revert logic
                    return json.dumps({"promptModel": full_model_path})
            return None

        mock_page.evaluate = AsyncMock(side_effect=evaluate_side_effect)

        # Simulate mismatch: page displays "Original Model" but storage has new model
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(return_value="Original Model")
        mock_page.locator.return_value = mock_locator

        # Execute - should fail validation and trigger revert
        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        # Verify revert occurred
        assert result is False

        # Check setItem calls for revert
        set_item_calls = [
            args
            for args in mock_page.evaluate.call_args_list
            if "localStorage.setItem" in args[0][0]
        ]

        # Verify revert prefs were set (target, compat, revert)
        assert len(set_item_calls) >= 3
        last_set_call = set_item_calls[-1]
        revert_prefs = json.loads(last_set_call[0][1])
        assert revert_prefs["promptModel"] == "models/Original Model"
        assert revert_prefs["isAdvancedOpen"] is True
        assert revert_prefs["areToolsOpen"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_incognito_toggle(mock_page):
    """Test incognito toggle logic when model switch succeeds"""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.logger"),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Mock evaluate for success path
        # It needs to return a DIFFERENT model initially so it doesn't return early
        call_count = 0

        def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check -> return old model
                    return json.dumps({"promptModel": "models/old-model"})
                if call_count == 2:  # Final verification -> return new model
                    return json.dumps({"promptModel": full_model_path})
            return None

        mock_page.evaluate.side_effect = evaluate_side_effect

        # Mock page elements
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(return_value=model_id)

        # Mock incognito button - INACTIVE initially
        mock_incognito = MagicMock()
        mock_incognito.wait_for = AsyncMock()
        mock_incognito.click = AsyncMock()
        # First check returns inactive, second check (after click) returns active
        mock_incognito.get_attribute = AsyncMock(
            side_effect=[
                "ms-button",  # inactive
                "ms-button-active ms-button",  # active
            ]
        )

        def locator_side_effect(selector):
            if 'data-test-id="model-name"' in selector:
                return mock_locator
            if "Temporary chat toggle" in selector:
                return mock_incognito
            return MagicMock()

        mock_page.locator.side_effect = locator_side_effect

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        assert result is True
        mock_incognito.click.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_exception_handling_coverage(mock_page):
    """Cover exception handlers in various functions"""

    # 1. _force_ui_state_settings exception
    with (
        patch(
            "browser_utils.models.ui_state._verify_ui_state_settings",
            side_effect=Exception("Force Error"),
        ),
        patch("browser_utils.models.ui_state.logger"),
    ):
        assert await _force_ui_state_settings(mock_page) is False

    # 2. _verify_and_apply_ui_state exception
    with (
        patch(
            "browser_utils.models.ui_state._verify_ui_state_settings",
            side_effect=Exception("Verify Apply Error"),
        ),
        patch("browser_utils.models.ui_state.logger"),
    ):
        assert await _verify_and_apply_ui_state(mock_page) is False

    # 3. switch_ai_studio_model JSON decode error is tested in test_handle_initial_model_state_exceptions
    # The JSONDecodeError handler falls back to empty prefs and continues execution


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_nav_only(mock_page):
    """Test navigation when model already matches but URL is wrong"""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    prefs = {"promptModel": full_model_path}

    mock_page.evaluate.return_value = json.dumps(prefs)
    mock_page.url = "https://other.url"  # Not new_chat

    with (
        patch("browser_utils.models.switcher.logger"),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

    assert result is True
    # Should navigate
    mock_page.goto.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_load_excluded_models_edge_cases(tmp_path):
    """Test edge cases for load_excluded_models"""
    # 1. File does not exist
    # Mock server module - use api_utils.server_state.state which is what the implementation uses
    mock_state = MagicMock()
    mock_state.excluded_model_ids = set()

    with (
        patch("api_utils.server_state.state", mock_state),
        patch("browser_utils.models.switcher.logger") as mock_logger,
    ):
        load_excluded_models("non_existent.txt")
        # Implementation uses logger.debug, not logger.info
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        assert any("未找到" in msg for msg in debug_calls)

    # 2. File exists but is empty - tested in the next block with mocked file I/O

    # Let's mock os.path.exists/open for easier testing of logic
    with (
        patch("api_utils.server_state.state", mock_state),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch("browser_utils.models.switcher.logger") as mock_logger,
    ):
        # Empty file
        mock_file = MagicMock()
        mock_file.__enter__.return_value = []  # Empty lines
        mock_open.return_value = mock_file

        load_excluded_models("empty.txt")
        # Implementation uses logger.debug
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        assert any("文件为空" in msg for msg in debug_calls)

    # 3. Exception
    with (
        patch("api_utils.server_state.state", mock_state),
        patch("os.path.exists", side_effect=Exception("Disk Error")),
        patch("browser_utils.models.switcher.logger") as mock_logger,
    ):
        load_excluded_models("error.txt")
        assert mock_logger.error.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_exceptions(mock_page):
    """Test exception handling in _handle_initial_model_state_and_storage"""
    mock_server = MagicMock()

    # 1. JSON Decode Error
    mock_page.evaluate.return_value = "invalid-json"

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._set_model_from_page_display"
        ) as mock_set_model,
        patch("browser_utils.models.startup.logger") as mock_logger,
    ):
        # Should trigger reload path due to JSON error
        # We'll mock _set_model_from_page_display to raise Exception to test the outer try/except
        mock_set_model.side_effect = Exception("Inner Error")

        await _handle_initial_model_state_and_storage(mock_page)

        # Verify error log
        # Check that we have the catastrophic error log
        # It catches "Inner Error" in the outer except block
        error_calls = [args[0][0] for args in mock_logger.error.call_args_list]
        assert any("严重错误" in msg for msg in error_calls)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_reload_retry_logic(mock_page):
    """Test reload retry logic"""
    mock_server = MagicMock()
    mock_page.evaluate.return_value = None  # Trigger reload

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._set_model_from_page_display"
        ) as mock_set_model,
        patch("browser_utils.models.startup.logger"),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Mock goto to fail twice then succeed
        mock_page.goto.side_effect = [Exception("Fail 1"), Exception("Fail 2"), None]

        await _handle_initial_model_state_and_storage(mock_page)

        assert mock_page.goto.call_count == 3
        # Should eventually succeed and call set_model twice (start and end)
        assert mock_set_model.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_timeout(mock_page):
    """Test timeout when waiting for model list"""
    mock_state = MagicMock()
    mock_state.current_ai_studio_model_id = None
    mock_state.parsed_model_list = []

    # Use AsyncMock for async event
    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set.return_value = False  # Event not set, will wait
    mock_state.model_list_fetch_event = mock_event

    # Mock locator
    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="displayed-model")
    mock_page.locator.return_value = mock_locator

    with (
        patch("api_utils.server_state.state", mock_state),
        patch("browser_utils.models.startup.logger") as mock_logger,
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        await _set_model_from_page_display(mock_page, set_storage=False)

        # Should log warning about timeout
        assert any(
            "等待模型列表超时" in str(arg)
            for arg in mock_logger.warning.call_args_list[0][0]
        )
        # Should still update global ID using display name as fallback
        assert mock_state.current_ai_studio_model_id == "displayed-model"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_storage_logic(mock_page):
    """Test storage update logic in _set_model_from_page_display"""
    mock_state = MagicMock()
    mock_state.current_ai_studio_model_id = "old"
    # Create a set event to avoid hanging on wait()
    mock_event = asyncio.Event()
    mock_event.set()
    mock_state.model_list_fetch_event = mock_event
    mock_state.parsed_model_list = []

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new-model")
    mock_page.locator.return_value = mock_locator

    # Mock existing prefs
    existing_prefs = {"someKey": "someVal"}
    mock_page.evaluate.return_value = json.dumps(existing_prefs)

    with (
        patch("api_utils.server_state.state", mock_state),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.logger"),
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Check that setItem was called with updated prefs
        assert mock_page.evaluate.call_count == 2  # getItem, setItem

        # Verify setItem args
        set_call = mock_page.evaluate.call_args_list[1]
        assert "localStorage.setItem" in set_call[0][0]
        saved_prefs = json.loads(set_call[0][1])

        assert saved_prefs["isAdvancedOpen"] is True
        assert saved_prefs["promptModel"] == "models/new-model"
        # Check default keys added
        assert "bidiModel" in saved_prefs


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_catastrophic_error(mock_page):
    """Test top-level exception handling in switch_ai_studio_model"""
    # Force an error immediately
    mock_page.evaluate.side_effect = Exception("Catastrophic Failure")

    with (
        patch("browser_utils.models.switcher.logger") as mock_logger,
        patch(
            "browser_utils.operations.save_error_snapshot", new_callable=AsyncMock
        ) as mock_snapshot,
    ):
        result = await switch_ai_studio_model(mock_page, "model-id", "req1")

        assert result is False
        mock_snapshot.assert_called()
        assert mock_logger.exception.called


# ============================================================================
# EXTENDED COVERAGE - Edge Cases, Error Handling, Revert Logic
# ============================================================================

# === Section 1: UI State Verification Tests ===


@pytest.mark.asyncio
async def test_verify_ui_state_missing_storage(mock_page):
    """Test verification when localStorage item is missing."""
    mock_page.evaluate.return_value = None

    result = await _verify_ui_state_settings(mock_page)

    assert result["exists"] is False
    assert result["error"] == "localStorage不存在"
    assert result["needsUpdate"] is True


@pytest.mark.asyncio
async def test_verify_ui_state_json_error(mock_page):
    """Test verification with invalid JSON in storage."""
    mock_page.evaluate.return_value = "invalid json"

    result = await _verify_ui_state_settings(mock_page)

    assert result["exists"] is False
    assert "JSON解析失败" in result["error"]
    assert result["needsUpdate"] is True


@pytest.mark.asyncio
async def test_verify_ui_state_exception(mock_page):
    """Test verification when evaluate raises exception."""
    mock_page.evaluate.side_effect = Exception("Page error")

    result = await _verify_ui_state_settings(mock_page)

    assert result["exists"] is False
    assert "验证失败" in result["error"]
    assert result["needsUpdate"] is True


# === Section 2: Force UI State Tests ===


@pytest.mark.asyncio
async def test_force_ui_state_already_correct(mock_page):
    """Test force update when state is already correct."""
    mock_page.evaluate.return_value = json.dumps(
        {"isAdvancedOpen": True, "areToolsOpen": True}
    )

    result = await _force_ui_state_settings(mock_page)

    assert result is True
    assert mock_page.evaluate.call_count == 1


@pytest.mark.asyncio
async def test_force_ui_state_verify_failure(mock_page):
    """Test force update when verification fails after setting."""
    initial_state = json.dumps({"isAdvancedOpen": False})
    final_state = json.dumps({"isAdvancedOpen": False})  # Still wrong

    mock_page.evaluate.side_effect = [
        initial_state,  # verify 1
        None,  # setItem
        final_state,  # verify 2
    ]

    result = await _force_ui_state_settings(mock_page)

    assert result is False


@pytest.mark.asyncio
async def test_force_ui_state_exception(mock_page):
    """Test force update exception handling."""
    mock_page.evaluate.side_effect = Exception("Set error")

    result = await _force_ui_state_settings(mock_page)

    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_exception_via_verify(mock_page):
    """Test exception handling in _force_ui_state_settings via verify."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        side_effect=Exception("Test Error"),
    ):
        result = await _force_ui_state_settings(mock_page, "req1")
        assert result is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mock_force_side_effect,mock_force_return_value,max_retries,retry_delay,expected_result,expected_call_count,test_id",
    [
        ([False, True], None, 3, None, True, 2, "success"),
        (None, False, 2, 0.01, False, 2, "failure"),
    ],
)
async def test_force_ui_state_retry(
    mock_page,
    mock_force_side_effect,
    mock_force_return_value,
    max_retries,
    retry_delay,
    expected_result,
    expected_call_count,
    test_id,
):
    """Test retry logic for forcing UI state settings (eventually succeeding or failing all attempts)."""
    with patch("browser_utils.models.ui_state._force_ui_state_settings") as mock_force:
        if mock_force_side_effect:
            mock_force.side_effect = mock_force_side_effect
        else:
            mock_force.return_value = mock_force_return_value

        kwargs = {"max_retries": max_retries}
        if retry_delay is not None:
            kwargs["retry_delay"] = retry_delay

        result = await _force_ui_state_with_retry(mock_page, **kwargs)

        assert result is expected_result
        assert mock_force.call_count == expected_call_count


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_and_apply_ui_state_exception(mock_page):
    """Test exception handling in _verify_and_apply_ui_state."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        side_effect=Exception("Test Error"),
    ):
        result = await _verify_and_apply_ui_state(mock_page, "req1")
        assert result is False


# === Section 3: Load Excluded Models Tests ===


@pytest.mark.asyncio
async def test_load_excluded_models_success(mock_server):
    """Test loading excluded models from file."""
    mock_content = "model-1\nmodel-2\n"

    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_content.splitlines()

    with (
        patch("builtins.open", return_value=mock_file),
        patch("os.path.exists", return_value=True),
        patch.dict(sys.modules, {"server": mock_server}),
    ):
        load_excluded_models("excluded.txt")

        assert "model-1" in mock_server.excluded_model_ids
        assert "model-2" in mock_server.excluded_model_ids


# === Section 4: Handle Initial Model State Tests ===


@pytest.mark.asyncio
async def test_handle_initial_state_missing_storage(mock_page, mock_server):
    """Test handling initial state when storage is missing."""
    mock_page.evaluate.return_value = None  # No storage
    mock_page.url = "http://test.url"

    with (
        patch(
            "browser_utils.models.startup._set_model_from_page_display"
        ) as mock_set_model,
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect_async,
    ):
        mock_expect = MagicMock()
        mock_expect.to_be_visible = AsyncMock()
        mock_expect_async.return_value = mock_expect

        await _handle_initial_model_state_and_storage(mock_page)

        assert mock_set_model.call_count == 2
        assert mock_page.goto.call_count == 1


@pytest.mark.asyncio
async def test_handle_initial_state_valid_no_reload(mock_page, mock_server):
    """Test handling initial state when everything is valid."""
    mock_page.evaluate.return_value = json.dumps(
        {"promptModel": "models/valid-model", "isAdvancedOpen": True}
    )

    with patch("browser_utils.models.startup._verify_ui_state_settings") as mock_verify:
        mock_verify.return_value = {"needsUpdate": False}

        with patch.dict(sys.modules, {"server": mock_server}):
            await _handle_initial_model_state_and_storage(mock_page)

            mock_page.goto.assert_not_called()
            assert mock_server.current_ai_studio_model_id == "valid-model"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_and_storage_success(mock_page, mock_server):
    """Test successful initial model state handling."""
    initial_prefs = json.dumps(
        {
            "promptModel": "models/gemini-pro",
            "isAdvancedOpen": True,
            "areToolsOpen": True,
        }
    )
    mock_page.evaluate.return_value = initial_prefs

    with (
        patch(
            "browser_utils.models.startup._verify_ui_state_settings",
            return_value={"needsUpdate": False},
        ),
        patch.dict("sys.modules", {"server": mock_server}),
    ):
        await _handle_initial_model_state_and_storage(mock_page)

        assert mock_server.current_ai_studio_model_id == "gemini-pro"
        mock_page.goto.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_exception(mock_page):
    """Test exception handling in _handle_initial_model_state_and_storage."""
    mock_page.evaluate.side_effect = Exception("Init Error")

    with patch(
        "browser_utils.models.startup._set_model_from_page_display"
    ) as mock_fallback:
        await _handle_initial_model_state_and_storage(mock_page)

        mock_fallback.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_json_error(mock_page, mock_server):
    """Test JSON error handling in initial state check."""
    mock_page.evaluate.return_value = "invalid-json"

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.models.startup.logger") as mock_logger,
        patch(
            "browser_utils.models.startup._set_model_from_page_display"
        ) as mock_set_model,
        patch("browser_utils.models.startup.expect_async") as mock_expect,
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        mock_set_model.assert_called()
        errors = [call.args[0] for call in mock_logger.error.call_args_list]
        assert any(
            "解析 localStorage.aiStudioUserPreference JSON 失败" in e for e in errors
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_reload_retry(mock_page, mock_server):
    """Test reload retry logic."""
    mock_page.evaluate.return_value = None  # Trigger reload

    mock_page.goto.side_effect = [Exception("Load failed"), None]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.models.startup.logger") as mock_logger,
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        assert mock_page.goto.call_count == 2
        warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert any("页面重新加载尝试 1/3 失败" in w for w in warnings)


# === Section 5: Set Model from Page Display Tests ===


@pytest.mark.asyncio
async def test_set_model_from_display_basic(mock_page, mock_server):
    """Test setting model from page display."""
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "displayed-model"

    mock_locator = AsyncMock()
    mock_locator.first = mock_element

    mock_page.locator.return_value = mock_locator

    mock_server.current_ai_studio_model_id = "old-model"

    with patch.dict(sys.modules, {"server": mock_server}):
        await _set_model_from_page_display(mock_page, set_storage=False)

        assert mock_server.current_ai_studio_model_id == "displayed-model"
        assert mock_page.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_set_model_from_display_with_storage(mock_page, mock_server):
    """Test setting model from page display and updating storage."""
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "displayed-model"

    mock_locator = AsyncMock()
    mock_locator.first = mock_element
    mock_page.locator.return_value = mock_locator

    mock_page.evaluate.return_value = json.dumps({})

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        assert any(
            "setItem" in str(args) for args, _ in mock_page.evaluate.call_args_list
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_success(mock_page, mock_server):
    """Test _set_model_from_page_display success."""
    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "gemini-ultra"
    type(mock_locator).first = PropertyMock(return_value=mock_element)
    mock_page.locator.return_value = mock_locator

    with (
        patch.dict("sys.modules", {"server": mock_server}),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        assert mock_server.current_ai_studio_model_id == "gemini-ultra"
        assert mock_page.evaluate.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_set_storage_defaults(mock_page, mock_server):
    """Test set_storage=True logic with default keys."""
    mock_page.locator.return_value.first.inner_text = AsyncMock(
        return_value="gemini-pro"
    )
    mock_page.evaluate.return_value = None  # No existing prefs

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        args = mock_page.evaluate.call_args[0]
        assert "localStorage.setItem" in args[0]
        prefs = json.loads(args[1])
        assert prefs["isAdvancedOpen"] is True
        assert prefs["promptModel"] == "models/gemini-pro"
        assert prefs["getCodeLanguage"] == "Node.js"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_same_id(mock_page):
    """Test when displayed ID matches current server ID.

    Implementation note: When model ID is unchanged, no log is emitted (line 175 comment).
    We verify the ID remains unchanged and no update occurs.
    """
    mock_state = MagicMock()
    mock_state.current_ai_studio_model_id = "gemini-pro"
    mock_state.parsed_model_list = []
    mock_event = asyncio.Event()
    mock_event.set()  # Already set
    mock_state.model_list_fetch_event = mock_event

    mock_page.locator.return_value.first.inner_text = AsyncMock(
        return_value="gemini-pro"
    )

    with (
        patch("api_utils.server_state.state", mock_state),
        patch("browser_utils.models.startup.logger") as mock_logger,
    ):
        await _set_model_from_page_display(mock_page)

        # Model ID should not have changed
        assert mock_state.current_ai_studio_model_id == "gemini-pro"
        # Implementation doesn't log when unchanged, so just verify debug was called for reading
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        assert any("gemini-pro" in msg for msg in debug_calls)


# === Section 6: Switch Model Tests ===


@pytest.mark.asyncio
async def test_switch_model_recovery_logic(mock_page):
    """Test switch model failure triggering recovery logic."""
    req_id = "test_req"
    model_id = "new-model"

    mock_page.evaluate.return_value = json.dumps({"promptModel": "models/old-model"})
    mock_page.url = "http://example.com"

    mock_locator = AsyncMock()
    mock_locator.first.inner_text.return_value = "old-model"
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "server.parsed_model_list",
            [{"id": "old-model", "display_name": "Old Model"}],
        ),
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
    ):
        result = await switch_ai_studio_model(mock_page, model_id, req_id)

        found_revert = False
        for call in mock_page.evaluate.call_args_list:
            args, _ = call
            if len(args) > 1 and "models/old-model" in str(args[1]):
                found_revert = True
                break

        assert found_revert
        assert result is False


@pytest.mark.asyncio
async def test_switch_model_json_error_original(mock_page):
    """Test switch model when original prefs are invalid JSON."""
    mock_page.evaluate.return_value = "invalid json"

    mock_locator = AsyncMock()
    mock_locator.first.inner_text.return_value = "unknown-model"
    mock_page.locator.return_value = mock_locator

    with patch(
        "browser_utils.models.switcher._verify_and_apply_ui_state", return_value=True
    ):
        result = await switch_ai_studio_model(mock_page, "new-model", "req_id")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_already_set_nav_needed(mock_page):
    """Test when model is already set in storage but URL is wrong."""
    mock_page.evaluate.return_value = json.dumps({"promptModel": "models/target-model"})
    mock_page.url = "http://wrong.url"

    mock_locator = AsyncMock()
    mock_locator.first.inner_text.return_value = "target-model"

    mock_incognito = AsyncMock()
    mock_incognito.get_attribute.return_value = ["ms-button-active"]

    def locator_side_effect(selector):
        if "model-name" in selector:
            return mock_locator
        if "Temporary chat toggle" in selector:
            return mock_incognito
        return AsyncMock()

    mock_page.locator.side_effect = locator_side_effect

    mock_expect = MagicMock()
    mock_expect.to_be_visible = AsyncMock()

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async", return_value=mock_expect),
    ):
        result = await switch_ai_studio_model(mock_page, "target-model", "req_id")

    assert result is True
    mock_page.goto.assert_called()


@pytest.mark.asyncio
async def test_switch_model_success_flow(mock_page, mock_server):
    """Test full success flow: not set -> set -> navigate -> verify -> success."""
    req_id = "test_req"
    model_id = "target-model"

    initial_state = json.dumps({"promptModel": "models/old-model"})
    final_state = json.dumps({"promptModel": "models/target-model"})

    mock_page.evaluate.side_effect = [
        initial_state,  # 1. get initial
        None,  # 2. set item
        None,  # 3. set item (compat)
        final_state,  # 4. get final
        initial_state,  # 5. get revert (if failure)
        None,  # 6. set revert
    ]

    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "target-model"

    mock_locator = AsyncMock()
    mock_locator.first = mock_element

    mock_incognito = AsyncMock()
    mock_incognito.get_attribute.return_value = "ms-button-active custom-class"
    mock_incognito.wait_for.return_value = None
    mock_incognito.click.return_value = None

    def locator_side_effect(selector):
        if "model-name" in selector:
            return mock_locator
        if "Temporary chat toggle" in selector:
            return mock_incognito
        return AsyncMock()

    mock_page.locator.side_effect = locator_side_effect

    mock_expect = MagicMock()
    mock_expect.to_be_visible = AsyncMock()

    mock_server.parsed_model_list = [
        {"id": "target-model", "display_name": "Target Model"}
    ]

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async", return_value=mock_expect),
        patch.dict(sys.modules, {"server": mock_server}),
    ):
        result = await switch_ai_studio_model(mock_page, model_id, req_id)

    assert result is True
    mock_page.goto.assert_called()
    assert any("setItem" in str(args) for args, _ in mock_page.evaluate.call_args_list)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_json_error_original_prefs(mock_page):
    """Test JSONDecodeError when parsing original prefs."""
    mock_page.evaluate.side_effect = [
        "invalid-json",  # 1. original
        None,  # 2. set promptModel
        None,  # 3. set UI state manual
        json.dumps({"promptModel": "models/target-model"}),  # 4. final
    ]
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "target-model"
    type(mock_locator).first = PropertyMock(return_value=mock_element)
    mock_page.locator.return_value = mock_locator

    mock_locator.get_attribute = AsyncMock(return_value=["ms-button-active"])

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "target-model", "req1")

        assert result is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_json_error_final_prefs(mock_page):
    """Test JSONDecodeError when parsing final prefs."""
    initial_prefs = json.dumps({"promptModel": "models/old-model"})

    mock_page.evaluate.side_effect = [
        initial_prefs,  # 1
        None,  # 2
        None,  # 3
        "invalid-json",  # 4 (final check -> fails)
        initial_prefs,  # 5 (revert: read current LS)
        None,  # 6 (revert: write LS)
    ]
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "target-model"
    type(mock_locator).first = PropertyMock(return_value=mock_element)

    mock_incognito = MagicMock()
    mock_incognito.wait_for = AsyncMock()
    mock_incognito.get_attribute = AsyncMock(return_value=["ms-button-active"])
    mock_incognito.click = AsyncMock()

    def locator_side_effect(selector):
        if "model-name" in selector:
            return mock_locator
        if "Temporary chat toggle" in selector:
            return mock_incognito
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "target-model", "req1")

        assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_read_model_name_exception(mock_page):
    """Test exception when reading displayed model name."""
    initial_prefs = json.dumps({"promptModel": "models/old-model"})

    mock_page.evaluate.side_effect = [
        initial_prefs,
        None,
        None,
        json.dumps({"promptModel": "models/target-model"}),
        None,  # Revert to original
    ]
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.side_effect = Exception("Read Error")
    type(mock_locator).first = PropertyMock(return_value=mock_element)

    def locator_side_effect(selector):
        if "model-name" in selector:
            return mock_locator
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "target-model", "req1")

        assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_incognito_retry(mock_page):
    """Test retrying to enable incognito mode."""
    initial_prefs = json.dumps({"promptModel": "models/old-model"})
    mock_page.evaluate.side_effect = [
        initial_prefs,
        None,
        None,
        json.dumps({"promptModel": "models/target-model"}),
    ]
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "target-model"
    type(mock_locator).first = PropertyMock(return_value=mock_element)

    mock_incognito = MagicMock()
    mock_incognito.wait_for = AsyncMock()
    mock_incognito.get_attribute = AsyncMock(side_effect=[[], ["ms-button-active"]])
    mock_incognito.click = AsyncMock()

    def locator_side_effect(selector):
        if "model-name" in selector:
            return mock_locator
        if "Temporary chat toggle" in selector:
            return mock_incognito
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "target-model", "req1")

        assert result is True
        assert mock_incognito.click.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_revert_cant_read_display(mock_page):
    """Test revert flow when display name cannot be read."""
    initial_prefs = json.dumps({"promptModel": "models/original-model"})

    mock_page.evaluate.side_effect = [
        initial_prefs,  # 1
        None,  # 2
        None,  # 3
        json.dumps({"promptModel": "models/target-model"}),  # 4
        None,  # 5
    ]
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "wrong-model"
    type(mock_locator).first = PropertyMock(return_value=mock_element)

    mock_revert_locator = MagicMock()
    mock_revert_element = AsyncMock()
    mock_revert_element.inner_text.side_effect = Exception("Revert Read Error")
    type(mock_revert_locator).first = PropertyMock(return_value=mock_revert_element)

    locators = iter([mock_locator, mock_revert_locator])

    def locator_side_effect(selector):
        if "model-name" in selector:
            return next(locators)
        return MagicMock()

    mock_page.locator.side_effect = locator_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "target-model", "req1")

        assert result is False
        set_calls = [
            args
            for args, _ in mock_page.evaluate.call_args_list
            if "setItem" in str(args)
        ]
        last_set_arg = set_calls[-1][1]
        assert "original-model" in last_set_arg


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_general_exception(mock_page):
    """Test general exception handling in switch_ai_studio_model."""
    mock_page.evaluate.side_effect = Exception("Catastrophic Failure")

    result = await switch_ai_studio_model(mock_page, "target-model", "req1")

    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_json_error_logging(mock_page):
    """Test handling of JSONDecodeError in original prefs with logging."""
    mock_page.evaluate.side_effect = [
        "invalid-json",  # original_prefs_str
        None,  # setItem 1
        None,  # setItem 2
        None,  # final_prefs_str (check)
        None,  # check for revert (current_ls_content_str)
    ]

    with (
        patch("browser_utils.models.switcher.logger") as mock_logger,
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        mock_page.locator.return_value.first.inner_text = AsyncMock(
            return_value="Different Model"
        )

        await switch_ai_studio_model(mock_page, "gemini-pro", "req1")

        warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert any(
            "无法解析原始的 aiStudioUserPreference JSON 字符串" in w for w in warnings
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_ui_state_fail(mock_page):
    """Test warning when UI state verification fails but process continues."""
    mock_page.evaluate.return_value = json.dumps({"promptModel": "models/old-model"})

    with (
        patch("browser_utils.models.switcher.logger") as mock_logger,
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=False,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_page.locator.return_value.first.inner_text = AsyncMock(
            return_value="gemini-pro"
        )

        await switch_ai_studio_model(mock_page, "gemini-pro", "req1")

        warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert any("UI状态设置失败，但继续执行" in w for w in warnings)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_final_storage_mismatch(mock_page):
    """Test error when final storage does not match target model."""
    mock_page.evaluate.side_effect = [
        json.dumps({"promptModel": "models/old-model"}),  # 1. Get original
        None,  # 2. Set item 1
        None,  # 3. Set item 2
        json.dumps({"promptModel": "models/old-model"}),  # 4. Get final (still old)
        None,  # 5. Set item (revert)
        json.dumps({"promptModel": "models/old-model"}),  # 6. Get item (revert logic)
        None,  # 7. Set item (revert)
    ]

    with (
        patch("browser_utils.models.switcher.logger") as mock_logger,
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_page.locator.return_value.first.inner_text = AsyncMock(
            return_value="gemini-pro"
        )

        await switch_ai_studio_model(mock_page, "gemini-pro", "req1")

        errors = [call.args[0] for call in mock_logger.error.call_args_list]
        assert any("AI Studio 未接受模型更改" in e for e in errors)


# === Section 7: Revert Logic Tests ===


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_revert_success(mock_page, mock_server):
    """Test revert logic when switch fails but revert works by reading displayed model."""
    req_id = "test_revert_success"
    model_id = "target-model"

    with patch.dict(sys.modules, {"server": mock_server}):
        initial_state = json.dumps({"promptModel": "models/old-model"})
        final_state = json.dumps({"promptModel": "models/target-model"})

        mock_page.evaluate.side_effect = [
            initial_state,  # 1. get initial
            None,  # 2. set item
            None,  # 3. set item (compat)
            final_state,  # 4. consumed by revert logic (get storage)
            initial_state,  # 5. consumed by revert logic (set revert storage)
            None,  # 6. set revert storage (extra safety)
        ] + [None] * 20

        mock_element = AsyncMock()
        mock_element.inner_text.return_value = "old-model"

        mock_locator = MagicMock()
        type(mock_locator).first = PropertyMock(return_value=mock_element)
        mock_page.locator.return_value = mock_locator

        mock_server.parsed_model_list = [
            {"id": "target-model", "display_name": "Target Model"},
            {"id": "old-model", "display_name": "Old Model"},
        ]

        mock_expect = MagicMock()
        mock_expect.to_be_visible = AsyncMock()

        with (
            patch(
                "browser_utils.models.switcher._verify_and_apply_ui_state",
                new_callable=AsyncMock,
                side_effect=[False, True, True, True],
            ) as mock_verify,
            patch(
                "browser_utils.models.switcher.expect_async", return_value=mock_expect
            ),
            patch(
                "browser_utils.operations.save_error_snapshot", new_callable=AsyncMock
            ),
        ):
            result = await switch_ai_studio_model(mock_page, model_id, req_id)

            assert result is False

            set_calls = [
                args
                for args, _ in mock_page.evaluate.call_args_list
                if "setItem" in str(args)
            ]
            assert len(set_calls) >= 3
            last_set_arg = set_calls[-1][1]
            assert "models/old-model" in last_set_arg

            assert mock_verify.call_count == 4


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_revert_failure_fallback(mock_page, mock_server):
    """Test revert logic when reading displayed model fails, falls back to original storage."""
    req_id = "test_revert_fallback"
    model_id = "target-model"

    initial_state = json.dumps({"promptModel": "models/original-model"})

    mock_page.evaluate.side_effect = [
        initial_state,  # 1. get initial
        None,  # 2. set item
        None,  # 3. set item (compat)
        None,  # 4. set fallback storage
    ] + [None] * 10

    mock_locator = MagicMock()
    mock_element = AsyncMock()
    mock_element.inner_text.side_effect = Exception("Locator fail")
    type(mock_locator).first = PropertyMock(return_value=mock_element)
    mock_page.locator.return_value = mock_locator

    mock_server.parsed_model_list = [
        {"id": "target-model", "display_name": "Target Model"}
    ]

    mock_expect = MagicMock()
    mock_expect.to_be_visible = AsyncMock()

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("browser_utils.models.switcher.expect_async", return_value=mock_expect),
    ):
        result = await switch_ai_studio_model(mock_page, model_id, req_id)

        assert result is False

        set_calls = [
            args
            for args, _ in mock_page.evaluate.call_args_list
            if "setItem" in str(args)
        ]
        last_set_arg = set_calls[-1][1]
        assert "models/original-model" in last_set_arg


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_model_revert_blind_trust(mock_page, mock_server):
    """Test revert logic uses displayed model name as ID blindly (current behavior)."""
    req_id = "test_revert_blind"
    model_id = "target-model"

    initial_state = json.dumps({"promptModel": "models/original-model"})

    mock_page.evaluate.side_effect = [
        initial_state,  # 1. get initial
        None,  # 2. set item
        None,  # 3. set item (compat)
        initial_state,  # 4. get revert storage
        None,  # 5. set revert storage
    ] + [None] * 10

    mock_element = AsyncMock()
    mock_element.inner_text.return_value = "Unknown Model"

    mock_locator = MagicMock()
    type(mock_locator).first = PropertyMock(return_value=mock_element)
    mock_page.locator.return_value = mock_locator

    mock_server.parsed_model_list = [
        {"id": "target-model", "display_name": "Target Model"}
    ]

    mock_expect = MagicMock()
    mock_expect.to_be_visible = AsyncMock()

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            new_callable=AsyncMock,
            side_effect=[False, True, True, True],
        ),
        patch("browser_utils.models.switcher.expect_async", return_value=mock_expect),
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
    ):
        result = await switch_ai_studio_model(mock_page, model_id, req_id)

        assert result is False

        set_calls = [
            args
            for args, _ in mock_page.evaluate.call_args_list
            if "setItem" in str(args)
        ]
        last_set_arg = set_calls[-1][1]
        assert "models/Unknown Model" in last_set_arg
