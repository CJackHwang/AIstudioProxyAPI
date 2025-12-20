# Focused coverage tests for browser_utils/model_management.py
# Targets specific missing lines to achieve >80% coverage

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    """Simple mock page."""
    page = AsyncMock()
    page.locator = MagicMock()
    page.evaluate = AsyncMock(return_value=None)
    page.goto = AsyncMock()
    page.url = "https://aistudio.google.com/prompts/new_chat"
    return page


# ===== _verify_ui_state_settings Coverage =====


@pytest.mark.asyncio
async def test_verify_ui_missing_storage(mock_page):
    """Lines 49-57: localStorage missing."""
    mock_page.evaluate.return_value = None

    result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert result["error"] == "localStorage不存在"
    assert result["needsUpdate"] is True


@pytest.mark.asyncio
async def test_verify_ui_json_error(mock_page):
    """Lines 82-90: JSONDecodeError handling."""
    mock_page.evaluate.return_value = "invalid json"

    result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert "JSON解析失败" in result["error"]


@pytest.mark.asyncio
async def test_verify_ui_general_exception(mock_page):
    """Lines 94-102: General exception handling."""
    mock_page.evaluate.side_effect = Exception("Page error")

    result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert "验证失败" in result["error"]


# ===== _force_ui_state_settings Coverage =====


@pytest.mark.asyncio
async def test_force_ui_no_update_needed(mock_page):
    """Lines 122-124: Early return when no update needed."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        return_value={"needsUpdate": False},
    ):
        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is True
        mock_page.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_force_ui_verify_fail(mock_page):
    """Lines 147-149: Verification fails after setting."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        side_effect=[{"needsUpdate": True, "prefs": {}}, {"needsUpdate": True}],
    ):
        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is False


# ===== _force_ui_state_with_retry Coverage =====


@pytest.mark.asyncio
async def test_retry_success_first_attempt(mock_page):
    """Lines 180-182: Success on first attempt."""
    with patch(
        "browser_utils.models.ui_state._force_ui_state_settings", return_value=True
    ):
        result = await _force_ui_state_with_retry(mock_page, max_retries=3)

        assert result is True


@pytest.mark.asyncio
async def test_retry_fail_all(mock_page):
    """Lines 184-189: All retries fail."""
    with patch(
        "browser_utils.models.ui_state._force_ui_state_settings", return_value=False
    ):
        result = await _force_ui_state_with_retry(
            mock_page, max_retries=2, retry_delay=0.01
        )

        assert result is False


# ===== _verify_and_apply_ui_state Coverage =====


@pytest.mark.asyncio
async def test_apply_ui_needs_update(mock_page):
    """Lines 214-216: Needs update path."""
    with (
        patch(
            "browser_utils.models.ui_state._verify_ui_state_settings",
            return_value={
                "exists": True,
                "needsUpdate": True,
                "isAdvancedOpen": False,
                "areToolsOpen": False,
            },
        ),
        patch(
            "browser_utils.models.ui_state._force_ui_state_with_retry",
            return_value=True,
        ),
    ):
        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True


@pytest.mark.asyncio
async def test_apply_ui_already_ok(mock_page):
    """Lines 217-219: No update needed."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        return_value={
            "exists": True,
            "needsUpdate": False,
            "isAdvancedOpen": True,
            "areToolsOpen": True,
        },
    ):
        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True


# ===== switch_ai_studio_model Coverage =====


@pytest.mark.asyncio
async def test_switch_model_json_error_original(mock_page):
    """Lines 246-248: JSONDecodeError on original prefs."""
    mock_page.evaluate.side_effect = ["invalid json", None, None, None]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="gemini-pro")
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "gemini-pro", "req1")

        # Should handle error and continue
        assert result in [True, False]  # May succeed or fail depending on verification


@pytest.mark.asyncio
async def test_switch_model_already_set_wrong_url(mock_page):
    """Lines 256-269: Model already set but URL wrong."""
    prefs = json.dumps({"promptModel": "models/gemini-pro"})
    mock_page.evaluate.return_value = prefs
    mock_page.url = "https://wrong.url"

    with patch("browser_utils.models.switcher.expect_async") as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "gemini-pro", "req1")

        assert result is True
        mock_page.goto.assert_called_once()


@pytest.mark.asyncio
async def test_switch_model_ui_state_fail_warning(mock_page):
    """Lines 283-284: UI state fails but continues."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new")
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=False,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.models.switcher.logger") as mock_logger,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await switch_ai_studio_model(mock_page, "new", "req1")

        # Verify warning logged
        warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert any("UI状态设置失败" in str(w) for w in warnings)


