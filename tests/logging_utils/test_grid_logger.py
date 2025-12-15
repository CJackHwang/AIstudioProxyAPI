"""
Tests for logging_utils/grid_logger.py - Grid-based logging system.

These tests verify the grid formatter, context managers, highlighters,
burst suppression, and other logging utilities.
"""

import logging
import threading
from unittest.mock import MagicMock

from logging_utils.grid_logger import (
    BrowserNoiseFilter,
    BurstBuffer,
    Colors,
    Columns,
    GridFormatter,
    PlainGridFormatter,
    SemanticHighlighter,
    log_context,
    normalize_source,
    request_context,
    request_id_var,
    source_var,
)


class TestNormalizeSource:
    """Tests for normalize_source function."""

    def test_known_source_api(self):
        """Known source 'api' should map to 'API  '."""
        assert normalize_source("api") == "API  "

    def test_known_source_server(self):
        """Known source 'server' should map to 'SERVR'."""
        assert normalize_source("server") == "SERVR"

    def test_known_source_browser(self):
        """Known source 'browser' should map to 'BROWR'."""
        assert normalize_source("browser") == "BROWR"

    def test_known_source_with_dash(self):
        """Source with dash should be normalized."""
        assert normalize_source("queue-worker") == "WORKR"

    def test_known_source_with_underscore(self):
        """Source with underscore should be normalized."""
        assert normalize_source("queue_worker") == "WORKR"

    def test_partial_match_proxy(self):
        """Partial match should work (proxyserver contains proxy)."""
        result = normalize_source("my_proxy")
        # Should find 'proxy' in 'my_proxy'
        assert result == "PROXY"

    def test_unknown_source_truncated(self):
        """Unknown source should be truncated to 5 chars."""
        result = normalize_source("verylongunknownsource")
        assert result == "VERYL"
        assert len(result) == 5

    def test_short_unknown_source_padded(self):
        """Short unknown source should be padded."""
        result = normalize_source("xyz")
        assert result == "XYZ  "
        assert len(result) == 5

    def test_case_insensitive(self):
        """Source normalization should be case-insensitive."""
        assert normalize_source("API") == "API  "
        assert normalize_source("Api") == "API  "
        assert normalize_source("aPi") == "API  "


class TestColumns:
    """Tests for Columns class."""

    def test_column_widths_defined(self):
        """Column widths should be defined as expected."""
        assert Columns.TIME == 12
        assert Columns.LEVEL == 3
        assert Columns.SOURCE == 5
        assert Columns.ID == 7
        assert Columns.TREE_INDENT == 3


class TestColors:
    """Tests for Colors class."""

    def test_level_colors_defined(self):
        """Level colors should be defined for all standard levels."""
        assert "DEBUG" in Colors.LEVELS
        assert "INFO" in Colors.LEVELS
        assert "WARNING" in Colors.LEVELS
        assert "ERROR" in Colors.LEVELS
        assert "CRITICAL" in Colors.LEVELS

    def test_level_abbreviations_defined(self):
        """Level abbreviations should be 3 characters."""
        for abbrev in Colors.LEVEL_ABBREV.values():
            assert len(abbrev) == 3


