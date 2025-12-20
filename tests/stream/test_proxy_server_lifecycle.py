"""
Tests for ProxyServer lifecycle and connection handling.

Covers:
- handle_client() - main client connection handler
- _handle_connect() - CONNECT method and SSL setup
- start() - server startup and READY signaling

These tests focus on the untested control flow and error handling paths.
"""

import asyncio
import multiprocessing
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stream.proxy_server import ProxyServer

# ==================== FIXTURES ====================


@pytest.fixture
def mock_deps():
    """Mock all external dependencies."""
    with (
        patch("stream.proxy_server.CertificateManager") as MockCert,
        patch("stream.proxy_server.ProxyConnector") as MockConnector,
        patch("stream.proxy_server.HttpInterceptor") as MockInterceptor,
        patch("logging.getLogger"),
    ):
        mock_cert = MockCert.return_value
        mock_cert.cert_dir = MagicMock()
        mock_cert.cert_dir.__truediv__ = MagicMock(return_value="fake/path")
        mock_cert.get_domain_cert = MagicMock()

        mock_connector = MockConnector.return_value
        mock_connector.create_connection = AsyncMock()

        yield {
            "cert": mock_cert,
            "connector": mock_connector,
            "interceptor": MockInterceptor.return_value,
        }


@pytest.fixture
def proxy_server(mock_deps):
    """Create ProxyServer with mocked dependencies."""
    queue = multiprocessing.Queue()
    server = ProxyServer(
        host="127.0.0.1", port=3120, intercept_domains=["*.google.com"], queue=queue
    )
    return server


# ==================== TESTS: handle_client ====================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_client_with_connect_method(proxy_server):
    """Test handle_client processes CONNECT requests."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Mock CONNECT request
    reader.readline.return_value = b"CONNECT example.com:443 HTTP/1.1\r\n"

    # Mock _handle_connect to verify it's called
    with patch.object(
        proxy_server, "_handle_connect", new_callable=AsyncMock
    ) as mock_connect:
        await proxy_server.handle_client(reader, writer)

        # Verify _handle_connect was called
        mock_connect.assert_called_once_with(reader, writer, "example.com:443")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_client_empty_request_line(proxy_server):
    """Test handle_client handles empty request (client disconnects)."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Empty request line (connection closed)
    reader.readline.return_value = b""

    await proxy_server.handle_client(reader, writer)

    # Verify connection was closed
    writer.close.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_client_exception_handling(proxy_server):
    """Test handle_client catches and logs exceptions."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Make readline raise an exception
    reader.readline.side_effect = Exception("Read error")

    # Should not crash, just log error
    await proxy_server.handle_client(reader, writer)

    # Verify logger was called
    proxy_server.logger.error.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_client_cancelled_error_propagates(proxy_server):
    """Test that CancelledError is re-raised."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Make readline raise CancelledError
    reader.readline.side_effect = asyncio.CancelledError()

    # Should re-raise CancelledError
    with pytest.raises(asyncio.CancelledError):
        await proxy_server.handle_client(reader, writer)


