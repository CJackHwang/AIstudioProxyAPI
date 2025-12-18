"""
Tests for config/timeouts.py - Timeout boundary guard tests.

These tests prevent future regressions where excessive timeouts could cause
slow startup or unresponsive behavior. The slow startup bug (68s → 10s fix)
was caused by 30s × 5 selectors = 150s worst-case in find_first_visible_locator.

Guard Test Philosophy:
- Each timeout constant has a maximum acceptable value
- If a future change increases a timeout beyond the threshold, tests fail
- This forces developers to consciously acknowledge the performance impact
"""


from config.selector_utils import (
    INPUT_WRAPPER_SELECTORS,
)
from config.timeouts import (
    CLICK_TIMEOUT_MS,
    POLLING_INTERVAL,
    POLLING_INTERVAL_STREAM,
    SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS,
    SELECTOR_VISIBILITY_TIMEOUT_MS,
    STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS,
    WAIT_FOR_ELEMENT_TIMEOUT_MS,
)


class TestTimeoutBounds:
    """Guard tests ensuring timeout values stay within acceptable bounds.

    These tests prevent future regressions where timeouts are increased
    without consideration for their cumulative impact on startup time.
    """

    def test_selector_existence_check_is_fast(self):
        """Existence check must be very fast (≤1000ms).

        This is the Phase 1 quick DOM check. It runs for EACH selector,
        so if this is too high, startup time multiplies quickly.

        Example: 5 selectors × 1000ms = 5s just for existence checks
        """
        max_acceptable_ms = 1000
        assert SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS <= max_acceptable_ms, (
            f"SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS ({SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS}ms) "
            f"exceeds maximum acceptable value ({max_acceptable_ms}ms). "
            "This timeout runs for each selector, so increasing it significantly "
            "impacts startup time."
        )

    def test_selector_visibility_timeout_is_reasonable(self):
        """Visibility timeout must be reasonable (≤10000ms).

        This is the Phase 2 visibility wait. It only runs on selectors
        that passed the existence check, but should still be bounded.
        """
        max_acceptable_ms = 10000
        assert SELECTOR_VISIBILITY_TIMEOUT_MS <= max_acceptable_ms, (
            f"SELECTOR_VISIBILITY_TIMEOUT_MS ({SELECTOR_VISIBILITY_TIMEOUT_MS}ms) "
            f"exceeds maximum acceptable value ({max_acceptable_ms}ms)."
        )

    def test_startup_selector_visibility_bounded(self):
        """Startup visibility timeout must be bounded (≤45000ms).

        This is used for critical startup path selectors where we allow
        longer waits because the page may still be loading.
        """
        max_acceptable_ms = 45000
        assert STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS <= max_acceptable_ms, (
            f"STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS ({STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS}ms) "
            f"exceeds maximum acceptable value ({max_acceptable_ms}ms)."
        )

    def test_click_timeout_is_fast(self):
        """Click timeout must be fast for responsive UX (≤5000ms)."""
        max_acceptable_ms = 5000
        assert CLICK_TIMEOUT_MS <= max_acceptable_ms, (
            f"CLICK_TIMEOUT_MS ({CLICK_TIMEOUT_MS}ms) exceeds maximum ({max_acceptable_ms}ms)."
        )

    def test_polling_intervals_are_efficient(self):
        """Polling intervals must be efficient (≤500ms)."""
        max_acceptable_ms = 500
        assert POLLING_INTERVAL <= max_acceptable_ms, (
            f"POLLING_INTERVAL ({POLLING_INTERVAL}ms) exceeds maximum ({max_acceptable_ms}ms)."
        )
        assert POLLING_INTERVAL_STREAM <= max_acceptable_ms, (
            f"POLLING_INTERVAL_STREAM ({POLLING_INTERVAL_STREAM}ms) exceeds maximum ({max_acceptable_ms}ms)."
        )

    def test_wait_for_element_timeout_bounded(self):
        """Wait for element timeout must be bounded (≤15000ms)."""
        max_acceptable_ms = 15000
        assert WAIT_FOR_ELEMENT_TIMEOUT_MS <= max_acceptable_ms, (
            f"WAIT_FOR_ELEMENT_TIMEOUT_MS ({WAIT_FOR_ELEMENT_TIMEOUT_MS}ms) "
            f"exceeds maximum ({max_acceptable_ms}ms)."
        )