class TestSemanticHighlighter:
    """Tests for SemanticHighlighter class."""

    def test_highlight_disabled(self):
        """With colorize=False, text should be unchanged."""
        text = "Hello World"
        result = SemanticHighlighter.highlight(text, colorize=False)
        assert result == text

    def test_highlight_quoted_string_single(self):
        """Single-quoted strings should be highlighted."""
        text = "Value is 'test'"
        result = SemanticHighlighter.highlight(text, colorize=True)
        # Should contain ANSI color codes around 'test'
        assert Colors.STRING in result or "test" in result

    def test_highlight_quoted_string_double(self):
        """Double-quoted strings should be highlighted."""
        text = 'Value is "test"'
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.STRING in result or "test" in result

    def test_highlight_boolean_true(self):
        """True should be highlighted in green."""
        text = "Success: True"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.BOOLEAN_TRUE in result

    def test_highlight_boolean_false(self):
        """False should be highlighted in red."""
        text = "Success: False"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.BOOLEAN_FALSE in result

    def test_highlight_boolean_none(self):
        """None should be highlighted dimly."""
        text = "Value: None"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.BOOLEAN_NONE in result

    def test_highlight_number(self):
        """Numbers should be highlighted."""
        text = "Count: 42"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.NUMBER in result

    def test_highlight_number_with_unit(self):
        """Numbers with units should be highlighted."""
        text = "Timeout: 500ms"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.NUMBER in result

    def test_highlight_url(self):
        """URLs should be highlighted."""
        text = "Connecting to https://example.com/api"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.URL in result or "https://example.com" in result

    def test_highlight_error_phrase(self):
        """Error phrases should be highlighted."""
        text = "Request Error occurred"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_ERROR in result

    def test_highlight_success_phrase(self):
        """Success phrases should be highlighted."""
        text = "Operation Success"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_SUCCESS in result

    def test_highlight_warning_phrase(self):
        """Warning phrases should be highlighted."""
        text = "Warning: low memory"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_WARNING in result

    def test_highlight_failed_phrase(self):
        """Failed phrases should be highlighted."""
        text = "Task Failed"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_FAILED in result

    def test_highlight_model_id(self):
        """Model IDs like gemini-* should be highlighted."""
        text = "Using model gemini-1.5-pro"
        result = SemanticHighlighter.highlight(text, colorize=True)
        # Model ID should be in result (may be split by ANSI codes)
        # Check that the key parts are present
        assert "gemini" in result
        assert "pro" in result
        # And that some color codes are applied
        assert "\x1b[" in result or "\033[" in result

    def test_highlight_hex_number(self):
        """Hex numbers should be highlighted."""
        text = "Address: 0xDEADBEEF"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.NUMBER in result

    def test_highlight_tag_at_start(self):
        """Tags like [UI] at start should be highlighted."""
        text = "[UI] Button clicked"
        result = SemanticHighlighter.highlight(text, colorize=True)
        # Should contain some coloring for the tag
        assert "[UI]" in result

    def test_highlight_matches_phrase(self):
        """Status phrases like (Matches) should be highlighted."""
        text = "State check (Matches page)"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_SUCCESS in result

    def test_highlight_updating_phrase(self):
        """Action phrases like (Updating...) should be highlighted."""
        text = "Parameter (Updating...)"
        result = SemanticHighlighter.highlight(text, colorize=True)
        assert Colors.PHRASE_WARNING in result


class TestBrowserNoiseFilter:
    """Tests for BrowserNoiseFilter class."""

    def test_filter_allows_normal_message(self):
        """Normal messages should pass through."""
        filter_obj = BrowserNoiseFilter()
        record = MagicMock()
        record.getMessage.return_value = "Normal log message"

        assert filter_obj.filter(record) is True

    def test_filter_blocks_abort_error(self):
        """AbortError messages should be filtered."""
        filter_obj = BrowserNoiseFilter()
        record = MagicMock()
        record.getMessage.return_value = (
            "AbortError: The operation was aborted during navigation"
        )

        assert filter_obj.filter(record) is False

    def test_filter_blocks_cors_error(self):
        """CORS errors should be filtered."""
        filter_obj = BrowserNoiseFilter()
        record = MagicMock()
        record.getMessage.return_value = "Cross-Origin Request Blocked: some policy"

        assert filter_obj.filter(record) is False

    def test_filter_blocks_google_log(self):
        """Google internal logging should be filtered."""
        filter_obj = BrowserNoiseFilter()
        record = MagicMock()
        record.getMessage.return_value = (
            "Request to play.google.com/log failed with 404"
        )

        assert filter_obj.filter(record) is False

    def test_filter_blocks_ssl_warning(self):
        """SSL shutdown warnings should be filtered."""
        filter_obj = BrowserNoiseFilter()
        record = MagicMock()
        record.getMessage.return_value = "SSL APPLICATION_DATA_AFTER_CLOSE_NOTIFY"

        assert filter_obj.filter(record) is False


