"""
Comprehensive tests for models/logging.py

Targets:
- StreamToLogger: write(), flush(), isatty()
- WebSocketConnectionManager: connect(), disconnect(), broadcast()
- WebSocketLogHandler: emit()
- Edge cases: exception handling, asyncio loop detection

Coverage target: 70-80% (40-50 statements out of 57 missing)
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from models.logging import (
    StreamToLogger,
    WebSocketConnectionManager,
    WebSocketLogHandler,
)

# ==================== StreamToLogger TESTS ====================


def test_streamtologger_init():
    """Test StreamToLogger initialization."""
    logger = logging.getLogger("test")
    stream = StreamToLogger(logger, log_level=logging.DEBUG)

    assert stream.logger == logger
    assert stream.log_level == logging.DEBUG
    assert stream.linebuf == ""


def test_streamtologger_write_single_line():
    """Test writing a single complete line."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.write("Hello world\n")

    logger.log.assert_called_once_with(logging.INFO, "Hello world")
    assert stream.linebuf == ""


def test_streamtologger_write_multiple_lines():
    """Test writing multiple lines at once."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.write("Line 1\nLine 2\nLine 3\n")

    assert logger.log.call_count == 3
    calls = logger.log.call_args_list
    assert calls[0] == call(logging.INFO, "Line 1")
    assert calls[1] == call(logging.INFO, "Line 2")
    assert calls[2] == call(logging.INFO, "Line 3")
    assert stream.linebuf == ""


def test_streamtologger_write_incomplete_line():
    """Test writing incomplete line (no newline) - should buffer."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.write("Incomplete")

    logger.log.assert_not_called()
    assert stream.linebuf == "Incomplete"


def test_streamtologger_write_buffered_continuation():
    """Test continuing a buffered line."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.write("Hello ")
    stream.write("world\n")

    logger.log.assert_called_once_with(logging.INFO, "Hello world")
    assert stream.linebuf == ""


def test_streamtologger_write_carriage_return():
    """Test writing line with carriage return."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.write("Line with CR\r")

    logger.log.assert_called_once_with(logging.INFO, "Line with CR")
    assert stream.linebuf == ""


def test_streamtologger_write_exception():
    """Test exception handling during write."""
    logger = MagicMock()
    logger.log.side_effect = Exception("Log error")
    stream = StreamToLogger(logger, log_level=logging.INFO)

    with patch("sys.__stderr__"):
        stream.write("Test line\n")

        # Should not raise, just print to stderr
        # Note: We can't easily verify the print call, but no exception should propagate


def test_streamtologger_flush_empty_buffer():
    """Test flushing with empty buffer."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.flush()

    logger.log.assert_not_called()
    assert stream.linebuf == ""


def test_streamtologger_flush_with_content():
    """Test flushing buffer with content."""
    logger = MagicMock()
    stream = StreamToLogger(logger, log_level=logging.INFO)

    stream.linebuf = "Buffered content"
    stream.flush()

    logger.log.assert_called_once_with(logging.INFO, "Buffered content")
    assert stream.linebuf == ""


def test_streamtologger_flush_exception():
    """Test exception handling during flush."""
    logger = MagicMock()
    logger.log.side_effect = Exception("Flush error")
    stream = StreamToLogger(logger, log_level=logging.INFO)
    stream.linebuf = "Content"

    with patch("sys.__stderr__"):
        stream.flush()

        # Should not raise, but buffer is NOT cleared on exception
        # (buffer clearing happens after logger.log, which raised)
        assert stream.linebuf == "Content"


def test_streamtologger_isatty():
    """Test isatty returns False."""
    logger = MagicMock()
    stream = StreamToLogger(logger)

    assert stream.isatty() is False


# ==================== WebSocketConnectionManager TESTS ====================


@pytest.mark.asyncio
async def test_websocketmanager_init():
    """Test WebSocketConnectionManager initialization."""
    manager = WebSocketConnectionManager()

    assert manager.active_connections == {}


@pytest.mark.asyncio
async def test_websocketmanager_connect_success():
    """Test successful WebSocket connection."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.connect("client1", ws)

    ws.accept.assert_called_once()
    assert "client1" in manager.active_connections
    assert manager.active_connections["client1"] == ws

    # Should send welcome message
    ws.send_text.assert_called_once()
    sent_data = json.loads(ws.send_text.call_args[0][0])
    assert sent_data["type"] == "connection_status"
    assert sent_data["status"] == "connected"

    # Should log connection (uses debug level)
    mock_logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_websocketmanager_connect_send_exception():
    """Test WebSocket connection when send_text fails."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    ws.send_text.side_effect = Exception("Send failed")

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.connect("client2", ws)

    # Connection should still be stored
    assert "client2" in manager.active_connections

    # Should log warning about failed send
    mock_logger.warning.assert_called_once()


def test_websocketmanager_disconnect_existing():
    """Test disconnecting an existing client."""
    manager = WebSocketConnectionManager()
    ws = MagicMock()
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        manager.disconnect("client1")

    assert "client1" not in manager.active_connections
    mock_logger.debug.assert_called_once()


def test_websocketmanager_disconnect_nonexistent():
    """Test disconnecting a non-existent client (should do nothing)."""
    manager = WebSocketConnectionManager()

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        manager.disconnect("nonexistent")

    # Should not log (client not found)
    mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_no_connections():
    """Test broadcasting with no active connections (early return)."""
    manager = WebSocketConnectionManager()

    # Should not raise
    await manager.broadcast("Test message")


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_single_client():
    """Test broadcasting to a single client."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    ws.send_text.assert_called_once_with("Test message")
    assert "client1" in manager.active_connections  # Not disconnected


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_multiple_clients():
    """Test broadcasting to multiple clients."""
    manager = WebSocketConnectionManager()
    ws1 = AsyncMock(spec=WebSocket)
    ws2 = AsyncMock(spec=WebSocket)
    manager.active_connections["client1"] = ws1
    manager.active_connections["client2"] = ws2

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    ws1.send_text.assert_called_once_with("Test message")
    ws2.send_text.assert_called_once_with("Test message")


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_websocketdisconnect():
    """Test broadcasting when client disconnects during send."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    ws.send_text.side_effect = WebSocketDisconnect()
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    # Client should be disconnected
    assert "client1" not in manager.active_connections
    mock_logger.info.assert_called()


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_runtimeerror_closed():
    """Test broadcasting with RuntimeError 'Connection is closed'."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    ws.send_text.side_effect = RuntimeError("Connection is closed")
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    # Client should be disconnected
    assert "client1" not in manager.active_connections
    # Should log the closed connection
    assert any(
        "已关闭" in str(call) or "client1" in str(call)
        for call in mock_logger.info.call_args_list
    )


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_runtimeerror_other():
    """Test broadcasting with RuntimeError (not connection closed)."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    ws.send_text.side_effect = RuntimeError("Some other error")
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    # Client should be disconnected
    assert "client1" not in manager.active_connections
    # Should log error
    mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_websocketmanager_broadcast_generic_exception():
    """Test broadcasting with generic exception."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)
    ws.send_text.side_effect = ValueError("Unexpected error")
    manager.active_connections["client1"] = ws

    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        await manager.broadcast("Test message")

    # Client should be disconnected
    assert "client1" not in manager.active_connections
    # Should log error
    mock_logger.error.assert_called()


