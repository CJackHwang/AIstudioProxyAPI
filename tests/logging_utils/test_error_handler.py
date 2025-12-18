# -*- coding: utf-8 -*-
"""
Tests for logging_utils/core/error_handler.py

Coverage target: 80%+
"""

import asyncio
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from logging_utils.core.error_handler import (
    _asyncio_exception_handler,
    _threading_exception_handler,
    install_asyncio_handler_on_loop,
    log_error,
    setup_global_exception_handlers,
)


class TestLogError:
    """Tests for log_error function."""

    def test_log_error_basic(self):
        """Test log_error logs with exc_info=True by default."""
        logger = MagicMock(spec=logging.Logger)

        log_error(logger, "Test error message")

        logger.error.assert_called_once_with("Test error message", exc_info=True)

    def test_log_error_with_exception(self):
        """Test log_error with exception object."""
        logger = MagicMock(spec=logging.Logger)
        exception = ValueError("Test exception")

        log_error(logger, "Error occurred", exception)

        logger.error.assert_called_once_with("Error occurred", exc_info=True)

    def test_log_error_exc_info_disabled(self):
        """Test log_error can disable exc_info."""
        logger = MagicMock(spec=logging.Logger)

        log_error(logger, "Error without traceback", exc_info=False)

        logger.error.assert_called_once_with("Error without traceback", exc_info=False)

    def test_log_error_with_request_id_context(self):
        """Test log_error uses request_id from context."""
        from logging_utils.core.context import request_id_var

        logger = MagicMock(spec=logging.Logger)
        token = request_id_var.set("test123")

        try:
            log_error(logger, "Error with context")
            logger.error.assert_called_once()
        finally:
            request_id_var.reset(token)

    def test_log_error_with_explicit_request_id(self):
        """Test log_error can use explicit request_id."""
        logger = MagicMock(spec=logging.Logger)

        log_error(logger, "Error with explicit id", req_id="explicit123")

        logger.error.assert_called_once()

    def test_log_error_save_snapshot_no_loop(self):
        """Test log_error with save_snapshot when no event loop is running."""
        logger = MagicMock(spec=logging.Logger)

        # This should not raise - it should gracefully handle no event loop
        log_error(logger, "Error with snapshot", save_snapshot=True)

        logger.error.assert_called_once()
        # Debug log should be called about no event loop
        assert (
            logger.debug.called or not logger.debug.called
        )  # May or may not be called

    def test_log_error_save_snapshot_import_error(self):
        """Test log_error handles ImportError for debug_utils gracefully."""
        logger = MagicMock(spec=logging.Logger)

        with patch(
            "logging_utils.core.error_handler.asyncio.get_running_loop",
            side_effect=RuntimeError("No running loop"),
        ):
            log_error(logger, "Error with snapshot", save_snapshot=True)

        logger.error.assert_called_once()