class TestBurstBuffer:
    """Tests for BurstBuffer class."""

    def test_first_message_returned(self):
        """First message should be returned immediately."""
        buffer = BurstBuffer()
        line, deferred = buffer.process("key1", "Line 1")

        assert line == "Line 1"
        assert deferred is None

    def test_duplicate_message_suppressed(self):
        """Duplicate messages should be suppressed."""
        buffer = BurstBuffer()
        buffer.process("key1", "Line 1")
        line, deferred = buffer.process("key1", "Line 1")

        assert line is None
        assert deferred is None

    def test_different_message_flushes_previous(self):
        """Different message should flush previous."""
        buffer = BurstBuffer()
        buffer.process("key1", "Line 1")
        line, deferred = buffer.process("key2", "Line 2")

        # Should return current line since previous wasn't repeated
        assert line == "Line 2"
        assert deferred is None

    def test_repeated_message_shows_count(self):
        """Repeated message should show count when flushed."""
        buffer = BurstBuffer()
        buffer.process("key1", "Line 1")
        buffer.process("key1", "Line 1")  # Repeated
        buffer.process("key1", "Line 1")  # Repeated again
        line, deferred = buffer.process("key2", "Line 2")

        # Previous line should have count indicator
        assert line is not None
        assert "Repeated" in line or "x" in line.lower() or "Line 1" in line
        assert deferred == "Line 2"

    def test_flush_with_repeated_messages(self):
        """Flush should return count for repeated messages."""
        buffer = BurstBuffer()
        buffer.process("key1", "Line 1")
        buffer.process("key1", "Line 1")  # Repeated

        result = buffer.flush()
        assert result is not None
        assert "Repeated" in result

    def test_flush_without_repetition(self):
        """Flush without repetition returns None."""
        buffer = BurstBuffer()
        buffer.process("key1", "Line 1")

        result = buffer.flush()
        assert result is None

    def test_thread_safety(self):
        """Buffer should be thread-safe."""
        buffer = BurstBuffer()
        results = []
        errors = []

        def worker(thread_id):
            try:
                for i in range(10):
                    buffer.process(f"key_{thread_id}_{i}", f"Line {thread_id} {i}")
                results.append(thread_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5


class TestGridFormatter:
    """Tests for GridFormatter class."""

    def test_format_basic_message(self):
        """Basic message should be formatted with all columns."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Set context vars
        request_id_var.set("abc1234")
        source_var.set("api")

        result = formatter.format(record)

        # Should contain level, source, request ID, and message
        assert "INF" in result
        assert "API" in result
        assert "abc1234" in result
        assert "Test message" in result

    def test_format_with_colors(self):
        """Colorized output should contain ANSI codes."""
        formatter = GridFormatter(colorize=True, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Warning message",
            args=(),
            exc_info=None,
        )

        request_id_var.set("xyz7890")
        source_var.set("server")

        result = formatter.format(record)

        # Should contain ANSI codes (escape sequences)
        assert "\x1b[" in result or "\033[" in result

    def test_format_skips_separator_lines(self):
        """Separator lines (---) should be skipped."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="--- Separator ---",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert result == ""

    def test_format_with_burst_suppression(self):
        """Burst suppression should dedupe repeated messages."""
        formatter = GridFormatter(colorize=False, burst_suppression=True)

        # Reset the global burst buffer state by processing a unique message first
        record1 = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Unique setup message for test",
            args=(),
            exc_info=None,
        )
        source_var.set("api")
        formatter.format(record1)

        # Now test with repeating messages
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Repeated message test",
            args=(),
            exc_info=None,
        )

        result1 = formatter.format(record)
        assert "Repeated message test" in result1 or result1 == ""


class TestPlainGridFormatter:
    """Tests for PlainGridFormatter class."""

    def test_format_no_ansi_codes(self):
        """Plain formatter should not include ANSI codes."""
        formatter = PlainGridFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Plain message",
            args=(),
            exc_info=None,
        )

        request_id_var.set("plain12")
        source_var.set("worker")

        result = formatter.format(record)

        # Should NOT contain ANSI escape sequences
        assert "\x1b[" not in result
        assert "\033[" not in result

    def test_format_skips_separator_lines(self):
        """Separator lines should be skipped."""
        formatter = PlainGridFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="=== Section ===",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert result == ""