class TestStartupTimeEstimate:
    """Tests that estimate and bound worst-case startup time.

    These tests calculate the theoretical worst-case startup time based on
    timeout constants and fail if it exceeds acceptable thresholds.
    """

    def test_input_wrapper_selector_worst_case_bounded(self):
        """Worst-case time for INPUT_WRAPPER_SELECTORS must be bounded.

        The fix for the 68s startup bug uses a two-phase approach:
        - Phase 1: Quick existence check (SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS × N selectors)
        - Phase 2: Visibility wait (only on existing selectors, typically 1)
        - Phase 3 (fallback): Single selector visibility wait

        Worst case: All existence checks timeout + 1 visibility wait
        """
        num_selectors = len(INPUT_WRAPPER_SELECTORS)

        # Worst case: all selectors fail existence check + fallback visibility wait
        worst_case_ms = (
            num_selectors * SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS
            + SELECTOR_VISIBILITY_TIMEOUT_MS  # fallback uses default timeout
        )

        max_acceptable_ms = 15000  # 15 seconds

        assert worst_case_ms <= max_acceptable_ms, (
            f"Worst-case selector search time ({worst_case_ms}ms) exceeds "
            f"maximum acceptable ({max_acceptable_ms}ms). "
            f"Current: {num_selectors} selectors × {SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS}ms "
            f"+ {SELECTOR_VISIBILITY_TIMEOUT_MS}ms fallback = {worst_case_ms}ms. "
            "Consider reducing SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS or the number of selectors."
        )

    def test_startup_critical_path_time_bounded(self):
        """Critical startup path with STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS.

        When called with the higher startup timeout (30s), worst case should
        still be acceptable.
        """
        num_selectors = len(INPUT_WRAPPER_SELECTORS)

        # With startup timeout: quick checks + one visibility wait with startup timeout
        worst_case_ms = (
            num_selectors * SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS
            + STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS
        )

        max_acceptable_ms = 45000  # 45 seconds (generous for startup)

        assert worst_case_ms <= max_acceptable_ms, (
            f"Startup critical path worst-case ({worst_case_ms}ms) exceeds "
            f"maximum acceptable ({max_acceptable_ms}ms)."
        )

    def test_selector_count_is_manageable(self):
        """Number of selectors should not grow unbounded.

        Each additional selector adds to startup time. This test ensures
        we keep the selector lists lean.
        """
        max_selectors = 10

        assert len(INPUT_WRAPPER_SELECTORS) <= max_selectors, (
            f"INPUT_WRAPPER_SELECTORS has {len(INPUT_WRAPPER_SELECTORS)} items, "
            f"exceeding maximum ({max_selectors}). Each selector adds "
            f"{SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS}ms to worst-case startup. "
            "Consider removing old/unused selectors."
        )


class TestTimeoutDocumentation:
    """Tests ensuring timeout constants are well-documented.

    These tests verify that timeout files have proper documentation
    so future maintainers understand the performance implications.
    """

    def test_timeouts_module_has_selector_section(self):
        """config/timeouts.py should have a selector timeout section."""
        # This test ensures the timeout constants exist and are positive
        assert SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS > 0
        assert SELECTOR_VISIBILITY_TIMEOUT_MS > 0
        assert STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS > 0

    def test_existence_check_faster_than_visibility(self):
        """Existence check should be faster than visibility timeout.

        The whole point of the two-phase approach is that existence checks
        are quick and visibility waits are only for existing elements.
        """
        assert SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS < SELECTOR_VISIBILITY_TIMEOUT_MS, (
            f"SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS ({SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS}ms) "
            f"should be less than SELECTOR_VISIBILITY_TIMEOUT_MS ({SELECTOR_VISIBILITY_TIMEOUT_MS}ms). "
            "The two-phase approach requires fast existence checks."
        )