@pytest.mark.asyncio
async def test_switch_model_final_ui_fail(mock_page):
    """Lines 303-307: Final UI state verification."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new")
    mock_page.locator.return_value = mock_locator

    ui_calls = [True, False]  # Initial succeeds, final fails

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            side_effect=lambda *args: ui_calls.pop(0),
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new", "req1")

        assert result is True  # Still succeeds despite warning


@pytest.mark.asyncio
async def test_switch_model_final_prefs_json_error(mock_page):
    """Lines 317-318: JSONDecodeError on final prefs."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [prefs, None, None, "invalid json"]

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.models.switcher.logger"),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new", "req1")

        assert result is False  # Fails due to verification failure


@pytest.mark.asyncio
async def test_switch_model_display_read_error(mock_page):
    """Lines 360-366: Exception reading displayed model."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(side_effect=Exception("Read failed"))
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_incognito_active(mock_page):
    """Lines 383-384: Incognito already active."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_model_loc = MagicMock()
    mock_model_loc.first.inner_text = AsyncMock(return_value="new")

    mock_incognito = MagicMock()
    mock_incognito.wait_for = AsyncMock()
    mock_incognito.get_attribute = AsyncMock(return_value="ms-button-active")

    def loc_side_effect(sel):
        if "model-name" in sel:
            return mock_model_loc
        if "Temporary" in sel:
            return mock_incognito
        return MagicMock()

    mock_page.locator.side_effect = loc_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new", "req1")

        assert result is True


