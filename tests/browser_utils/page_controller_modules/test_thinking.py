import unittest.mock
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from browser_utils.page_controller_modules.thinking import (
    ThinkingCategory,
    ThinkingController,
)


@pytest.fixture
def mock_controller(mock_page):
    logger = MagicMock()
    controller = ThinkingController(mock_page, logger, "req_123")
    return controller


# --- Helper Logic Tests ---


def test_get_thinking_category(mock_controller):
    """Test model category detection via _get_thinking_category."""
    # THINKING_LEVEL_FLASH: gemini-3-flash models (4-level thinking)
    assert (
        mock_controller._get_thinking_category("gemini-3-flash-preview")
        == ThinkingCategory.THINKING_LEVEL_FLASH
    )
    assert (
        mock_controller._get_thinking_category("gemini-3-flash")
        == ThinkingCategory.THINKING_LEVEL_FLASH
    )

    # THINKING_LEVEL: gemini-3-pro models (2-level thinking)
    assert (
        mock_controller._get_thinking_category("gemini-3-pro")
        == ThinkingCategory.THINKING_LEVEL
    )
    assert (
        mock_controller._get_thinking_category("gemini-3-pro-preview")
        == ThinkingCategory.THINKING_LEVEL
    )

    # THINKING_PRO: gemini-2.5-pro models
    assert (
        mock_controller._get_thinking_category("gemini-2.5-pro")
        == ThinkingCategory.THINKING_PRO
    )
    assert (
        mock_controller._get_thinking_category("gemini-2.5-pro-preview")
        == ThinkingCategory.THINKING_PRO
    )

    # THINKING_FLASH: gemini-2.5-flash models (including lite)
    assert (
        mock_controller._get_thinking_category("gemini-2.5-flash")
        == ThinkingCategory.THINKING_FLASH
    )
    assert (
        mock_controller._get_thinking_category("gemini-2.5-flash-lite")
        == ThinkingCategory.THINKING_FLASH
    )

    # NON_THINKING: gemini-2.0-*, gemini-1.5-*, None
    assert (
        mock_controller._get_thinking_category("gemini-2.0-flash")
        == ThinkingCategory.NON_THINKING
    )
    assert (
        mock_controller._get_thinking_category("gemini-2.0-flash-lite")
        == ThinkingCategory.NON_THINKING
    )
    assert (
        mock_controller._get_thinking_category("gemini-1.5-pro")
        == ThinkingCategory.NON_THINKING
    )
    assert mock_controller._get_thinking_category(None) == ThinkingCategory.NON_THINKING


@pytest.mark.asyncio
async def test_has_thinking_dropdown(mock_controller, mock_page):
    # Case 1: Exists and visible
    mock_page.locator.return_value.count = AsyncMock(return_value=1)
    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        assert await mock_controller._has_thinking_dropdown() is True

    # Case 2: Does not exist
    mock_page.locator.return_value.count = AsyncMock(return_value=0)
    assert await mock_controller._has_thinking_dropdown() is False

    # Case 3: Exception during check (e.g. timeout on visibility, returns True as fallback logic says "return True" on exception inside inner try)
    mock_page.locator.return_value.count = AsyncMock(return_value=1)
    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async",
        side_effect=Exception("Timeout"),
    ):
        # The code catches exception in inner try and returns True?
        # Lines 170-174: try expect... except: return True.
        assert await mock_controller._has_thinking_dropdown() is True

    # Case 4: Exception during locator creation (outer try)
    mock_page.locator.side_effect = Exception("Fatal")
    assert await mock_controller._has_thinking_dropdown() is False


# --- _handle_thinking_budget Logic Tests ---


@pytest.mark.asyncio
async def test_handle_thinking_budget_disabled(mock_controller):
    # Mock helpers - THINKING_FLASH category
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    # reasoning_effort=0 -> disabled
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 0}, "model", MagicMock(return_value=False)
    )

    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=False, check_client_disconnected=unittest.mock.ANY
    )
    mock_controller._control_thinking_budget_toggle.assert_not_called()  # Flash model behavior (toggle hidden)


@pytest.mark.asyncio
async def test_handle_thinking_budget_disabled_non_flash(mock_controller):
    # Non-flash model (gemini-2.5-pro), disable thinking - but toggle is always on
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_PRO
    )
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 0}, "gemini-2.5-pro", MagicMock(return_value=False)
    )

    # THINKING_PRO has no main toggle (always on), so budget toggle is called
    mock_controller._control_thinking_mode_toggle.assert_not_called()
    mock_controller._control_thinking_budget_toggle.assert_called_with(
        should_be_checked=False, check_client_disconnected=unittest.mock.ANY
    )