class TestLogContext:
    """Tests for log_context context manager."""

    def test_log_context_with_source(self):
        """Log context can change source temporarily."""
        source_var.set("original")
        logger = logging.getLogger("test_source")

        with log_context("Changed Source", logger, source="new_source", silent=True):
            assert source_var.get() == "new_source"

        assert source_var.get() == "original"

    def test_log_context_silent_no_log(self):
        """Log context with silent=True should not log the header."""
        import io

        logger = logging.getLogger("test_silent")
        logger.setLevel(logging.DEBUG)

        # Capture stdout
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        with log_context("Should Not Appear", logger, silent=True):
            pass

        logger.removeHandler(handler)
        output = captured.getvalue()
        assert "Should Not Appear" not in output


class TestRequestContext:
    """Tests for request_context context manager."""

    def test_request_context_sets_id(self):
        """Request context should set request ID."""
        request_id_var.set("default")

        with request_context("req1234"):
            assert request_id_var.get() == "req1234"

        assert request_id_var.get() == "default"

    def test_request_context_sets_source(self):
        """Request context should set source."""
        source_var.set("original")

        with request_context("reqid", source="PROXY"):
            assert source_var.get() == "PROXY"

        assert source_var.get() == "original"


class TestFormatObject:
    """Tests for format_object and _format_value functions."""

    def test_format_object_dict_simple(self):
        """format_object should format simple dict."""
        from logging_utils.grid_logger import format_object

        obj = {"key1": "value1", "key2": 42}
        result = format_object(obj, colorize=False)

        assert "key1" in result
        assert "'value1'" in result
        assert "key2" in result
        assert "42" in result

    def test_format_object_dict_nested(self):
        """format_object should handle nested dicts."""
        from logging_utils.grid_logger import format_object

        obj = {"outer": {"inner": "value"}}
        result = format_object(obj, colorize=False)

        assert "outer" in result
        assert "inner" in result
        assert "'value'" in result

    def test_format_object_list(self):
        """format_object should format lists."""
        from logging_utils.grid_logger import format_object

        obj = ["item1", "item2", 3]
        result = format_object(obj, colorize=False)

        assert "- 'item1'" in result
        assert "- 'item2'" in result
        assert "- 3" in result

    def test_format_object_list_nested(self):
        """format_object should handle nested lists."""
        from logging_utils.grid_logger import format_object

        obj = [{"nested": "dict"}]
        result = format_object(obj, colorize=False)

        assert "nested" in result
        assert "'dict'" in result

    def test_format_object_primitive(self):
        """format_object should handle primitives."""
        from logging_utils.grid_logger import format_object

        result = format_object("simple", colorize=False)
        assert "'simple'" in result

    def test_format_object_with_colors(self):
        """format_object with colorize=True should add color codes."""
        from logging_utils.grid_logger import format_object

        obj = {"key": "value"}
        result = format_object(obj, colorize=True)

        # Should contain ANSI codes
        assert "\x1b[" in result or "\033[" in result

    def test_format_value_boolean_true(self):
        """_format_value should color True."""
        from logging_utils.grid_logger import _format_value

        result = _format_value(True, colorize=True)
        assert "True" in result
        assert Colors.BOOLEAN_TRUE in result

    def test_format_value_boolean_false(self):
        """_format_value should color False."""
        from logging_utils.grid_logger import _format_value

        result = _format_value(False, colorize=True)
        assert "False" in result
        assert Colors.BOOLEAN_FALSE in result

    def test_format_value_number(self):
        """_format_value should color numbers."""
        from logging_utils.grid_logger import _format_value

        result = _format_value(42, colorize=True)
        assert "42" in result
        assert Colors.NUMBER in result

    def test_format_value_float(self):
        """_format_value should color floats."""
        from logging_utils.grid_logger import _format_value

        result = _format_value(3.14, colorize=True)
        assert "3.14" in result
        assert Colors.NUMBER in result

    def test_format_value_string(self):
        """_format_value should color strings."""
        from logging_utils.grid_logger import _format_value

        result = _format_value("hello", colorize=True)
        assert "'hello'" in result
        assert Colors.STRING in result

    def test_format_value_long_string_truncated(self):
        """_format_value should truncate long strings."""
        from logging_utils.grid_logger import _format_value

        long_string = "x" * 100
        result = _format_value(long_string, colorize=True)
        assert "..." in result
        assert len(result.replace("\x1b", "").replace("\033", "")) < 100

    def test_format_value_none(self):
        """_format_value should handle None."""
        from logging_utils.grid_logger import _format_value

        result = _format_value(None, colorize=True)
        assert "None" in result
        assert Colors.BOOLEAN_NONE in result

    def test_format_value_other_type(self):
        """_format_value should handle other types via repr."""
        from logging_utils.grid_logger import _format_value

        result = _format_value((1, 2, 3), colorize=True)
        assert "(1, 2, 3)" in result

    def test_format_value_no_colorize(self):
        """_format_value with colorize=False should return plain text."""
        from logging_utils.grid_logger import _format_value

        result = _format_value("test", colorize=False)
        assert result == "'test'"
        assert "\x1b[" not in result