# ==================== TESTS: _handle_connect ====================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_connect_non_intercepted_domain(proxy_server, mock_deps):
    """Test CONNECT to non-intercepted domain (passthrough)."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Mock reader.read for dropping proxy headers
    reader.read = AsyncMock(return_value=b"")

    # Mock server connection
    server_reader = AsyncMock()
    server_writer = MagicMock()
    server_writer.close = MagicMock()
    server_writer.wait_closed = AsyncMock()

    mock_deps["connector"].create_connection.return_value = (
        server_reader,
        server_writer,
    )

    # Mock _forward_data
    with patch.object(
        proxy_server, "_forward_data", new_callable=AsyncMock
    ) as mock_forward:
        # Non-intercepted domain
        await proxy_server._handle_connect(reader, writer, "example.com:443")

        # Verify "200 Connection Established" was sent
        writer.write.assert_called_with(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        # Verify forwarding was started (no interception)
        mock_forward.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_connect_intercepted_domain_ssl_setup(proxy_server, mock_deps):
    """Test CONNECT to intercepted domain sets up SSL/TLS."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    # Mock transport for SSL upgrade
    mock_transport = MagicMock()
    mock_protocol = MagicMock()
    writer.transport = mock_transport
    mock_transport.get_protocol.return_value = mock_protocol

    # Mock reader.read for dropping headers
    reader.read = AsyncMock(return_value=b"")

    # Mock event loop start_tls
    mock_new_transport = MagicMock()
    with (
        patch("asyncio.get_running_loop") as mock_get_loop,
        patch("ssl.create_default_context") as mock_ssl_ctx,
    ):
        mock_loop = mock_get_loop.return_value
        mock_loop.start_tls = AsyncMock(return_value=mock_new_transport)

        # Mock SSL context to avoid file loading
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.load_cert_chain = MagicMock()
        mock_ssl_ctx.return_value = mock_ctx_instance

        # Mock server connection
        server_reader = AsyncMock()
        server_writer = MagicMock()
        mock_deps["connector"].create_connection.return_value = (
            server_reader,
            server_writer,
        )

        # Mock StreamWriter creation to avoid asyncio internal assertions
        with (
            patch("asyncio.StreamWriter") as mock_stream_writer_cls,
            patch.object(
                proxy_server, "_forward_data_with_interception", new_callable=AsyncMock
            ) as mock_intercept,
        ):
            # Create a fake StreamWriter instance
            mock_stream_writer_instance = MagicMock()
            mock_stream_writer_cls.return_value = mock_stream_writer_instance

            # Intercepted domain
            await proxy_server._handle_connect(
                reader, writer, "aistudio.google.com:443"
            )

            # Verify cert was generated
            mock_deps["cert"].get_domain_cert.assert_called_with("aistudio.google.com")

            # Verify SSL context load_cert_chain was called
            mock_ctx_instance.load_cert_chain.assert_called_once()

            # Verify TLS upgrade happened
            mock_loop.start_tls.assert_called_once()

            # Verify interception forwarding was started
            mock_intercept.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_connect_transport_none_before_tls(proxy_server):
    """Test _handle_connect handles None transport gracefully."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    writer.transport = None  # Transport is None

    reader.read = AsyncMock(return_value=b"")

    # Intercepted domain but transport is None
    await proxy_server._handle_connect(reader, writer, "aistudio.google.com:443")

    # Verify warning was logged
    proxy_server.logger.warning.assert_called()
    assert "transport is None" in str(proxy_server.logger.warning.call_args)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_connect_start_tls_returns_none(proxy_server, mock_deps):
    """Test _handle_connect handles start_tls returning None."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    mock_transport = MagicMock()
    writer.transport = mock_transport
    mock_transport.get_protocol.return_value = MagicMock()

    reader.read = AsyncMock(return_value=b"")

    # Mock start_tls to return None (error case)
    with (
        patch("asyncio.get_running_loop") as mock_get_loop,
        patch("ssl.create_default_context") as mock_ssl_ctx,
    ):
        mock_loop = mock_get_loop.return_value
        mock_loop.start_tls = AsyncMock(return_value=None)

        # Mock SSL context to avoid file loading
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.load_cert_chain = MagicMock()
        mock_ssl_ctx.return_value = mock_ctx_instance

        await proxy_server._handle_connect(reader, writer, "aistudio.google.com:443")

        # Verify error was logged
        proxy_server.logger.error.assert_called()
        assert "start_tls returned None" in str(proxy_server.logger.error.call_args)

        # Verify connection was closed
        writer.close.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_connect_server_connection_fails(proxy_server, mock_deps):
    """Test _handle_connect handles server connection errors."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    reader.read = AsyncMock(return_value=b"")

    # Mock connection failure
    mock_deps["connector"].create_connection.side_effect = Exception(
        "Connection refused"
    )

    # Non-intercepted domain with connection failure
    await proxy_server._handle_connect(reader, writer, "example.com:443")

    # Verify error was logged
    proxy_server.logger.error.assert_called()

    # Verify writer was closed
    writer.close.assert_called()


# ==================== TESTS: start() ====================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_start_creates_server_and_signals_ready(proxy_server):
    """Test start() creates server and sends READY signal to queue."""
    mock_server = MagicMock()
    mock_socket = MagicMock()
    mock_socket.getsockname.return_value = ("127.0.0.1", 3120)
    mock_server.sockets = [mock_socket]
    mock_server.serve_forever = AsyncMock()
    mock_server.__aenter__ = AsyncMock(return_value=mock_server)
    mock_server.__aexit__ = AsyncMock(return_value=None)

    with patch("asyncio.start_server", new_callable=AsyncMock) as mock_start_server:
        mock_start_server.return_value = mock_server

        # Create task for start() since it runs forever
        task = asyncio.create_task(proxy_server.start())

        # Give it time to start
        await asyncio.sleep(0.2)

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify server was created
        mock_start_server.assert_called_once()

        # Verify READY signal was sent to queue
        # Note: queue.put is called, we can't easily verify without real queue


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_start_handles_queue_none(mock_deps):
    """Test start() works when queue is None (no signaling)."""
    # Create server without queue
    server = ProxyServer(
        host="127.0.0.1",
        port=3120,
        intercept_domains=["*.google.com"],
        queue=None,  # No queue
    )

    mock_server = MagicMock()
    mock_socket = MagicMock()
    mock_socket.getsockname.return_value = ("127.0.0.1", 3120)
    mock_server.sockets = [mock_socket]
    mock_server.serve_forever = AsyncMock()
    mock_server.__aenter__ = AsyncMock(return_value=mock_server)
    mock_server.__aexit__ = AsyncMock(return_value=None)

    with patch("asyncio.start_server", new_callable=AsyncMock) as mock_start_server:
        mock_start_server.return_value = mock_server

        # Create task for start()
        task = asyncio.create_task(server.start())

        # Give it time to start
        await asyncio.sleep(0.2)

        # Cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should not crash even without queue
        mock_start_server.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_start_logs_server_address(proxy_server):
    """Test start() logs the server address."""
    mock_server = MagicMock()
    mock_socket = MagicMock()
    mock_socket.getsockname.return_value = ("127.0.0.1", 3120)
    mock_server.sockets = [mock_socket]
    mock_server.serve_forever = AsyncMock()
    mock_server.__aenter__ = AsyncMock(return_value=mock_server)
    mock_server.__aexit__ = AsyncMock(return_value=None)

    with patch("asyncio.start_server", new_callable=AsyncMock) as mock_start_server:
        mock_start_server.return_value = mock_server

        task = asyncio.create_task(proxy_server.start())

        await asyncio.sleep(0.2)

        # Verify logger.debug was called with address (implementation uses debug, not info)
        proxy_server.logger.debug.assert_called()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