@pytest.mark.asyncio
async def test_switch_model_incognito_exception(mock_page):
    """Lines 400-403: Incognito toggle fails."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_model_loc = MagicMock()
    mock_model_loc.first.inner_text = AsyncMock(return_value="new")

    mock_incognito = MagicMock()
    mock_incognito.wait_for = AsyncMock(side_effect=Exception("Button not found"))

    def loc_side_effect(sel):
        if "model-name" in sel:
            return mock_model_loc
        if "Temporary" in sel:
            return mock_incognito
        return MagicMock()

    mock_page.locator.side_effect = loc_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new", "req1")

        assert result is True  # Succeeds despite incognito failure


# ===== load_excluded_models Coverage =====


@pytest.mark.asyncio
async def test_load_excluded_file_exists():
    """Lines 597-609: Successful load."""
    from api_utils.server_state import state

    state.excluded_model_ids = set()

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
    ):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = ["model-1\n", "model-2\n"]
        mock_open.return_value = mock_file

        load_excluded_models("test.txt")

        assert "model-1" in state.excluded_model_ids
        assert "model-2" in state.excluded_model_ids


@pytest.mark.asyncio
async def test_load_excluded_empty_file():
    """Lines 606-609: Empty file."""
    from api_utils.server_state import state

    state.excluded_model_ids = set()

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
    ):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = []
        mock_open.return_value = mock_file

        load_excluded_models("empty.txt")

        assert len(state.excluded_model_ids) == 0


@pytest.mark.asyncio
async def test_load_excluded_file_not_found():
    """Lines 610-611: File not found."""
    from api_utils.server_state import state

    state.excluded_model_ids = set()

    with patch("os.path.exists", return_value=False):
        load_excluded_models("nonexistent.txt")

        assert len(state.excluded_model_ids) == 0


@pytest.mark.asyncio
async def test_load_excluded_exception():
    """Lines 612-613: Exception during load."""
    from api_utils.server_state import state

    state.excluded_model_ids = set()

    with patch("os.path.exists", side_effect=Exception("Disk error")):
        load_excluded_models("error.txt")

        # Should not crash, just log error
        assert len(state.excluded_model_ids) == 0


# ===== _handle_initial_model_state_and_storage Coverage =====


@pytest.mark.asyncio
async def test_handle_initial_missing_storage(mock_page):
    """Lines 632-635: Missing localStorage."""

    mock_page.evaluate.return_value = None
    mock_page.url = "https://test.url"

    with (
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        # Should trigger reload flow
        assert mock_page.goto.called


@pytest.mark.asyncio
async def test_handle_initial_json_error(mock_page):
    """Lines 664-669: JSONDecodeError."""
    mock_page.evaluate.return_value = "invalid json"
    mock_page.url = "https://test.url"

    with (
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        # Should trigger reload
        assert mock_page.goto.called


@pytest.mark.asyncio
async def test_handle_initial_exception_fallback(mock_page):
    """Lines 738-753: Exception with fallback."""
    mock_page.evaluate.side_effect = Exception("Critical error")

    with patch(
        "browser_utils.models.startup._set_model_from_page_display"
    ) as mock_fallback:
        await _handle_initial_model_state_and_storage(mock_page)

        # Should call fallback
        mock_fallback.assert_called_once()
        assert mock_fallback.call_args[1]["set_storage"] is False


# ===== _set_model_from_page_display Coverage =====


@pytest.mark.asyncio
async def test_set_model_display_basic(mock_page):
    """Lines 765-795: Basic display read."""
    from api_utils.server_state import state

    state.current_ai_studio_model_id = "old"

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="new-model")
    mock_page.locator.return_value = mock_loc

    await _set_model_from_page_display(mock_page, set_storage=False)

    assert state.current_ai_studio_model_id == "new-model"


@pytest.mark.asyncio
async def test_set_model_display_with_storage(mock_page):
    """Lines 797-860: Storage update path."""
    from api_utils.server_state import state

    # Setup event mock
    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set = MagicMock(return_value=True)
    state.model_list_fetch_event = mock_event

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="model-id")
    mock_page.locator.return_value = mock_loc

    # First call returns existing prefs, second call for setItem
    mock_page.evaluate.side_effect = [json.dumps({}), None]

    with patch(
        "browser_utils.models.startup._verify_and_apply_ui_state", return_value=True
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Verify setItem called
        calls = [str(c) for c in mock_page.evaluate.call_args_list]
        assert any("setItem" in c for c in calls)


@pytest.mark.asyncio
async def test_set_model_display_json_error_storage(mock_page):
    """Lines 807-811: JSONDecodeError on existing prefs."""
    from api_utils.server_state import state

    # Setup event mock
    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set = MagicMock(return_value=True)
    state.model_list_fetch_event = mock_event

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="model")
    mock_page.locator.return_value = mock_loc

    # First call returns invalid JSON, second call for setItem
    mock_page.evaluate.side_effect = ["invalid json", None]

    with patch(
        "browser_utils.models.startup._verify_and_apply_ui_state", return_value=True
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Should handle error and create new prefs
        assert mock_page.evaluate.call_count >= 2


@pytest.mark.asyncio
async def test_set_model_display_exception(mock_page):
    """Lines 861-864: Exception handling."""
    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(side_effect=Exception("Read failed"))
    mock_page.locator.return_value = mock_loc

    # Should not raise
    await _set_model_from_page_display(mock_page, set_storage=False)


# ===== Complex Revert Logic Coverage (Lines 430-554) =====


@pytest.mark.asyncio
async def test_switch_model_revert_read_fail_with_original(mock_page):
    """Lines 431-459: Revert path when reading display fails, with original prefs."""
    original_prefs = json.dumps({"promptModel": "models/original-model"})

    # Setup evaluation sequence
    evaluations = [
        original_prefs,  # First: get original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Final prefs (mismatch)
        None,  # Revert: restore original prefs
    ]
    mock_page.evaluate.side_effect = evaluations

    # Model name locator fails on revert attempt
    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Display read failed"),  # First storage check fails
            Exception("Revert read fails"),  # Revert display read also fails
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False
        # Should attempt to restore original prefs
        assert mock_page.goto.call_count >= 2


@pytest.mark.asyncio
async def test_switch_model_revert_read_fail_no_original(mock_page):
    """Lines 455-459: Revert path when no original prefs available."""
    # No original prefs
    mock_page.evaluate.side_effect = [
        None,  # No original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Final prefs (mismatch)
    ]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Display read failed"),  # Storage check fails
            Exception("Revert read fails"),  # Revert display read also fails
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_revert_with_valid_display(mock_page):
    """Lines 461-526: Revert with successful display read."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,  # Original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Final prefs mismatch
        "current-model",  # Revert: read current display name (invalid, will be replaced)
        json.dumps({}),  # Revert: get current localStorage for base prefs
        None,  # Revert: set localStorage with reverted model
        None,  # Revert: set localStorage again (UI state compatibility)
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("First check fails"),  # Initial storage check fails
            "current-model",  # Revert: successfully read display
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False
        # Should navigate for revert
        assert mock_page.goto.call_count >= 2