@pytest.mark.asyncio
async def test_handle_thinking_budget_enabled_level(mock_controller):
    # Gemini 3 Pro with level
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # High
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "high"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("high", unittest.mock.ANY)

    # Low
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "low"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("low", unittest.mock.ANY)

    # Int >= 8000 -> High
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 8000}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("high", unittest.mock.ANY)

    # Int < 8000 -> Low
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 100}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("low", unittest.mock.ANY)

    # Invalid -> Keep current (None)
    mock_controller._set_thinking_level.reset_mock()
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "invalid"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_flash_4_levels(mock_controller):
    """Test Gemini 3 Flash 4-level thinking (minimal, low, medium, high).

    This tests the THINKING_LEVEL_FLASH category which maps reasoning_effort
    to 4 distinct levels based on thresholds:
    - high: >= 16000 or -1 (unlimited)
    - medium: >= 8000
    - low: >= 1024
    - minimal: < 1024
    """
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL_FLASH
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test string levels (direct mapping)
    test_cases = [
        ("minimal", "minimal"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("MINIMAL", "minimal"),  # Case insensitive
        ("HIGH", "high"),
    ]

    for input_level, expected_level in test_cases:
        mock_controller._set_thinking_level.reset_mock()
        await mock_controller._handle_thinking_budget(
            {"reasoning_effort": input_level},
            "gemini-3-flash-preview",
            MagicMock(return_value=False),
        )
        (
            mock_controller._set_thinking_level.assert_called_with(
                expected_level, unittest.mock.ANY
            ),
            f"Failed for input '{input_level}': expected '{expected_level}'",
        )


@pytest.mark.asyncio
async def test_handle_thinking_budget_flash_numeric_thresholds(mock_controller):
    """Test Gemini 3 Flash numeric threshold mapping.

    Thresholds:
    - >= 16000: high
    - >= 8000: medium
    - >= 1024: low
    - < 1024: minimal
    """
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL_FLASH
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test numeric thresholds (boundary cases)
    test_cases = [
        (16000, "high"),  # Exactly at high threshold
        (20000, "high"),  # Above high threshold
        (-1, "high"),  # Unlimited
        (8000, "medium"),  # Exactly at medium threshold
        (15999, "medium"),  # Just below high
        (1024, "low"),  # Exactly at low threshold
        (7999, "low"),  # Just below medium
        (1023, "minimal"),  # Just below low
        (1, "minimal"),  # Minimum positive value (0 disables thinking)
        (500, "minimal"),  # Well below low
    ]

    for input_value, expected_level in test_cases:
        mock_controller._set_thinking_level.reset_mock()
        await mock_controller._handle_thinking_budget(
            {"reasoning_effort": input_value},
            "gemini-3-flash-preview",
            MagicMock(return_value=False),
        )
        (
            mock_controller._set_thinking_level.assert_called_with(
                expected_level, unittest.mock.ANY
            ),
            f"Failed for input {input_value}: expected '{expected_level}'",
        )


@pytest.mark.asyncio
async def test_handle_thinking_budget_enabled_budget_caps(mock_controller):
    # Flash models with budget caps
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    # Flash Lite (cap 32k or 24k? Code says 24576 for flash-lite)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 100000},
        "gemini-2.0-flash-lite",
        MagicMock(return_value=False),
    )
    mock_controller._set_thinking_budget_value.assert_called_with(
        24576, unittest.mock.ANY
    )


@pytest.mark.asyncio
async def test_handle_thinking_budget_no_limit(mock_controller):
    # Budget enabled but set to 0/None -> disable manual budget
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    # normalize_reasoning_effort returns budget_enabled=False for -1 or 'none' if configured so?
    # Actually normalize_reasoning_effort behavior: 'none' -> thinking_enabled=True, budget_enabled=False
    # Let's rely on _handle_thinking_budget logic for "budget_enabled"

    # If reasoning_effort is None -> thinking disabled by default if normalize returns disabled
    # If reasoning_effort is "none" (string) -> Thinking enabled (default), Budget disabled (unlimited)

    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "none"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )
    mock_controller._control_thinking_budget_toggle.assert_called_with(
        should_be_checked=False, check_client_disconnected=unittest.mock.ANY
    )


# --- Interaction Methods Tests ---


@pytest.mark.asyncio
async def test_set_thinking_level(mock_controller, mock_page):
    trigger = AsyncMock()
    option = AsyncMock()
    mock_page.locator.side_effect = [
        trigger,
        option,
        AsyncMock(),
    ]  # trigger, option, listbox check

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_be_hidden = AsyncMock()

    trigger.locator.return_value.inner_text = AsyncMock(return_value="High")

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_level("High", MagicMock(return_value=False))

        trigger.click.assert_called()
        option.click.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle(mock_controller, mock_page):
    toggle = AsyncMock()
    mock_page.locator.return_value = toggle

    # Initial state: false. Desired: true.
    toggle.get_attribute.side_effect = ["false", "true"]  # Before click, after click

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._control_thinking_budget_toggle(
            True, MagicMock(return_value=False)
        )

        toggle.click.assert_called()

    # Test verify failure
    toggle.get_attribute.side_effect = ["false", "false"]  # Fails to change
    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        await mock_controller._control_thinking_budget_toggle(
            True, MagicMock(return_value=False)
        )
        # Should log warning but not raise (unless strict check implemented? Code just warns)
        mock_controller.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_set_thinking_budget_value_complex(mock_controller, mock_page):
    input_el = AsyncMock()
    mock_page.locator.return_value = input_el

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    # Simulate to_have_value failing initially, triggering fallback verification
    mock_expect.return_value.to_have_value.side_effect = [Exception("Mismatch"), None]

    # Fallback verification reads input_value
    input_el.input_value.return_value = "5000"

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_budget_value(
            5000, MagicMock(return_value=False)
        )

        input_el.fill.assert_called_with("5000", timeout=5000)
        # Should log success after reading value
        mock_controller.logger.info.assert_any_call(unittest.mock.ANY)