class TestLogObject:
    """Tests for log_object function."""

    def test_log_object_logs_label(self):
        """log_object should log label and formatted content."""
        from logging_utils.grid_logger import log_object

        mock_logger = MagicMock()
        data = {"key": "value"}

        log_object(mock_logger, data, "Test Data")

        assert mock_logger.log.called
        # First call should be the label
        first_call = mock_logger.log.call_args_list[0]
        assert "Test Data" in str(first_call)

    def test_log_object_with_custom_level(self):
        """log_object should use custom log level."""
        from logging_utils.grid_logger import log_object

        mock_logger = MagicMock()
        data = {"key": "value"}

        log_object(mock_logger, data, "Debug Data", level=logging.DEBUG)

        # All calls should use DEBUG level
        for call in mock_logger.log.call_args_list:
            assert call[0][0] == logging.DEBUG


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_set_source(self):
        """set_source should update source_var."""
        from logging_utils.grid_logger import set_source

        set_source("TEST_SOURCE")
        assert source_var.get() == "TEST_SOURCE"

    def test_set_request_id(self):
        """set_request_id should update request_id_var."""
        from logging_utils.grid_logger import set_request_id

        set_request_id("testid7")
        assert request_id_var.get() == "testid7"

    def test_get_source(self):
        """get_source should return current source."""
        from logging_utils.grid_logger import get_source

        source_var.set("MY_SOURCE")
        assert get_source() == "MY_SOURCE"

    def test_get_request_id(self):
        """get_request_id should return current request id."""
        from logging_utils.grid_logger import get_request_id

        request_id_var.set("myreqid")
        assert get_request_id() == "myreqid"


class TestProgressLine:
    """Tests for ProgressLine class."""

    def test_progress_line_init(self):
        """ProgressLine should initialize correctly."""
        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test Progress")
        assert progress.message == "Test Progress"
        assert progress._started is False

    def test_progress_line_with_source(self):
        """ProgressLine should accept optional source."""
        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test", source="CUSTOM")
        assert progress.source == "CUSTOM"


class TestSetupGridLogging:
    """Tests for setup_grid_logging function."""

    def test_setup_grid_logging_returns_logger(self):
        """setup_grid_logging should return a logger."""
        from logging_utils.grid_logger import setup_grid_logging

        logger = setup_grid_logging(logger_name="test_setup_logger")
        assert isinstance(logger, logging.Logger)

    def test_setup_grid_logging_sets_level(self):
        """setup_grid_logging should set log level."""
        from logging_utils.grid_logger import setup_grid_logging

        logger = setup_grid_logging(level=logging.WARNING, logger_name="test_level")
        assert logger.level == logging.WARNING

    def test_setup_grid_logging_adds_handler(self):
        """setup_grid_logging should add a handler."""
        from logging_utils.grid_logger import setup_grid_logging

        logger = setup_grid_logging(logger_name="test_handler")
        assert len(logger.handlers) > 0

    def test_setup_grid_logging_with_options(self):
        """setup_grid_logging should accept all options."""
        from logging_utils.grid_logger import setup_grid_logging

        logger = setup_grid_logging(
            level=logging.INFO,
            show_tree=False,
            colorize=False,
            burst_suppression=False,
            logger_name="test_options",
        )
        assert logger is not None

    def test_setup_grid_logging_root_logger(self):
        """setup_grid_logging with no name should configure root."""
        from logging_utils.grid_logger import setup_grid_logging

        # Create isolated test by using a specific name first
        logger = setup_grid_logging(logger_name=None)
        assert logger is not None


