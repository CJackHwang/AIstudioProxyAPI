# -*- coding: utf-8 -*-
"""
Tests for logging_utils/core/rendering.py

Covers:
- GridFormatter shutdown safety
- PlainGridFormatter
- SemanticHighlighter
- BurstBuffer suppression
"""

import logging
import sys
from unittest.mock import patch

from logging_utils.core.rendering import (
    BurstBuffer,
    GridFormatter,
    PlainGridFormatter,
    SemanticHighlighter,
    normalize_source,
)


class TestNormalizeSource:
    """Tests for normalize_source function."""

    def test_known_source_mapping(self):
        """Test that known sources are mapped correctly."""
        assert normalize_source("api") == "API  "
        assert normalize_source("API") == "API  "
        assert normalize_source("launcher") == "LNCHR"
        assert normalize_source("LAUNCHER") == "LNCHR"

    def test_unknown_source_truncated(self):
        """Test that unknown sources are truncated to 5 chars."""
        result = normalize_source("verylongsourcename")
        assert len(result) == 5
        assert result == "VERYL"

    def test_short_source_padded(self):
        """Test that short sources are padded to 5 chars."""
        result = normalize_source("ab")
        assert len(result) == 5
        assert result == "AB   "


class TestSemanticHighlighter:
    """Tests for SemanticHighlighter."""

    def test_highlight_disabled(self):
        """Test that highlighting can be disabled."""
        text = "Test message with 'quotes' and numbers 123"
        result = SemanticHighlighter.highlight(text, colorize=False)
        assert result == text

    def test_highlight_tags(self):
        """Test that tags like [UI] are highlighted."""
        text = "[UI] Some message"
        result = SemanticHighlighter.highlight(text, colorize=True)
        # Should contain ANSI codes
        assert "\x1b[" in result
        assert "UI" in result

    def test_highlight_booleans(self):
        """Test that True/False/None are highlighted."""
        text = "Value is True and other is False"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert "\x1b[" in result
        assert "True" in result
        assert "False" in result

    def test_highlight_status_phrases(self):
        """Test that status phrases like error/success are highlighted."""
        text = "Operation successful"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert "\x1b[" in result
        assert "successful" in result


class TestBurstBuffer:
    """Tests for BurstBuffer suppression."""

    def test_first_message_returned(self):
        """Test that first message is returned immediately."""
        buffer = BurstBuffer()
        prev, current = buffer.process("key1", "formatted line 1")
        assert prev == "formatted line 1"
        assert current is None

    def test_duplicate_suppressed(self):
        """Test that duplicate messages are suppressed."""
        buffer = BurstBuffer()
        buffer.process("key1", "line 1")

        # Second identical message
        prev, current = buffer.process("key1", "line 1")
        assert prev is None
        assert current is None

    def test_different_message_returns_new_message(self):
        """Test that different message returns the new message."""
        buffer = BurstBuffer()
        buffer.process("key1", "line 1")

        # Different message with no duplicates
        # When prev_count == 1, returns (formatted_line, None)
        # meaning the NEW line is returned in prev, current is None
        prev, current = buffer.process("key2", "line 2")
        assert prev == "line 2"
        assert current is None

    def test_flush_with_count(self):
        """Test flush returns count when duplicates exist."""
        buffer = BurstBuffer()
        buffer.process("key1", "line 1")
        buffer.process("key1", "line 1")  # Duplicate
        buffer.process("key1", "line 1")  # Another duplicate

        result = buffer.flush()
        assert result is not None
        assert "Repeated" in result
        assert "3" in result

    def test_flush_no_duplicates(self):
        """Test flush returns None when no duplicates."""
        buffer = BurstBuffer()
        buffer.process("key1", "line 1")

        result = buffer.flush()
        # No repeat count if only one message
        assert result is None


class TestGridFormatterShutdownSafety:
    """Tests for GridFormatter shutdown safety - prevent ImportError during shutdown."""

    def test_format_returns_raw_message_when_meta_path_is_none(self):
        """Test that format returns raw message when sys.meta_path is None."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message during shutdown",
            args=(),
            exc_info=None,
        )

        with patch.object(sys, "meta_path", None):
            result = formatter.format(record)

        # Should return the raw message, not crash
        assert result == "Test message during shutdown"

    def test_format_works_normally_when_not_shutting_down(self):
        """Test that format works normally when Python is not shutting down."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should contain timestamp, level, etc.
        assert "INF" in result
        assert "Normal message" in result

    def test_format_skips_separator_lines(self):
        """Test that separator lines (---) are skipped."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="--- Separator ---",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert result == ""


class TestPlainGridFormatter:
    """Tests for PlainGridFormatter."""

    def test_format_no_ansi_codes(self):
        """Test that plain formatter produces no ANSI codes."""
        formatter = PlainGridFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Plain message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should not contain ANSI escape codes
        assert "\x1b[" not in result
        assert "INF" in result
        assert "Plain message" in result

    def test_format_skips_separator_lines(self):
        """Test that separator lines are skipped."""
        formatter = PlainGridFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="=== Separator ===",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert result == ""


class TestGridFormatterIntegration:
    """Integration tests for GridFormatter."""

    def test_format_with_context_vars(self):
        """Test formatter uses context variables."""
        from logging_utils.core.context import request_id_var, source_var

        formatter = GridFormatter(colorize=False, burst_suppression=False)

        req_token = request_id_var.set("abc1234")
        src_token = source_var.set("API")

        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Context test",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)

            assert "abc1234" in result
            assert "API" in result
            assert "Context test" in result
        finally:
            request_id_var.reset(req_token)
            source_var.reset(src_token)

    def test_format_all_log_levels(self):
        """Test formatter handles all log levels."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)

        levels = [
            (logging.DEBUG, "DBG"),
            (logging.INFO, "INF"),
            (logging.WARNING, "WRN"),
            (logging.ERROR, "ERR"),
            (logging.CRITICAL, "CRT"),
        ]

        for level, abbrev in levels:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=1,
                msg=f"Level {abbrev} message",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            assert abbrev in result, f"Expected {abbrev} in result for level {level}"