@pytest.mark.asyncio
async def test_set_thinking_budget_value_max_fallback(mock_controller, mock_page):
    input_el = AsyncMock()
    mock_page.locator.return_value = input_el

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_have_value.side_effect = Exception("Mismatch")

    input_el.input_value.return_value = "8000"  # Less than desired 10000
    input_el.get_attribute.return_value = "8000"  # Max is 8000

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_budget_value(
            10000, MagicMock(return_value=False)
        )

        # Should warn and try to set to max
        mock_controller.logger.warning.assert_called()
        # Should verify it called fill with 8000 eventually
        assert call("8000", timeout=5000) in input_el.fill.call_args_list


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_click_failure_fallback(
    mock_controller, mock_page
):
    # Test fallback to aria-label based toggle click if main toggle click fails
    toggle = AsyncMock()
    toggle.click.side_effect = Exception("Not clickable")

    alt_toggle = AsyncMock()
    alt_toggle.count = AsyncMock(return_value=1)

    def locator_side_effect(selector):
        if "button" in selector and "switch" in selector:
            return toggle
        if 'aria-label="Toggle thinking mode"' in selector:
            return alt_toggle
        if "mat-slide-toggle" in selector:  # Old fallback
            root = MagicMock()
            root.locator.return_value = AsyncMock()
            return root
        return toggle

    mock_page.locator.side_effect = locator_side_effect
    toggle.get_attribute.return_value = "false"

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._control_thinking_mode_toggle(
            True, MagicMock(return_value=False)
        )

        alt_toggle.click.assert_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_various_inputs(mock_controller):
    # Test various inputs for reasoning_effort triggering enable/disable
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    # String "none" -> enabled (No budget limit implies enabled)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "none"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )

    # String "100" -> enabled
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "100"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )

    # String "0" -> disabled
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "0"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=False, check_client_disconnected=unittest.mock.ANY
    )

    # String "-1" -> enabled
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "-1"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )

    # Int -1 -> enabled
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": -1}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )


@pytest.mark.asyncio
async def test_handle_thinking_budget_disabled_uses_level(mock_controller):
    # THINKING_LEVEL models with disabled thinking should skip toggle and just return
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 0}, "gemini-3-pro", MagicMock(return_value=False)
    )

    # THINKING_LEVEL has no main toggle (has_main_toggle=False), so no toggle call
    mock_controller._control_thinking_mode_toggle.assert_not_called()
    # Level models skip budget toggle logic entirely when disabled
    mock_controller._control_thinking_budget_toggle.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_downgrade_logic(mock_controller):
    # Test the path where directive says disabled but raw says enabled, and we fail to disable?
    # Actually lines 113-127: if not directive.thinking_enabled (but desired_enabled=True)

    mock_directive = MagicMock()
    mock_directive.thinking_enabled = False

    with patch(
        "browser_utils.page_controller_modules.thinking.normalize_reasoning_effort",
        return_value=mock_directive,
    ):
        mock_controller._get_thinking_category = MagicMock(
            return_value=ThinkingCategory.THINKING_FLASH
        )

        # _control_thinking_mode_toggle fails (returns False)
        mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=False)
        mock_controller._control_thinking_budget_toggle = AsyncMock()
        mock_controller._set_thinking_budget_value = AsyncMock()

        # Pass "high" -> _should_enable_from_raw returns True -> desired_enabled=True
        # But mock directive says False
        await mock_controller._handle_thinking_budget(
            {"reasoning_effort": "high"}, "model", MagicMock(return_value=False)
        )

        # Should attempt to disable toggle
        mock_controller._control_thinking_mode_toggle.assert_called_with(
            should_be_enabled=False, check_client_disconnected=unittest.mock.ANY
        )

        # Upon failure (since we mocked return_value=False), should set budget to 0
        mock_controller._control_thinking_budget_toggle.assert_called_with(
            should_be_checked=True, check_client_disconnected=unittest.mock.ANY
        )
        mock_controller._set_thinking_budget_value.assert_called_with(
            0, unittest.mock.ANY
        )


@pytest.mark.asyncio
async def test_handle_thinking_budget_cap_gemini_2_5(mock_controller):
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 40000}, "gemini-2.5-pro", MagicMock(return_value=False)
    )

    mock_controller._set_thinking_budget_value.assert_called_with(
        32768, unittest.mock.ANY
    )


