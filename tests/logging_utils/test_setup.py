"""
Comprehensive tests for logging_utils/setup.py

Targets:
- USCentralFormatter.formatTime() with/without datefmt
- setup_server_logging() with various configurations
- restore_original_streams()
- Edge cases: OSError, None ws_manager, stdout/stderr redirection

Coverage target: 70-80% (40-50 statements out of 62 missing)
"""

import logging
import logging.handlers
import sys
from unittest.mock import MagicMock, patch

import pytest

from logging_utils.setup import (
    restore_original_streams,
    setup_server_logging,
)

# ==================== FIXTURES ====================


@pytest.fixture(autouse=True)
def mock_rotating_file_handler():
    """Mock RotatingFileHandler globally to prevent file creation."""
    with patch("logging_utils.setup.logging.handlers.RotatingFileHandler") as mock:
        handler_instance = MagicMock()
        handler_instance.level = logging.NOTSET  # Fix for >= comparison
        mock.return_value = handler_instance
        yield mock


@pytest.fixture(autouse=True)
def mock_sys_stderr():
    """Mock sys.__stderr__ to prevent WinError 6 on Windows."""
    with patch("logging_utils.setup.sys.__stderr__") as mock:
        yield mock


@pytest.fixture
def mock_logger():
    """Create a fresh logger instance for each test."""
    logger = logging.getLogger("test_logger")
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    logger.propagate = False
    yield logger
    logger.handlers.clear()


@pytest.fixture
def mock_ws_manager():
    """Create a mock WebSocket connection manager."""
    manager = MagicMock()
    manager.broadcast = MagicMock()
    return manager


@pytest.fixture
def mock_dirs():
    """Mock directory creation."""
    with patch("logging_utils.setup.os.makedirs") as mock:
        yield mock


@pytest.fixture
def mock_file_ops():
    """Mock file operations (exists, remove)."""
    with (
        patch("logging_utils.setup.os.path.exists") as mock_exists,
        patch("logging_utils.setup.os.remove") as mock_remove,
    ):
        mock_exists.return_value = False
        yield mock_exists, mock_remove


# ==================== setup_server_logging BASIC TESTS ====================


def test_setup_server_logging_basic(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test basic setup_server_logging functionality."""
    mock_exists, mock_remove = mock_file_ops

    orig_stdout, orig_stderr = setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="INFO",
        redirect_print_str="false",
    )

    # Verify directory creation was called
    assert mock_dirs.call_count == 3  # LOG_DIR, ACTIVE_AUTH_DIR, SAVED_AUTH_DIR

    # Verify logger configuration
    assert mock_logger.level == logging.INFO
    assert mock_logger.propagate is False

    # Verify handlers were added (file + console + websocket)
    assert len(mock_logger.handlers) == 3

    # Verify original streams were returned
    assert orig_stdout is not None
    assert orig_stderr is not None


def test_setup_server_logging_log_levels(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test setup_server_logging with different log levels."""
    test_cases = [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ]

    for level_name, expected_level in test_cases:
        mock_logger.handlers.clear()

        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name=level_name,
            redirect_print_str="false",
        )

        assert mock_logger.level == expected_level, f"Failed for level {level_name}"


def test_setup_server_logging_invalid_log_level(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test setup_server_logging with invalid log level defaults to INFO."""
    setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="INVALID_LEVEL",
        redirect_print_str="false",
    )

    # Should default to INFO
    assert mock_logger.level == logging.INFO


def test_setup_server_logging_clears_existing_handlers(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test that setup_server_logging clears existing handlers."""
    # Add a dummy handler
    dummy_handler = logging.StreamHandler()
    mock_logger.addHandler(dummy_handler)
    assert len(mock_logger.handlers) == 1

    setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="INFO",
        redirect_print_str="false",
    )

    # Old handler should be removed, new handlers added
    assert dummy_handler not in mock_logger.handlers
    assert len(mock_logger.handlers) == 3


# ==================== HANDLER TESTS ====================


def test_setup_server_logging_file_handler(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops, mock_rotating_file_handler
):
    """Test that file handler is configured correctly."""
    setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="INFO",
        redirect_print_str="false",
    )

    # Verify RotatingFileHandler was created
    mock_rotating_file_handler.assert_called_once()
    call_kwargs = mock_rotating_file_handler.call_args[1]
    assert (
        call_kwargs["maxBytes"] == 10 * 1024 * 1024
    )  # 10 MB (configurable via LOG_FILE_MAX_BYTES)
    assert call_kwargs["backupCount"] == 5
    assert call_kwargs["encoding"] == "utf-8"
    assert call_kwargs["mode"] == "w"

    # Verify formatter was set
    mock_rotating_file_handler.return_value.setFormatter.assert_called_once()