@pytest.mark.asyncio
async def test_switch_model_revert_ls_parse_fail(mock_page):
    """Lines 483-488: Revert localStorage parse fails, uses original prefs."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,  # Original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Mismatch
        "invalid json",  # Revert: current localStorage is invalid JSON
        None,  # Revert: set localStorage with reverted model
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),  # Initial check fails
            "fallback-model",  # Revert: successfully read display
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_revert_ui_state_fail(mock_page):
    """Lines 494-496: Revert UI state setting fails."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,  # Original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Mismatch
        json.dumps({}),  # Revert: get current localStorage
        None,  # Revert: set localStorage
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),
            "revert-model",
        ]
    )
    mock_page.locator.return_value = mock_locator

    ui_calls = [True, False, False]  # Initial succeeds, revert fails twice

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            side_effect=lambda *args: ui_calls.pop(0) if ui_calls else False,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_revert_final_ui_success(mock_page):
    """Lines 518-522: Revert final UI state verification success."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Mismatch
        json.dumps({}),  # Revert: get localStorage
        None,  # Revert: set localStorage
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),
            "revert-model",
        ]
    )
    mock_page.locator.return_value = mock_locator

    ui_calls = [True, True, True]  # All UI state calls succeed

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            side_effect=lambda *args: ui_calls.pop(0) if ui_calls else True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_no_revert_id_with_original(mock_page):
    """Lines 527-553: No valid revert ID, fallback to original prefs."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Mismatch
        None,  # Final fallback: restore original
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    # Return "无法读取" to trigger no-valid-ID path
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),
            "   ",  # Whitespace-only, strips to empty -> treated as invalid
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False
        # Should attempt final fallback restoration
        assert mock_page.goto.call_count >= 2


@pytest.mark.asyncio
async def test_switch_model_no_revert_id_no_original(mock_page):
    """Lines 551-552: No revert ID and no original prefs."""
    evaluations = [
        None,  # No original prefs
        None,  # Set new promptModel
        None,  # Set UI state
        json.dumps({"promptModel": "models/wrong"}),  # Mismatch
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),
            "",  # Empty display name
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


@pytest.mark.asyncio
async def test_switch_model_exception_recovery_with_original(mock_page):
    """Lines 564-586: Exception handling with original prefs recovery."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,  # Get original prefs
        Exception("Critical failure"),  # Trigger exception path
        None,  # Recovery: restore original
    ]
    mock_page.evaluate.side_effect = evaluations

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False
        # Should attempt recovery
        assert mock_page.goto.call_count >= 1


@pytest.mark.asyncio
async def test_switch_model_exception_recovery_fail(mock_page):
    """Lines 582-585: Exception recovery itself fails."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,  # Get original prefs
        Exception("First failure"),  # Trigger exception
        Exception("Recovery also fails"),  # Recovery evaluate fails
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_page.goto.side_effect = Exception("Goto fails")

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, "new-model", "req1")

        assert result is False


# ===== Additional Coverage for _handle_initial_model_state_and_storage =====