# ==================== WebSocketLogHandler TESTS ====================


def test_websocketloghandler_init():
    """Test WebSocketLogHandler initialization."""
    manager = MagicMock()
    handler = WebSocketLogHandler(manager)

    assert handler.manager == manager
    assert isinstance(handler.formatter, logging.Formatter)


@pytest.mark.asyncio
async def test_websocketloghandler_emit_with_active_connections():
    """Test emitting log record with active connections."""
    manager = MagicMock()
    manager.active_connections = {"client1": MagicMock()}
    handler = WebSocketLogHandler(manager)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Mock asyncio.get_running_loop to simulate running in event loop
    mock_loop = MagicMock()
    mock_loop.create_task = MagicMock()

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        handler.emit(record)

    # Should create task for broadcast
    mock_loop.create_task.assert_called_once()


def test_websocketloghandler_emit_no_connections():
    """Test emitting log record with no active connections."""
    manager = MagicMock()
    manager.active_connections = {}
    handler = WebSocketLogHandler(manager)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Should not raise
    handler.emit(record)


def test_websocketloghandler_emit_no_manager():
    """Test emitting log record with no manager."""
    handler = WebSocketLogHandler(None)  # type: ignore[arg-type]

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Should not raise
    handler.emit(record)


def test_websocketloghandler_emit_no_running_loop():
    """Test emitting log record when no event loop is running."""
    manager = MagicMock()
    manager.active_connections = {"client1": MagicMock()}
    handler = WebSocketLogHandler(manager)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Mock asyncio.get_running_loop to raise RuntimeError (no loop)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("No running loop")):
        # Should not raise - catches RuntimeError
        handler.emit(record)


def test_websocketloghandler_emit_format_exception():
    """Test emitting log record when formatting fails."""
    manager = MagicMock()
    manager.active_connections = {"client1": MagicMock()}
    handler = WebSocketLogHandler(manager)

    # Make format() raise exception
    handler.format = MagicMock(side_effect=Exception("Format error"))

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    with patch("sys.__stderr__"):
        # Should not raise, just print to stderr
        handler.emit(record)


# ==================== INTEGRATION TESTS ====================


@pytest.mark.asyncio
async def test_websocket_logging_integration():
    """Test full integration: handler -> manager -> websocket."""
    manager = WebSocketConnectionManager()
    ws = AsyncMock(spec=WebSocket)

    # Connect a client
    with patch("logging.getLogger"):
        await manager.connect("client1", ws)

    # Create handler and logger
    handler = WebSocketLogHandler(manager)
    logger = logging.getLogger("integration_test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # Create log record
    record = logging.LogRecord(
        name="integration_test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Integration test message",
        args=(),
        exc_info=None,
    )

    # Mock event loop
    mock_loop = AsyncMock()

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        handler.emit(record)

    # Should create task
    mock_loop.create_task.assert_called_once()

    logger.removeHandler(handler)


def test_streamtologger_integration_with_real_logger():
    """Test StreamToLogger with a real logger instance."""
    logger = logging.getLogger("stream_integration")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    stream = StreamToLogger(logger, log_level=logging.INFO)

    # Write some content
    stream.write("Line 1\n")
    stream.write("Partial ")
    stream.write("line\n")
    stream.flush()

    # Should not raise
    logger.handlers.clear()