@pytest.mark.asyncio
async def test_handle_thinking_budget_should_enable_variations(mock_controller):
    # Test _should_enable_from_raw logic via _handle_thinking_budget
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    # "high" -> Enable
    print("DEBUG: Testing high")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "high"}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is True
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # "low" -> Enable
    print("DEBUG: Testing low")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "low"}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is True
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # "-1" -> Enable
    print("DEBUG: Testing -1 string")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "-1"}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is True
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # -1 (int) -> Enable
    print("DEBUG: Testing -1 int")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": -1}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is True
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # "none" -> Enable (unlimited budget)
    # normalize_reasoning_effort("none") -> thinking_enabled=True
    print("DEBUG: Testing none")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "none"}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is True
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # "invalid" -> Disable
    print("DEBUG: Testing invalid")
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "invalid"}, "model", check_disconnect_mock
    )
    assert mock_controller._control_thinking_mode_toggle.call_count == 1
    _, kwargs = mock_controller._control_thinking_mode_toggle.call_args
    assert kwargs["should_be_enabled"] is False
    mock_controller._control_thinking_mode_toggle.reset_mock()


@pytest.mark.asyncio
async def test_handle_thinking_budget_skip_level_disabled(mock_controller):
    # Skip logic: THINKING_LEVEL with disabled thinking should skip toggle
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 0}, "gemini-3-pro", check_disconnect_mock
    )

    # THINKING_LEVEL has no main toggle
    mock_controller._control_thinking_mode_toggle.assert_not_called()
    mock_controller._control_thinking_budget_toggle.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_caps(mock_controller):
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    # flash -> 24576
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 40000}, "gemini-flash", check_disconnect_mock
    )
    mock_controller._set_thinking_budget_value.assert_called_with(
        24576, unittest.mock.ANY
    )

    # flash-lite -> 24576
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 40000}, "flash-lite", check_disconnect_mock
    )
    mock_controller._set_thinking_budget_value.assert_called_with(
        24576, unittest.mock.ANY
    )


@pytest.mark.asyncio
async def test_set_thinking_level_errors(mock_controller):
    # Test error handling in _set_thinking_level
    # Simulate success path but verification mismatch
    trigger = MagicMock()
    trigger.click = AsyncMock()
    trigger.scroll_into_view_if_needed = AsyncMock()
    trigger.locator.return_value.inner_text = AsyncMock(return_value="Low")

    mock_controller.page.locator.return_value = trigger

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_be_hidden = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        await mock_controller._set_thinking_level("High", check_disconnect_mock)
        # Should verify warning log
        mock_controller.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_fallback(mock_controller):
    # Test fallback to aria-label based toggle click
    toggle = MagicMock()
    toggle.count = AsyncMock(return_value=1)  # Element exists
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock(side_effect=Exception("Click failed"))

    alt_toggle = MagicMock()
    alt_toggle.count = AsyncMock(return_value=1)
    alt_toggle.click = AsyncMock()

    def locator_side_effect(selector):
        if "button" in selector and "switch" in selector:
            return toggle
        if 'aria-label="Toggle thinking mode"' in selector:
            return alt_toggle
        if 'data-test-toggle="enable-thinking"' in selector:
            root = MagicMock()
            root.locator.return_value = MagicMock()
            return root
        return toggle

    mock_controller.page.locator.side_effect = locator_side_effect

    # Mock expect_async
    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        await mock_controller._control_thinking_mode_toggle(True, check_disconnect_mock)

    alt_toggle.click.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_fallback(mock_controller):
    # Test fallback to aria-label based toggle click
    toggle = MagicMock()
    toggle.count = AsyncMock(return_value=1)  # Element exists
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock(side_effect=Exception("Click failed"))

    alt_toggle = MagicMock()
    alt_toggle.count = AsyncMock(return_value=1)
    alt_toggle.click = AsyncMock()

    def locator_side_effect(selector):
        if "button" in selector and "switch" in selector:
            return toggle
        if 'aria-label="Toggle thinking budget between auto and manual"' in selector:
            return alt_toggle
        if 'data-test-toggle="manual-budget"' in selector:
            root = MagicMock()
            root.locator.return_value = MagicMock()
            return root
        return toggle

    mock_controller.page.locator.side_effect = locator_side_effect

    # Mock expect_async
    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        await mock_controller._control_thinking_budget_toggle(
            True, check_disconnect_mock
        )

    alt_toggle.click.assert_called()


@pytest.mark.asyncio
async def test_set_thinking_budget_value_fallback(mock_controller):
    # Test fallback in _set_thinking_budget_value
    budget_input = MagicMock()
    budget_input.fill = AsyncMock()
    # Verification raises exception
    budget_input.input_value = AsyncMock(return_value="20000")  # Mismatch

    mock_controller.page.locator.return_value = budget_input

    # Mock expect_async to fail first verification
    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_have_value = AsyncMock(
        side_effect=Exception("Value mismatch")
    )

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        await mock_controller._set_thinking_budget_value(30000, check_disconnect_mock)

        # Should check fallback path
        # It tries to read input_value, sees 20000 != 30000
        # Then tries max attribute
        budget_input.get_attribute.assert_called_with("max")


# --- Additional Coverage Tests ---


@pytest.mark.asyncio
async def test_handle_thinking_budget_invalid_string(mock_controller):
    """Test handling invalid string value for reasoning_effort"""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )

    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_level = AsyncMock()

    # Test with invalid string that can't be parsed to int - should hit exception handler
    params = {"reasoning_effort": "invalid_value"}
    await mock_controller._handle_thinking_budget(
        params, "gemini-3-pro", MagicMock(return_value=False)
    )

    # The exception handling path should be taken, leading to level_to_set = None
    # which logs "无法解析等级" and returns without calling _set_thinking_level
    # Note: This test mainly ensures the exception path is covered