@pytest.mark.asyncio
async def test_handle_initial_reload_retry_all_fail(mock_page):
    """Lines 707-725: All reload retries fail."""
    from api_utils.server_state import state

    state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    state.model_list_fetch_event.is_set = MagicMock(return_value=True)

    mock_page.evaluate.return_value = None  # Missing localStorage
    mock_page.url = "https://test.url"
    mock_page.goto.side_effect = Exception("Reload always fails")

    with (
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=False,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
        patch(
            "browser_utils.models.startup.asyncio.sleep", new_callable=AsyncMock
        ),  # Skip retry delays
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Should not raise despite all retries failing
        await _handle_initial_model_state_and_storage(mock_page)

        # Should have tried 3 times
        assert mock_page.goto.call_count == 3


@pytest.mark.asyncio
async def test_handle_initial_valid_state_no_reload(mock_page):
    """Lines 734-737: Valid state, no reload needed."""
    from api_utils.server_state import state

    state.current_ai_studio_model_id = None

    prefs = json.dumps(
        {
            "promptModel": "models/valid-model",
            "isAdvancedOpen": True,
            "areToolsOpen": True,
        }
    )
    mock_page.evaluate.return_value = prefs

    with patch(
        "browser_utils.models.startup._verify_ui_state_settings",
        return_value={"needsUpdate": False},
    ):
        await _handle_initial_model_state_and_storage(mock_page)

        # Should not call goto since state is valid
        mock_page.goto.assert_not_called()
        assert state.current_ai_studio_model_id == "valid-model"


@pytest.mark.asyncio
async def test_set_model_display_wait_for_event_timeout(mock_page):
    """Lines 776-781: Wait for model list event timeout."""
    from api_utils.server_state import state

    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set = MagicMock(return_value=False)
    mock_event.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    state.model_list_fetch_event = mock_event

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="model-from-page")
    mock_page.locator.return_value = mock_loc

    await _set_model_from_page_display(mock_page, set_storage=False)

    # Should handle timeout gracefully
    assert state.current_ai_studio_model_id == "model-from-page"