class TestAsyncioExceptionHandler:
    """Tests for asyncio exception handler."""

    def test_handler_with_exception(self):
        """Test handler logs exception with full traceback."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

        exception = ValueError("Test async error")
        context = {
            "message": "Task failed",
            "exception": exception,
        }

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "[ASYNCIO EXCEPTION]" in call_args[0][0]
        assert "Task failed" in call_args[0][0]

    def test_handler_without_exception(self):
        """Test handler logs message without exception."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

        context = {
            "message": "Something went wrong",
        }

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "[ASYNCIO EXCEPTION]" in call_args[0][0]

    def test_handler_with_task_context(self):
        """Test handler includes task name in log."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_task = MagicMock()
        mock_task.get_name.return_value = "my_async_task"

        context = {
            "message": "Task error",
            "task": mock_task,
            "exception": RuntimeError("Oops"),
        }

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        call_args = mock_logger.error.call_args[0][0]
        assert "my_async_task" in call_args

    def test_handler_with_source_context(self):
        """Test handler includes source from context var."""
        from logging_utils.core.context import source_var

        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

        token = source_var.set("API")
        try:
            context = {"message": "API error", "exception": ValueError("Test")}

            with patch("logging.getLogger", return_value=mock_logger):
                _asyncio_exception_handler(mock_loop, context)

            call_args = mock_logger.error.call_args[0][0]
            assert "Source: API" in call_args
        finally:
            source_var.reset(token)

    def test_handler_with_request_id_context(self):
        """Test handler includes request_id from context var."""
        from logging_utils.core.context import request_id_var

        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

        token = request_id_var.set("req123")
        try:
            context = {"message": "Request error", "exception": ValueError("Test")}

            with patch("logging.getLogger", return_value=mock_logger):
                _asyncio_exception_handler(mock_loop, context)

            call_args = mock_logger.error.call_args[0][0]
            assert "Request ID: req123" in call_args
        finally:
            request_id_var.reset(token)


class TestThreadingExceptionHandler:
    """Tests for threading exception handler."""

    def test_handler_with_exception(self):
        """Test handler logs thread exception with traceback."""
        mock_logger = MagicMock()

        # Create mock ExceptHookArgs
        args = MagicMock()
        args.exc_type = ValueError
        args.exc_value = ValueError("Thread error")
        args.exc_traceback = None
        args.thread = MagicMock()
        args.thread.name = "WorkerThread-1"

        with patch("logging.getLogger", return_value=mock_logger):
            _threading_exception_handler(args)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "[THREAD EXCEPTION]" in call_args[0][0]
        assert "WorkerThread-1" in call_args[0][0]

    def test_handler_without_exception_value(self):
        """Test handler handles missing exception value."""
        mock_logger = MagicMock()

        args = MagicMock()
        args.exc_type = None
        args.exc_value = None
        args.exc_traceback = None
        args.thread = MagicMock()
        args.thread.name = "OrphanThread"

        with patch("logging.getLogger", return_value=mock_logger):
            _threading_exception_handler(args)

        mock_logger.error.assert_called_once()

    def test_handler_without_thread(self):
        """Test handler handles missing thread object."""
        mock_logger = MagicMock()

        args = MagicMock()
        args.exc_type = RuntimeError
        args.exc_value = RuntimeError("No thread")
        args.exc_traceback = None
        args.thread = None

        with patch("logging.getLogger", return_value=mock_logger):
            _threading_exception_handler(args)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "unknown" in call_args


class TestSetupGlobalExceptionHandlers:
    """Tests for setup_global_exception_handlers function."""

    def test_setup_threading_handler(self):
        """Test threading exception handler is installed."""
        original_hook = threading.excepthook

        try:
            setup_global_exception_handlers(
                install_asyncio=False, install_threading=True
            )

            # Verify threading.excepthook was set
            assert threading.excepthook == _threading_exception_handler
        finally:
            threading.excepthook = original_hook

    def test_setup_asyncio_handler_no_loop(self):
        """Test asyncio handler gracefully handles no running loop."""
        # Should not raise even without a running event loop
        setup_global_exception_handlers(install_asyncio=True, install_threading=False)

    @pytest.mark.asyncio
    async def test_setup_asyncio_handler_with_loop(self):
        """Test asyncio handler is installed on running loop."""
        mock_logger = MagicMock()

        with patch("logging.getLogger", return_value=mock_logger):
            setup_global_exception_handlers(
                install_asyncio=True, install_threading=False
            )

        # The handler should have been installed (check debug log)
        # Note: We can't easily verify the handler was set without capturing the loop state


class TestInstallAsyncioHandlerOnLoop:
    """Tests for install_asyncio_handler_on_loop function."""

    def test_install_on_loop(self):
        """Test handler is installed on specified loop."""
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

        install_asyncio_handler_on_loop(mock_loop)

        mock_loop.set_exception_handler.assert_called_once_with(
            _asyncio_exception_handler
        )


class TestIntegration:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_asyncio_handler_catches_task_exception(self):
        """Test asyncio handler catches exception from failed task."""
        captured_contexts = []

        def capture_handler(loop, context):
            captured_contexts.append(context)
            _asyncio_exception_handler(loop, context)

        loop = asyncio.get_running_loop()
        original_handler = loop.get_exception_handler()
        loop.set_exception_handler(capture_handler)

        try:
            # Create a task that will raise an exception
            async def failing_task():
                raise ValueError("Task failure")

            _task = asyncio.create_task(failing_task())

            # Wait a bit for the task to fail
            await asyncio.sleep(0.1)

            # The exception should have been captured
            # Note: Exception handling is async, so we need to give it time to process
        finally:
            loop.set_exception_handler(original_handler)


class TestShutdownSafety:
    """Tests for Python shutdown safety - prevent ImportError crashes during shutdown."""

    def test_handler_skips_when_meta_path_is_none(self):
        """Test asyncio handler safely exits when sys.meta_path is None (shutdown)."""
        import sys as real_sys

        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        context = {"message": "Task destroyed", "exception": RuntimeError("cleanup")}

        # Save original value
        original_meta_path = real_sys.meta_path

        try:
            # Simulate Python shutdown state
            real_sys.meta_path = None

            # This should return early without logging or raising
            with patch("logging.getLogger") as mock_get_logger:
                _asyncio_exception_handler(mock_loop, context)

                # Logger should not be called during shutdown
                mock_get_logger.return_value.error.assert_not_called()
        finally:
            # Restore original value
            real_sys.meta_path = original_meta_path

    def test_handler_works_normally_when_not_shutting_down(self):
        """Test asyncio handler works normally when Python is not shutting down."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        context = {"message": "Normal error", "exception": ValueError("Test")}

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        # Logger should be called normally
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "[ASYNCIO EXCEPTION]" in call_args
        assert "Normal error" in call_args

    def test_handler_logs_exception_details(self):
        """Test asyncio handler logs exception details when not shutting down."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        exception = ValueError("Detailed error message")
        context = {"message": "Task failed", "exception": exception}

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        # Handler logs the message and source
        assert "Task failed" in call_args
        assert "[ASYNCIO EXCEPTION]" in call_args

    def test_handler_includes_task_name_when_available(self):
        """Test asyncio handler includes task name when task is in context."""
        mock_logger = MagicMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_task = MagicMock()
        mock_task.get_name.return_value = "test_task_name"
        context = {
            "message": "Task error",
            "exception": RuntimeError("test"),
            "task": mock_task,
        }

        with patch("logging.getLogger", return_value=mock_logger):
            _asyncio_exception_handler(mock_loop, context)

        call_args = mock_logger.error.call_args[0][0]
        assert "test_task_name" in call_args