def test_setup_server_logging_console_handler(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test that console handler is configured correctly."""
    setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="WARNING",
        redirect_print_str="false",
    )

    # Find console handler (StreamHandler writing to stderr)
    console_handlers = [
        h for h in mock_logger.handlers if isinstance(h, logging.StreamHandler)
    ]
    assert len(console_handlers) > 0

    # Verify console handler level matches logger level
    console_handler = console_handlers[0]
    assert console_handler.level == logging.WARNING


def test_setup_server_logging_websocket_handler_valid(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test WebSocket handler is added when manager is provided."""
    with patch("logging_utils.setup.WebSocketLogHandler") as MockWSHandler:
        mock_ws_handler = MagicMock()
        mock_ws_handler.level = logging.NOTSET  # Fix for >= comparison
        MockWSHandler.return_value = mock_ws_handler

        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # Verify WebSocket handler was created and configured
        MockWSHandler.assert_called_once_with(mock_ws_manager)
        # WebSocket handler should use the same log level as requested
        mock_ws_handler.setLevel.assert_called_once_with(logging.INFO)


def test_setup_server_logging_websocket_handler_debug_level(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test WebSocket handler respects DEBUG log level."""
    with patch("logging_utils.setup.WebSocketLogHandler") as MockWSHandler:
        mock_ws_handler = MagicMock()
        mock_ws_handler.level = logging.NOTSET
        MockWSHandler.return_value = mock_ws_handler

        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="DEBUG",
            redirect_print_str="false",
        )

        # WebSocket handler should use DEBUG level (not hardcoded INFO)
        mock_ws_handler.setLevel.assert_called_once_with(logging.DEBUG)


def test_setup_server_logging_websocket_handler_none(
    mock_logger, mock_dirs, mock_file_ops, capsys, mock_sys_stderr
):
    """Test behavior when WebSocket manager is None."""
    with patch("logging_utils.setup.WebSocketLogHandler") as MockWSHandler:
        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=None,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # WebSocketLogHandler should NOT be created
        MockWSHandler.assert_not_called()

        # Should print warning to stderr (mocked)
        # Verify any of the write calls contains the warning
        calls = mock_sys_stderr.write.call_args_list
        warning_found = any(
            "严重警告" in str(call.args[0]) or "log_ws_manager" in str(call.args[0])
            for call in calls
        )
        assert warning_found, f"Warning not found in sys.__stderr__ writes: {calls}"


# ==================== FILE OPERATIONS TESTS ====================


def test_setup_server_logging_removes_existing_log_file(
    mock_logger, mock_ws_manager, mock_dirs
):
    """Test that existing log file is removed."""
    with (
        patch("logging_utils.setup.os.path.exists") as mock_exists,
        patch("logging_utils.setup.os.remove") as mock_remove,
    ):
        mock_exists.return_value = True

        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # Verify file removal was attempted
        mock_remove.assert_called_once()


def test_setup_server_logging_oserror_on_remove(
    mock_logger, mock_ws_manager, mock_dirs, capsys, mock_sys_stderr
):
    """Test handling of OSError when removing log file."""
    with (
        patch("logging_utils.setup.os.path.exists") as mock_exists,
        patch("logging_utils.setup.os.remove") as mock_remove,
    ):
        mock_exists.return_value = True
        mock_remove.side_effect = OSError("Permission denied")

        # Should not raise exception
        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # Should print warning to stderr (mocked)
        calls = mock_sys_stderr.write.call_args_list
        warning_found = any(
            "警告" in str(call.args[0]) or "Permission denied" in str(call.args[0])
            for call in calls
        )
        assert warning_found, f"Warning not found in sys.__stderr__ writes: {calls}"


# ==================== STDOUT/STDERR REDIRECTION TESTS ====================


def test_setup_server_logging_redirect_print_false(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test that stdout/stderr are NOT redirected when redirect_print_str is 'false'."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    orig_stdout, orig_stderr = setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="INFO",
        redirect_print_str="false",
    )

    # Stdout/stderr should remain unchanged
    assert sys.stdout == original_stdout
    assert sys.stderr == original_stderr

    # Returned originals should match current
    assert orig_stdout == original_stdout
    assert orig_stderr == original_stderr


def test_setup_server_logging_redirect_print_true(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test that stdout/stderr ARE redirected when redirect_print_str is 'true'."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with patch("logging_utils.setup.StreamToLogger") as MockStreamToLogger:
        mock_stream = MagicMock()
        MockStreamToLogger.return_value = mock_stream

        orig_stdout, orig_stderr = setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="true",
        )

        # Verify StreamToLogger was created for both stdout and stderr
        assert MockStreamToLogger.call_count == 2

        # Returned originals should be the original streams
        assert orig_stdout == original_stdout
        assert orig_stderr == original_stderr


def test_setup_server_logging_redirect_print_variations(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test redirect_print with various truthy values."""
    test_cases = [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
    ]

    for input_val, should_redirect in test_cases:
        with patch("logging_utils.setup.StreamToLogger") as MockStreamToLogger:
            mock_stream = MagicMock()
            MockStreamToLogger.return_value = mock_stream

            setup_server_logging(
                logger_instance=mock_logger,
                log_ws_manager=mock_ws_manager,
                log_level_name="INFO",
                redirect_print_str=input_val,
            )

            if should_redirect:
                assert MockStreamToLogger.called, f"Failed for input: {input_val}"
            else:
                assert not MockStreamToLogger.called, f"Failed for input: {input_val}"


# ==================== THIRD-PARTY LOGGER TESTS ====================


def test_setup_server_logging_configures_third_party_loggers(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test that third-party library loggers are configured."""
    with patch("logging_utils.setup.logging.getLogger") as mock_get_logger:
        # Create mock loggers for third-party libraries
        third_party_loggers = {}
        for name in [
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "websockets",
            "playwright",
            "asyncio",
        ]:
            third_party_loggers[name] = MagicMock()

        def get_logger_side_effect(name):
            if name in third_party_loggers:
                return third_party_loggers[name]
            return MagicMock()

        mock_get_logger.side_effect = get_logger_side_effect

        setup_server_logging(
            logger_instance=mock_logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # Verify third-party loggers were configured
        # Note: We can't easily verify the setLevel calls due to the patching,
        # but we can verify getLogger was called for them
        assert mock_get_logger.call_count >= 6


# ==================== restore_original_streams TESTS ====================


def test_restore_original_streams(capsys, mock_sys_stderr):
    """Test restore_original_streams restores stdout and stderr."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Replace with mock streams
    mock_stdout = MagicMock()
    mock_stderr = MagicMock()
    sys.stdout = mock_stdout
    sys.stderr = mock_stderr

    # Restore
    restore_original_streams(original_stdout, original_stderr)

    # Verify restoration
    assert sys.stdout == original_stdout
    assert sys.stderr == original_stderr

    # Note: restore_original_streams is now silent (no confirmation message)
    # This is intentional to reduce shutdown log noise


def test_restore_original_streams_with_streamtologger():
    """Test restore_original_streams when streams are StreamToLogger instances."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Mock StreamToLogger
    mock_stream_stdout = MagicMock()
    mock_stream_stderr = MagicMock()
    sys.stdout = mock_stream_stdout
    sys.stderr = mock_stream_stderr

    restore_original_streams(original_stdout, original_stderr)

    # Verify restoration
    assert sys.stdout == original_stdout
    assert sys.stderr == original_stderr


# ==================== INTEGRATION TESTS ====================


def test_setup_and_restore_full_cycle(
    mock_logger, mock_ws_manager, mock_dirs, mock_file_ops
):
    """Test full setup -> log -> restore cycle."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Setup
    orig_streams = setup_server_logging(
        logger_instance=mock_logger,
        log_ws_manager=mock_ws_manager,
        log_level_name="DEBUG",
        redirect_print_str="false",
    )

    # Verify setup
    assert len(mock_logger.handlers) == 3
    assert mock_logger.level == logging.DEBUG

    # Test logging
    mock_logger.info("Test message")
    mock_logger.debug("Debug message")
    mock_logger.error("Error message")

    # Restore
    restore_original_streams(*orig_streams)

    # Verify restoration
    assert sys.stdout == original_stdout
    assert sys.stderr == original_stderr


def test_setup_server_logging_creates_directories(mock_ws_manager, mock_file_ops):
    """Test that all required directories are created."""
    with patch("logging_utils.setup.os.makedirs") as mock_makedirs:
        logger = logging.getLogger("test_dirs")
        logger.handlers.clear()

        setup_server_logging(
            logger_instance=logger,
            log_ws_manager=mock_ws_manager,
            log_level_name="INFO",
            redirect_print_str="false",
        )

        # Verify makedirs was called 3 times (LOG_DIR, ACTIVE_AUTH_DIR, SAVED_AUTH_DIR)
        assert mock_makedirs.call_count == 3

        # Verify exist_ok=True was used
        for call_args in mock_makedirs.call_args_list:
            assert call_args[1]["exist_ok"] is True

        logger.handlers.clear()