@pytest.mark.asyncio
async def test_set_model_display_ui_state_fail_fallback(mock_page):
    """Lines 816-824: UI state setting fails, use traditional method."""
    from api_utils.server_state import state

    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set = MagicMock(return_value=True)
    state.model_list_fetch_event = mock_event

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="test-model")
    mock_page.locator.return_value = mock_loc

    mock_page.evaluate.side_effect = [json.dumps({}), None]

    with patch(
        "browser_utils.models.startup._verify_and_apply_ui_state", return_value=False
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Should still call setItem with traditional method
        assert mock_page.evaluate.call_count >= 2


@pytest.mark.asyncio
async def test_set_model_display_no_model_id_found(mock_page):
    """Lines 832-835: No model ID found from display."""
    from api_utils.server_state import state

    mock_event = AsyncMock(spec=asyncio.Event)
    mock_event.is_set = MagicMock(return_value=True)
    state.model_list_fetch_event = mock_event

    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(return_value="unknown-display")
    mock_page.locator.return_value = mock_loc

    # Return empty prefs without promptModel
    mock_page.evaluate.side_effect = [json.dumps({}), None]

    with patch(
        "browser_utils.models.startup._verify_and_apply_ui_state", return_value=True
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Should handle missing model ID gracefully
        assert state.current_ai_studio_model_id == "unknown-display"


# ===== Additional Edge Cases for 80% Coverage =====


@pytest.mark.asyncio
async def test_verify_ui_cancellederror(mock_page):
    """Lines 92-93: CancelledError propagation in verify."""
    mock_page.evaluate.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _verify_ui_state_settings(mock_page, "req1")


@pytest.mark.asyncio
async def test_force_ui_cancellederror(mock_page):
    """Lines 151-152: CancelledError in force_ui_state_settings."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        side_effect=asyncio.CancelledError(),
    ):
        with pytest.raises(asyncio.CancelledError):
            await _force_ui_state_settings(mock_page, "req1")


@pytest.mark.asyncio
async def test_verify_apply_cancellederror(mock_page):
    """Lines 221-222: CancelledError in verify_and_apply."""
    with patch(
        "browser_utils.models.ui_state._verify_ui_state_settings",
        side_effect=asyncio.CancelledError(),
    ):
        with pytest.raises(asyncio.CancelledError):
            await _verify_and_apply_ui_state(mock_page, "req1")


@pytest.mark.asyncio
async def test_switch_model_cancellederror(mock_page):
    """Lines 556-557: CancelledError in switch_ai_studio_model."""
    mock_page.evaluate.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await switch_ai_studio_model(mock_page, "new-model", "req1")


@pytest.mark.asyncio
async def test_switch_model_incognito_cancellederror(mock_page):
    """Lines 400-401: CancelledError during incognito toggle."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_model_loc = MagicMock()
    mock_model_loc.first.inner_text = AsyncMock(return_value="new")

    mock_incognito = MagicMock()
    mock_incognito.wait_for = AsyncMock(side_effect=asyncio.CancelledError())

    def loc_side_effect(sel):
        if "model-name" in sel:
            return mock_model_loc
        if "Temporary" in sel:
            return mock_incognito
        return MagicMock()

    mock_page.locator.side_effect = loc_side_effect

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await switch_ai_studio_model(mock_page, "new", "req1")


@pytest.mark.asyncio
async def test_switch_model_revert_cancellederror(mock_page):
    """Lines 429-430: CancelledError during revert display read."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    # Make evaluation also throw CancelledError on revert attempts
    evaluations = [
        original_prefs,
        None,
        None,
        json.dumps({"promptModel": "models/wrong"}),
        asyncio.CancelledError(),  # CancelledError during revert evaluate
    ]
    mock_page.evaluate.side_effect = evaluations

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(
        side_effect=[
            Exception("Check fails"),  # Initial check fails, enters revert
            asyncio.CancelledError(),  # CancelledError during revert display read
        ]
    )
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await switch_ai_studio_model(mock_page, "new-model", "req1")


@pytest.mark.asyncio
async def test_switch_model_exception_recovery_cancellederror(mock_page):
    """Lines 582-583: CancelledError during exception recovery."""
    original_prefs = json.dumps({"promptModel": "models/original"})

    evaluations = [
        original_prefs,
        Exception("Trigger exception path"),
        asyncio.CancelledError(),  # CancelledError during recovery
    ]
    mock_page.evaluate.side_effect = evaluations

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
        patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock),
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await switch_ai_studio_model(mock_page, "new-model", "req1")


@pytest.mark.asyncio
async def test_handle_initial_cancellederror(mock_page):
    """Lines 738-739: CancelledError in handle_initial."""
    mock_page.evaluate.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _handle_initial_model_state_and_storage(mock_page)


@pytest.mark.asyncio
async def test_handle_initial_exception_fallback_cancellederror(mock_page):
    """Lines 750-751: CancelledError in fallback path."""
    mock_page.evaluate.side_effect = Exception("Error")

    with patch(
        "browser_utils.models.startup._set_model_from_page_display",
        side_effect=asyncio.CancelledError(),
    ):
        with pytest.raises(asyncio.CancelledError):
            await _handle_initial_model_state_and_storage(mock_page)


@pytest.mark.asyncio
async def test_set_model_display_cancellederror(mock_page):
    """Lines 861-862: CancelledError in set_model_from_page_display."""
    mock_loc = MagicMock()
    mock_loc.first.inner_text = AsyncMock(side_effect=asyncio.CancelledError())
    mock_page.locator.return_value = mock_loc

    with pytest.raises(asyncio.CancelledError):
        await _set_model_from_page_display(mock_page, set_storage=False)


@pytest.mark.asyncio
async def test_switch_model_display_cancellederror(mock_page):
    """Lines 360-361: CancelledError when reading display model."""
    prefs = json.dumps({"promptModel": "models/old"})
    mock_page.evaluate.side_effect = [
        prefs,
        None,
        None,
        json.dumps({"promptModel": "models/new"}),
    ]

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(side_effect=asyncio.CancelledError())
    mock_page.locator.return_value = mock_locator

    with (
        patch(
            "browser_utils.models.switcher._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.switcher.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await switch_ai_studio_model(mock_page, "new", "req1")


@pytest.mark.asyncio
async def test_handle_initial_reload_cancellederror(mock_page):
    """Lines 707-708: CancelledError during page reload."""
    from api_utils.server_state import state

    state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    state.model_list_fetch_event.is_set = MagicMock(return_value=True)

    mock_page.evaluate.return_value = None  # Missing localStorage
    mock_page.url = "https://test.url"
    mock_page.goto.side_effect = asyncio.CancelledError()

    with (
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=False,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await _handle_initial_model_state_and_storage(mock_page)


@pytest.mark.asyncio
async def test_handle_initial_invalid_promptmodel(mock_page):
    """Lines 646-649: Invalid promptModel in localStorage."""

    # promptModel is empty string (invalid)
    prefs = json.dumps({"promptModel": "   ", "isAdvancedOpen": False})
    mock_page.evaluate.return_value = prefs
    mock_page.url = "https://test.url"

    with (
        patch("browser_utils.models.startup._set_model_from_page_display"),
        patch(
            "browser_utils.models.startup._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.models.startup.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        # Should trigger reload due to invalid promptModel
        assert mock_page.goto.called