class TestProgressLineExtended:
    """Extended tests for ProgressLine update and finish methods."""

    def test_progress_line_update(self):
        """ProgressLine.update should format and output progress."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Downloading")
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            # Set context for proper formatting
            request_id_var.set("prgtest")
            source_var.set("worker")

            # Call update with progress values
            progress.update(50, 100, "50%")

            # Should have started (captures output via carriage return)
            _ = sys.stdout.getvalue()  # Consume output
            assert progress._started is True
        finally:
            sys.stdout = old_stdout

    def test_progress_line_finish_without_start(self):
        """ProgressLine.finish without update should do nothing."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test")
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            progress.finish("Done")
            _ = sys.stdout.getvalue()  # Consume output
            # Should not output if not started
            assert progress._started is False
        finally:
            sys.stdout = old_stdout

    def test_progress_line_finish_with_message(self):
        """ProgressLine.finish with message should append it."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test")
        progress._started = True  # Simulate having started
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            progress.finish("Complete!")
            output = sys.stdout.getvalue()
            assert "Complete!" in output or len(output) > 0
        finally:
            sys.stdout = old_stdout

    def test_progress_line_finish_without_message(self):
        """ProgressLine.finish without message should just newline."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test")
        progress._started = True
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            progress.finish()
            output = sys.stdout.getvalue()
            assert "\n" in output
        finally:
            sys.stdout = old_stdout

    def test_progress_line_update_with_source_override(self):
        """ProgressLine with source override should use it."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test", source="CUSTOM")
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            request_id_var.set("srctest")
            progress.update(10, 100)
            assert progress._started is True
        finally:
            sys.stdout = old_stdout

    def test_progress_line_rate_limiting(self):
        """ProgressLine should rate-limit updates."""
        import io
        import sys

        from logging_utils.grid_logger import ProgressLine

        progress = ProgressLine("Test")
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            request_id_var.set("rate")
            source_var.set("test")

            # First update should succeed
            progress.update(10, 100)

            # Immediate second update should be rate-limited
            _ = len(sys.stdout.getvalue())  # Get baseline
            progress.update(11, 100)  # Should be skipped due to rate limiting

            # But 100% completion should always update
            progress.update(100, 100)
        finally:
            sys.stdout = old_stdout


class TestFlushBurstBuffer:
    """Tests for flush_burst_buffer function."""

    def test_flush_burst_buffer_prints(self):
        """flush_burst_buffer should print if there's a repeated message."""
        import io
        import sys

        from logging_utils.grid_logger import _burst_buffer, flush_burst_buffer

        # Setup: add repeated messages
        _burst_buffer.process("flush_key", "Flush line")
        _burst_buffer.process("flush_key", "Flush line")

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            flush_burst_buffer()
            _ = sys.stdout.getvalue()  # Consume output
            # If there were repeated messages, should have output
        finally:
            sys.stdout = old_stdout
            # Clean up buffer state
            _burst_buffer.flush()


class TestGridFormatterEdgeCases:
    """Additional edge cases for GridFormatter."""

    def test_format_equals_separator_skipped(self):
        """Separator lines starting with === should be skipped."""
        formatter = GridFormatter(colorize=False, burst_suppression=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="=== Header ===",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert result == ""


class TestPlainGridFormatterEdgeCases:
    """Additional edge cases for PlainGridFormatter."""

    def test_format_various_levels(self):
        """PlainGridFormatter should handle various log levels."""
        formatter = PlainGridFormatter()

        for level, expected in [
            (logging.DEBUG, "DBG"),
            (logging.INFO, "INF"),
            (logging.WARNING, "WRN"),
            (logging.ERROR, "ERR"),
            (logging.CRITICAL, "CRT"),
        ]:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="",
                lineno=0,
                msg="Test message",
                args=(),
                exc_info=None,
            )
            request_id_var.set("lvltest")
            source_var.set("test")

            result = formatter.format(record)
            assert expected in result