# --- Additional Coverage Tests for Missing Lines ---


@pytest.mark.asyncio
async def test_should_enable_from_raw_edge_cases(mock_controller):
    """Test _should_enable_from_raw with various edge cases to cover lines 59, 66."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    # Test string "none" (line 58-59) - should enable thinking
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "none"}, "model", MagicMock(return_value=False)
    )
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True, check_client_disconnected=unittest.mock.ANY
    )
    mock_controller._control_thinking_mode_toggle.reset_mock()

    # Test invalid type (boolean) - normalize_reasoning_effort returns default config
    # which typically enables thinking (line 66 returns False in _should_enable_from_raw,
    # but directive.thinking_enabled takes precedence)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": [1, 2, 3]},
        "model",
        MagicMock(return_value=False),  # Use list instead
    )
    # normalize_reasoning_effort returns default (ENABLE_THINKING_BUDGET)
    # Just verify it doesn't crash - behavior depends on config


@pytest.mark.asyncio
async def test_set_thinking_level_string_conversion_paths(mock_controller):
    """Test _set_thinking_level with string conversion paths (lines 113-117)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test string "none" -> high (line 110-111)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "none"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("high", unittest.mock.ANY)

    # Test string that parses to int >= 8000 (line 114-115)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "9000"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("high", unittest.mock.ANY)

    # Test string that parses to int < 8000 (line 115)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "5000"}, "gemini-3-pro", MagicMock(return_value=False)
    )
    mock_controller._set_thinking_level.assert_called_with("low", unittest.mock.ANY)

    # Test string with exception during parsing (line 116-117)
    mock_controller._set_thinking_level.reset_mock()
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "not_a_number_or_keyword"},
        "gemini-3-pro",
        MagicMock(return_value=False),
    )
    # Should not call _set_thinking_level (line 122)
    mock_controller._set_thinking_level.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_no_main_toggle_enabled(mock_controller):
    """Test enabled path when model has no main toggle (lines 147-152)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_FLASH
    )

    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()

    # Test with reasoning_effort that enables thinking but model has no main toggle
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": 5000}, "gemini-2.5-pro", MagicMock(return_value=False)
    )

    # Should call _control_thinking_mode_toggle even without main toggle (line 148-152)
    mock_controller._control_thinking_mode_toggle.assert_called()


@pytest.mark.asyncio
async def test_has_thinking_dropdown_cancelled_error(mock_controller, mock_page):
    """Test CancelledError propagation in _has_thinking_dropdown (lines 190-195)."""
    mock_page.locator.return_value.count = AsyncMock(return_value=1)

    # Mock expect_async to raise CancelledError
    import asyncio

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

        # Should re-raise CancelledError (line 191)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._has_thinking_dropdown()

    # Test outer CancelledError (line 195)
    mock_page.locator.return_value.count = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    with pytest.raises(asyncio.CancelledError):
        await mock_controller._has_thinking_dropdown()


@pytest.mark.asyncio
async def test_set_thinking_level_listbox_close_fallback(mock_controller, mock_page):
    """Test listbox close fallback with keyboard escape (lines 243-250)."""
    trigger = AsyncMock()
    option = AsyncMock()
    listbox = AsyncMock()

    locator_calls = [trigger, option, listbox]
    mock_page.locator.side_effect = locator_calls

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    # Simulate listbox not closing automatically (line 242 exception)
    mock_expect.return_value.to_be_hidden = AsyncMock(
        side_effect=Exception("Listbox still visible")
    )

    trigger.locator.return_value.inner_text = AsyncMock(return_value="High")
    mock_page.keyboard.press = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_level("High", check_disconnect_mock)

        # Should press Escape key (line 247)
        mock_page.keyboard.press.assert_called_with("Escape")


@pytest.mark.asyncio
async def test_set_thinking_level_value_verification_mismatch(
    mock_controller, mock_page
):
    """Test value verification mismatch warning (lines 255, 262)."""
    trigger = AsyncMock()
    option = AsyncMock()
    listbox = AsyncMock()

    # Setup trigger to return mismatched value
    value_locator = AsyncMock()
    value_locator.inner_text = AsyncMock(return_value="Low")
    trigger.locator = MagicMock(return_value=value_locator)
    trigger.scroll_into_view_if_needed = AsyncMock()
    trigger.click = AsyncMock()

    option.click = AsyncMock()

    locator_call_count = [0]

    def locator_side_effect(selector):
        locator_call_count[0] += 1
        if locator_call_count[0] == 1:  # First call for trigger
            return trigger
        elif locator_call_count[0] == 2:  # Second call for option
            return option
        else:  # Third call for listbox
            return listbox

    mock_page.locator.side_effect = locator_side_effect

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_be_hidden = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_level("High", check_disconnect_mock)

        # Should log warning (line 257-259)
        mock_controller.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_set_thinking_level_client_disconnect(mock_controller, mock_page):
    """Test ClientDisconnectedError handling in _set_thinking_level (lines 262, 265)."""
    from models import ClientDisconnectedError

    trigger = AsyncMock()
    trigger.click = AsyncMock(side_effect=ClientDisconnectedError("Client gone"))

    mock_page.locator.return_value = trigger

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise ClientDisconnectedError (line 265)
        with pytest.raises(ClientDisconnectedError):
            await mock_controller._set_thinking_level("High", check_disconnect_mock)


@pytest.mark.asyncio
async def test_set_thinking_budget_value_evaluate_exception(mock_controller, mock_page):
    """Test evaluate exception handling in _set_thinking_budget_value (lines 336-339)."""
    import asyncio

    input_el = AsyncMock()
    mock_page.locator.return_value = input_el
    mock_page.evaluate = AsyncMock(side_effect=Exception("Evaluate failed"))

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_have_value = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should catch exception and continue (line 338)
        await mock_controller._set_thinking_budget_value(5000, check_disconnect_mock)

        # Should still call fill
        input_el.fill.assert_called()

    # Test CancelledError in evaluate (line 336-337)
    mock_page.evaluate = AsyncMock(side_effect=asyncio.CancelledError())
    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await mock_controller._set_thinking_budget_value(
                5000, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_set_thinking_budget_value_verification_int_exception(
    mock_controller, mock_page
):
    """Test int parsing exception in verification fallback (lines 357-358)."""
    input_el = AsyncMock()
    mock_page.locator.return_value = input_el

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_have_value = AsyncMock(
        side_effect=Exception("Mismatch")
    )

    # Return non-numeric string (line 357 exception)
    input_el.input_value = AsyncMock(return_value="not_a_number")
    input_el.get_attribute = AsyncMock(return_value=None)

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._set_thinking_budget_value(5000, check_disconnect_mock)

        # Should log warning (line 403-405)
        mock_controller.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_set_thinking_budget_value_fallback_cancelled_error(
    mock_controller, mock_page
):
    """Test CancelledError in fallback evaluation (lines 389-392, 399)."""
    import asyncio

    input_el = AsyncMock()
    mock_page.locator.return_value = input_el

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()
    mock_expect.return_value.to_have_value = AsyncMock(
        side_effect=Exception("Mismatch")
    )

    input_el.input_value = AsyncMock(return_value="8000")
    input_el.get_attribute = AsyncMock(return_value="8000")

    # Mock page.evaluate to raise CancelledError in fallback path (line 389)
    mock_page.evaluate = AsyncMock(side_effect=asyncio.CancelledError())

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise CancelledError (line 390)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._set_thinking_budget_value(
                10000, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_set_thinking_budget_value_top_level_errors(mock_controller, mock_page):
    """Test top-level error handling in _set_thinking_budget_value (lines 407-412)."""
    import asyncio

    from models import ClientDisconnectedError

    # Test CancelledError at top level (line 408)
    input_el = AsyncMock()
    mock_page.locator.return_value = input_el

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise CancelledError (line 409)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._set_thinking_budget_value(
                5000, check_disconnect_mock
            )

    # Test ClientDisconnectedError (line 411-412)
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=ClientDisconnectedError("Client gone")
    )

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise ClientDisconnectedError (line 412)
        with pytest.raises(ClientDisconnectedError):
            await mock_controller._set_thinking_budget_value(
                5000, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_scroll_exception(
    mock_controller, mock_page
):
    """Test scroll_into_view_if_needed exception handling (lines 438)."""

    toggle = AsyncMock()
    toggle.scroll_into_view_if_needed = AsyncMock(
        side_effect=Exception("Scroll failed")
    )
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should catch exception and continue (line 439)
        await mock_controller._control_thinking_mode_toggle(True, check_disconnect_mock)

        # Should still attempt click
        toggle.click.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_click_cancelled_error(
    mock_controller, mock_page
):
    """Test CancelledError during toggle click (lines 457-458)."""
    import asyncio

    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock(side_effect=asyncio.CancelledError())
    toggle.scroll_into_view_if_needed = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise CancelledError (line 458)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._control_thinking_mode_toggle(
                True, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_fallback_success(
    mock_controller, mock_page
):
    """Test successful fallback to aria-label based toggle click."""
    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(side_effect=["false", "true"])  # Before and after
    toggle.click = AsyncMock(side_effect=Exception("Click failed"))
    toggle.scroll_into_view_if_needed = AsyncMock()

    alt_toggle = AsyncMock()
    alt_toggle.count = AsyncMock(return_value=1)
    alt_toggle.click = AsyncMock()  # Success on fallback

    locator_call_count = [0]

    def locator_side_effect(selector):
        locator_call_count[0] += 1
        if "button" in selector and "switch" in selector:
            return toggle
        if 'aria-label="Toggle thinking mode"' in selector:
            return alt_toggle
        # Old fallback path
        root = MagicMock()
        root.locator.return_value = MagicMock()
        return root

    mock_page.locator.side_effect = locator_side_effect

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should succeed via fallback
        result = await mock_controller._control_thinking_mode_toggle(
            True, check_disconnect_mock
        )

        # Verify alt_toggle click was called (fallback)
        alt_toggle.click.assert_called()
        assert result is True


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_verification_failure(
    mock_controller, mock_page
):
    """Test verification failure after toggle click (lines 478-481)."""
    toggle = AsyncMock()
    # Simulate toggle not changing state
    toggle.get_attribute = AsyncMock(side_effect=["false", "false"])
    toggle.click = AsyncMock()
    toggle.scroll_into_view_if_needed = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        result = await mock_controller._control_thinking_mode_toggle(
            True, check_disconnect_mock
        )

        # Should log warning and return False (lines 483-486)
        mock_controller.logger.warning.assert_called()
        assert result is False


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_already_correct_state(
    mock_controller, mock_page
):
    """Test toggle already in desired state (lines 488-489)."""
    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(return_value="true")
    toggle.scroll_into_view_if_needed = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        result = await mock_controller._control_thinking_mode_toggle(
            True, check_disconnect_mock
        )

        # Should not click and return True (line 489)
        toggle.click.assert_not_called()
        assert result is True


@pytest.mark.asyncio
async def test_control_thinking_mode_toggle_top_level_errors(
    mock_controller, mock_page
):
    """Test top-level error handling in _control_thinking_mode_toggle (lines 497-503)."""
    import asyncio

    from playwright.async_api import TimeoutError

    from models import ClientDisconnectedError

    # Test TimeoutError (lines 491-495)
    mock_page.locator.return_value = AsyncMock()

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=TimeoutError("Not found")
    )

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        result = await mock_controller._control_thinking_mode_toggle(
            True, check_disconnect_mock
        )

        # Should return False and log warning (lines 492-495)
        mock_controller.logger.warning.assert_called()
        assert result is False

    # Test CancelledError (lines 497-498)
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await mock_controller._control_thinking_mode_toggle(
                True, check_disconnect_mock
            )

    # Test ClientDisconnectedError (lines 501-502)
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=ClientDisconnectedError("Client gone")
    )

    with (
        patch(
            "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
        ),
        patch(
            "browser_utils.page_controller_modules.thinking.save_error_snapshot",
            AsyncMock(),
        ),
    ):
        mock_controller._check_disconnect = AsyncMock()

        with pytest.raises(ClientDisconnectedError):
            await mock_controller._control_thinking_mode_toggle(
                True, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_scroll_exception(
    mock_controller, mock_page
):
    """Test scroll exception in _control_thinking_budget_toggle (lines 523)."""
    toggle = AsyncMock()
    toggle.scroll_into_view_if_needed = AsyncMock(
        side_effect=Exception("Scroll failed")
    )
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should catch exception and continue (line 524)
        await mock_controller._control_thinking_budget_toggle(
            True, check_disconnect_mock
        )

        # Should still attempt click
        toggle.click.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_click_cancelled_error(
    mock_controller, mock_page
):
    """Test CancelledError during budget toggle click (lines 543-544)."""
    import asyncio

    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(return_value="false")
    toggle.click = AsyncMock(side_effect=asyncio.CancelledError())
    toggle.scroll_into_view_if_needed = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise CancelledError (line 544)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._control_thinking_budget_toggle(
                True, check_disconnect_mock
            )


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_fallback_success(
    mock_controller, mock_page
):
    """Test successful fallback to aria-label based toggle click."""
    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(side_effect=["false", "true"])  # Before and after
    toggle.click = AsyncMock(side_effect=Exception("Click failed"))
    toggle.scroll_into_view_if_needed = AsyncMock()

    alt_toggle = AsyncMock()
    alt_toggle.count = AsyncMock(return_value=1)
    alt_toggle.click = AsyncMock()  # Success on fallback

    def locator_side_effect(selector):
        if "button" in selector and "switch" in selector:
            return toggle
        if 'aria-label="Toggle thinking budget between auto and manual"' in selector:
            return alt_toggle
        # Old fallback path
        root = MagicMock()
        root.locator.return_value = MagicMock()
        return root

    mock_page.locator.side_effect = locator_side_effect

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should succeed via fallback
        await mock_controller._control_thinking_budget_toggle(
            True, check_disconnect_mock
        )

        # Verify alt_toggle click was called (fallback)
        alt_toggle.click.assert_called()


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_already_correct(
    mock_controller, mock_page
):
    """Test budget toggle already in desired state (lines 572-573)."""
    toggle = AsyncMock()
    toggle.get_attribute = AsyncMock(return_value="true")
    toggle.scroll_into_view_if_needed = AsyncMock()

    mock_page.locator.return_value = toggle

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock()

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        await mock_controller._control_thinking_budget_toggle(
            True, check_disconnect_mock
        )

        # Should not click (line 572)
        toggle.click.assert_not_called()
        mock_controller.logger.info.assert_any_call(
            unittest.mock.ANY
        )  # Log "already in desired state"


@pytest.mark.asyncio
async def test_control_thinking_budget_toggle_top_level_errors(
    mock_controller, mock_page
):
    """Test top-level error handling in _control_thinking_budget_toggle (lines 574-579)."""
    import asyncio

    from models import ClientDisconnectedError

    # Test CancelledError (lines 575-576)
    mock_page.locator.return_value = AsyncMock()

    mock_expect = MagicMock()
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    check_disconnect_mock = MagicMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise CancelledError (line 576)
        with pytest.raises(asyncio.CancelledError):
            await mock_controller._control_thinking_budget_toggle(
                True, check_disconnect_mock
            )

    # Test ClientDisconnectedError (lines 578-579)
    mock_expect.return_value.to_be_visible = AsyncMock(
        side_effect=ClientDisconnectedError("Client gone")
    )

    with patch(
        "browser_utils.page_controller_modules.thinking.expect_async", mock_expect
    ):
        mock_controller._check_disconnect = AsyncMock()

        # Should re-raise ClientDisconnectedError (line 579)
        with pytest.raises(ClientDisconnectedError):
            await mock_controller._control_thinking_budget_toggle(
                True, check_disconnect_mock
            )


# --- Additional Coverage Tests for Uncovered Lines ---


@pytest.mark.asyncio
async def test_handle_thinking_budget_non_thinking_category(mock_controller):
    """Test early return for NON_THINKING category (lines 66-67)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.NON_THINKING
    )
    mock_controller._control_thinking_mode_toggle = AsyncMock()
    mock_controller._control_thinking_budget_toggle = AsyncMock()

    # Should return early without calling any toggles
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "high"}, "gemini-2.0-flash", MagicMock(return_value=False)
    )

    mock_controller._control_thinking_mode_toggle.assert_not_called()
    mock_controller._control_thinking_budget_toggle.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_flash_string_numeric_parsing(mock_controller):
    """Test Flash 4-level string numeric parsing (lines 149-163)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL_FLASH
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test string numeric values for Flash 4-level model
    test_cases = [
        ("16000", "high"),      # String >= 16000 -> high
        ("20000", "high"),      # String > 16000 -> high
        ("8000", "medium"),     # String >= 8000 -> medium
        ("10000", "medium"),    # String between 8000-16000 -> medium
        ("1024", "low"),        # String >= 1024 -> low
        ("2000", "low"),        # String between 1024-8000 -> low
        ("500", "minimal"),     # String < 1024 -> minimal
        ("100", "minimal"),     # String well below 1024 -> minimal
        ("none", "high"),       # "none" maps to "high" for Flash (lines 149-150)
        ("-1", "high"),         # "-1" maps to "high" (lines 149-150)
    ]

    for input_value, expected_level in test_cases:
        mock_controller._set_thinking_level.reset_mock()
        await mock_controller._handle_thinking_budget(
            {"reasoning_effort": input_value},
            "gemini-3-flash-preview",
            MagicMock(return_value=False),
        )
        mock_controller._set_thinking_level.assert_called_with(
            expected_level, unittest.mock.ANY
        ), f"Failed for input '{input_value}': expected '{expected_level}'"


@pytest.mark.asyncio 
async def test_handle_thinking_budget_pro_string_exception(mock_controller):
    """Test Pro level string parsing exception path (lines 174-175)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test string that can't be parsed as int
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": "invalid_string"},
        "gemini-3-pro",
        MagicMock(return_value=False),
    )

    # Should not call _set_thinking_level (level_to_set is None)
    mock_controller._set_thinking_level.assert_not_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_pro_string_numeric(mock_controller):
    """Test Pro level string numeric parsing (lines 171-175)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Test string numeric values for Pro 2-level model
    test_cases = [
        ("8000", "high"),       # String >= 8000 -> high
        ("10000", "high"),      # String > 8000 -> high
        ("7999", "low"),        # String < 8000 -> low
        ("100", "low"),         # String well below 8000 -> low
    ]

    for input_value, expected_level in test_cases:
        mock_controller._set_thinking_level.reset_mock()
        await mock_controller._handle_thinking_budget(
            {"reasoning_effort": input_value},
            "gemini-3-pro",
            MagicMock(return_value=False),
        )
        mock_controller._set_thinking_level.assert_called_with(
            expected_level, unittest.mock.ANY
        ), f"Failed for input '{input_value}': expected '{expected_level}'"


@pytest.mark.asyncio
async def test_handle_thinking_budget_default_level_none(mock_controller):
    """Test default level assignment when reasoning_effort is None (lines 193-200)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Pass None reasoning_effort to trigger default level logic (line 101, 191-200)
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": None},
        "gemini-3-pro",
        MagicMock(return_value=False),
    )

    # Should use DEFAULT_THINKING_LEVEL_PRO
    mock_controller._set_thinking_level.assert_called()


@pytest.mark.asyncio
async def test_handle_thinking_budget_default_level_flash(mock_controller):
    """Test default level assignment for Flash model (lines 193-196)."""
    mock_controller._get_thinking_category = MagicMock(
        return_value=ThinkingCategory.THINKING_LEVEL_FLASH
    )
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()

    # Pass None reasoning_effort to trigger default level logic
    await mock_controller._handle_thinking_budget(
        {"reasoning_effort": None},
        "gemini-3-flash",
        MagicMock(return_value=False),
    )

    # Should use DEFAULT_THINKING_LEVEL_FLASH
    mock_controller._set_thinking_level.assert_called()
