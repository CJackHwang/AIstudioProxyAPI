import asyncio
import queue
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api_utils.app import (
    APIKeyAuthMiddleware,
    _initialize_browser_and_page,
    _initialize_globals,
    _initialize_proxy_settings,
    _setup_logging,
    _shutdown_resources,
    _start_stream_proxy,
    create_app,
)
from api_utils.server_state import state


@pytest.fixture(autouse=True)
def reset_state():
    """Reset server state before each test."""
    state.reset()
    yield
    state.reset()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_create_app(app):
    """Test that the app is created correctly."""
    assert app.title == "AI Studio Proxy Server (集成模式)"
    assert app.version == "0.6.0-integrated"


def test_middleware_initialization(app):
    """Test that middleware is added."""
    middleware_types = [m.cls for m in app.user_middleware]
    assert APIKeyAuthMiddleware in middleware_types


@pytest.mark.asyncio
async def test_api_key_auth_middleware_no_keys():
    """Test middleware when no API keys are configured."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)

    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    call_next = AsyncMock()

    with patch("api_utils.auth_utils.API_KEYS", {}):
        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_api_key_auth_middleware_excluded_path():
    """Test middleware with excluded paths."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)

    request = MagicMock()
    request.url.path = "/health"
    call_next = AsyncMock()

    # Even with keys configured, excluded paths should pass
    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_api_key_auth_middleware_valid_key():
    """Test middleware with valid API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)

    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {"Authorization": "Bearer test-key"}
    call_next = AsyncMock()

    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        with patch("api_utils.auth_utils.verify_api_key", return_value=True):
            await middleware.dispatch(request, call_next)
            call_next.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_api_key_auth_middleware_invalid_key():
    """Test middleware with invalid API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)

    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {"Authorization": "Bearer invalid-key"}
    call_next = AsyncMock()

    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        with patch("api_utils.auth_utils.verify_api_key", return_value=False):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401
            call_next.assert_not_called()


@pytest.mark.asyncio
async def test_api_key_auth_middleware_missing_key():
    """Test middleware with missing API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)

    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {}
    call_next = AsyncMock()

    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 401
        call_next.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_startup_shutdown():
    """Test application startup and shutdown sequence."""
    app_mock = MagicMock()

    # Set state.is_page_ready before the test
    state.is_page_ready = True
    mock_logger = MagicMock()
    state.logger = mock_logger

    # Mock all the dependencies
    with (
        patch("api_utils.app._setup_logging") as mock_setup_logging,
        patch("api_utils.app._initialize_globals") as mock_init_globals,
        patch("api_utils.app._initialize_proxy_settings") as mock_init_proxy,
        patch("api_utils.app.load_excluded_models") as mock_load_models,
        patch(
            "api_utils.app._start_stream_proxy", new_callable=AsyncMock
        ) as mock_start_proxy,
        patch(
            "api_utils.app._initialize_browser_and_page", new_callable=AsyncMock
        ) as mock_init_browser,
        patch(
            "api_utils.app._shutdown_resources", new_callable=AsyncMock
        ) as mock_shutdown,
        patch("api_utils.queue_worker", new_callable=AsyncMock),
        patch("api_utils.app.restore_original_streams") as mock_restore_streams,
    ):
        mock_setup_logging.return_value = (MagicMock(), MagicMock())

        # Get the lifespan context manager
        from api_utils.app import lifespan

        async with lifespan(app_mock):
            # Verify startup actions
            mock_init_globals.assert_called_once()
            mock_init_proxy.assert_called_once()
            mock_load_models.assert_called_once()
            mock_start_proxy.assert_called_once()
            mock_init_browser.assert_called_once()
            # Check actual log messages from the implementation
            mock_logger.info.assert_any_call("[系统] AI Studio 代理服务器启动中...")

        # Verify shutdown actions
        mock_shutdown.assert_called_once()
        mock_restore_streams.assert_called()
        mock_logger.info.assert_any_call("[系统] 服务器已关闭")


@pytest.mark.asyncio
async def test_lifespan_startup_failure():
    """Test application startup failure handling."""
    app_mock = MagicMock()

    mock_logger = MagicMock()
    state.logger = mock_logger

    with (
        patch("api_utils.app._setup_logging") as mock_setup_logging,
        patch("api_utils.app._initialize_globals"),
        patch("api_utils.app._initialize_proxy_settings"),
        patch("api_utils.app.load_excluded_models"),
        patch(
            "api_utils.app._start_stream_proxy", side_effect=Exception("Startup failed")
        ),
        patch(
            "api_utils.app._shutdown_resources", new_callable=AsyncMock
        ) as mock_shutdown,
        patch("api_utils.app.restore_original_streams"),
    ):
        mock_setup_logging.return_value = (MagicMock(), MagicMock())

        from api_utils.app import lifespan

        with pytest.raises(RuntimeError, match="Application startup failed"):
            async with lifespan(app_mock):
                pass

        # Verify shutdown was called even after failure
        mock_shutdown.assert_called()
        mock_logger.critical.assert_called()


# --- New Tests for Helper Functions ---


def test_setup_logging():
    """Test _setup_logging helper."""
    # Ensure state starts clean
    state.log_ws_manager = None

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("api_utils.app.setup_server_logging") as mock_setup,
    ):
        mock_get_env.side_effect = lambda key, default=None: {
            "SERVER_LOG_LEVEL": "DEBUG",
            "SERVER_REDIRECT_PRINT": "true",
        }.get(key, default)

        _setup_logging()

        assert state.log_ws_manager is not None
        mock_setup.assert_called_once()
        args, kwargs = mock_setup.call_args
        assert kwargs["log_level_name"] == "DEBUG"
        assert kwargs["redirect_print_str"] == "true"


def test_initialize_globals():
    """Test _initialize_globals helper."""
    # Ensure state starts clean
    state.request_queue = None
    state.processing_lock = None
    state.model_switching_lock = None
    state.params_cache_lock = None

    with patch("api_utils.auth_utils.initialize_keys") as mock_init_keys:
        _initialize_globals()

        assert state.request_queue is not None
        assert state.processing_lock is not None
        assert state.model_switching_lock is not None
        assert state.params_cache_lock is not None
        mock_init_keys.assert_called_once()


def test_initialize_proxy_settings_no_port():
    """Test _initialize_proxy_settings when STREAM_PORT is 0."""
    state.PLAYWRIGHT_PROXY_SETTINGS = None

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("api_utils.app.NO_PROXY_ENV", "127.0.0.1"),
    ):
        mock_get_env.side_effect = lambda key, default=None: {
            "STREAM_PORT": "0",
            "HTTPS_PROXY": "http://system-proxy:8080",
        }.get(key, default)

        _initialize_proxy_settings()

        assert state.PLAYWRIGHT_PROXY_SETTINGS == {
            "server": "http://system-proxy:8080",
            "bypass": "127.0.0.1",
        }


def test_initialize_proxy_settings_with_port():
    """Test _initialize_proxy_settings when STREAM_PORT is set."""
    state.PLAYWRIGHT_PROXY_SETTINGS = None

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("api_utils.app.NO_PROXY_ENV", "localhost,127.0.0.1"),
    ):
        mock_get_env.side_effect = lambda key, default=None: {
            "STREAM_PORT": "3120"
        }.get(key, default)

        _initialize_proxy_settings()

        assert state.PLAYWRIGHT_PROXY_SETTINGS == {
            "server": "http://127.0.0.1:3120/",
            "bypass": "localhost;127.0.0.1",
        }


@pytest.mark.asyncio
async def test_start_stream_proxy_disabled():
    """Test _start_stream_proxy when STREAM_PORT is 0."""
    with patch("api_utils.app.get_environment_variable", return_value="0"):
        await _start_stream_proxy()
        # Should do nothing


@pytest.mark.asyncio
async def test_start_stream_proxy_success():
    """Test _start_stream_proxy success path."""
    state.STREAM_QUEUE = None
    state.STREAM_PROCESS = None

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("multiprocessing.Queue") as mock_queue_cls,
        patch("multiprocessing.Process") as mock_process_cls,
    ):
        mock_get_env.side_effect = lambda key, default=None: {
            "STREAM_PORT": "3120",
            "UNIFIED_PROXY_CONFIG": "http://upstream:8080",
        }.get(key, default)

        mock_queue = MagicMock()
        mock_queue.get.return_value = "READY"
        mock_queue_cls.return_value = mock_queue

        mock_process = MagicMock()
        mock_process_cls.return_value = mock_process

        await _start_stream_proxy()

        assert state.STREAM_QUEUE is not None
        assert state.STREAM_PROCESS is not None
        mock_process.start.assert_called_once()
        # Verify queue.get was called (via asyncio.to_thread, so we check the mock)
        mock_queue.get.assert_called()


@pytest.mark.asyncio
async def test_start_stream_proxy_timeout():
    """Test _start_stream_proxy timeout waiting for READY."""
    with (
        patch("api_utils.app.get_environment_variable", return_value="3120"),
        patch("multiprocessing.Queue") as mock_queue_cls,
        patch("multiprocessing.Process"),
        patch("server.logger"),
        patch("asyncio.to_thread", side_effect=queue.Empty),
    ):
        mock_queue = MagicMock()
        mock_queue_cls.return_value = mock_queue

        with pytest.raises(RuntimeError, match="STREAM proxy failed to start in time"):
            await _start_stream_proxy()


@pytest.mark.asyncio
async def test_start_stream_proxy_unexpected_signal():
    """Test _start_stream_proxy receiving unexpected signal."""
    mock_logger = MagicMock()
    state.logger = mock_logger

    with (
        patch("api_utils.app.get_environment_variable", return_value="3120"),
        patch("multiprocessing.Queue") as mock_queue_cls,
        patch("multiprocessing.Process"),
    ):
        mock_queue = MagicMock()
        mock_queue.get.return_value = "ERROR"
        mock_queue_cls.return_value = mock_queue

        # Mock asyncio.to_thread to return the value directly since we can't easily mock the thread execution
        with patch("asyncio.to_thread", return_value="ERROR"):
            await _start_stream_proxy()

        mock_logger.warning.assert_called_with(
            "Received unexpected signal from proxy: ERROR"
        )


@pytest.mark.asyncio
async def test_initialize_browser_and_page_missing_endpoint():
    """Test _initialize_browser_and_page raises error if endpoint missing."""
    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("server.logger"),
        patch("playwright.async_api.async_playwright") as mock_playwright,
    ):
        mock_get_env.return_value = None  # No endpoint, no launch mode
        mock_playwright.return_value.start = AsyncMock()

        with pytest.raises(
            ValueError, match="CAMOUFOX_WS_ENDPOINT environment variable is missing"
        ):
            await _initialize_browser_and_page()


@pytest.mark.asyncio
async def test_initialize_browser_and_page_success():
    """Test _initialize_browser_and_page success path."""
    # Create a mock event that mimics asyncio.Event behavior
    mock_event = MagicMock()
    mock_event.is_set.return_value = False
    state.model_list_fetch_event = mock_event

    with (
        patch("api_utils.app.get_environment_variable", return_value="ws://test"),
        patch("playwright.async_api.async_playwright") as mock_playwright,
        patch(
            "api_utils.app._initialize_page_logic", new_callable=AsyncMock
        ) as mock_init_page,
        patch(
            "api_utils.app._handle_initial_model_state_and_storage",
            new_callable=AsyncMock,
        ) as mock_handle_state,
        patch(
            "api_utils.app.enable_temporary_chat_mode", new_callable=AsyncMock
        ) as mock_enable_chat,
    ):
        # Setup mock for async_playwright().start()
        mock_browser = AsyncMock()
        mock_browser.version = "1.0"

        mock_pw_instance = AsyncMock()
        mock_pw_instance.firefox.connect.return_value = mock_browser

        # async_playwright() returns a context manager whose start() method is async
        mock_context_manager = MagicMock()
        mock_context_manager.start = AsyncMock(return_value=mock_pw_instance)
        mock_playwright.return_value = mock_context_manager

        mock_page = AsyncMock()
        mock_init_page.return_value = (mock_page, True)

        await _initialize_browser_and_page()

        assert state.is_playwright_ready
        assert state.is_browser_connected
        assert state.is_page_ready
        mock_handle_state.assert_called_once()
        mock_enable_chat.assert_called_once()
        mock_event.set.assert_called()


@pytest.mark.asyncio
async def test_initialize_browser_and_page_init_failed():
    """Test _initialize_browser_and_page when page init fails."""
    mock_logger = MagicMock()
    state.logger = mock_logger
    mock_event = MagicMock()
    mock_event.is_set.return_value = False
    state.model_list_fetch_event = mock_event

    with (
        patch("api_utils.app.get_environment_variable", return_value="ws://test"),
        patch("playwright.async_api.async_playwright") as mock_playwright,
        patch(
            "api_utils.app._initialize_page_logic", new_callable=AsyncMock
        ) as mock_init_page,
    ):
        mock_browser = AsyncMock()

        mock_pw_instance = AsyncMock()
        mock_pw_instance.firefox.connect.return_value = mock_browser

        mock_context_manager = MagicMock()
        mock_context_manager.start = AsyncMock(return_value=mock_pw_instance)
        mock_playwright.return_value = mock_context_manager

        mock_init_page.return_value = (None, False)

        await _initialize_browser_and_page()

        mock_logger.error.assert_called_with("Page initialization failed.")


@pytest.mark.asyncio
async def test_shutdown_resources():
    """Test _shutdown_resources cleans up everything."""

    # Create a dummy task in the current loop
    async def dummy_coro():
        await asyncio.sleep(0.1)

    real_task = asyncio.create_task(dummy_coro())

    # Set up state with mocked resources
    mock_stream_process = MagicMock()
    state.STREAM_PROCESS = mock_stream_process
    state.worker_task = real_task
    state.page_instance = MagicMock()

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.close = AsyncMock()
    state.browser_instance = mock_browser

    mock_pw = MagicMock()
    mock_pw.stop = AsyncMock()
    state.playwright_manager = mock_pw

    with patch(
        "api_utils.app._close_page_logic", new_callable=AsyncMock
    ) as mock_close_page:
        await _shutdown_resources()

        mock_stream_process.terminate.assert_called_once()
        # The task should be cancelled
        assert real_task.cancelled() or real_task.done()
        mock_close_page.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_resources_worker_timeout():
    """Test _shutdown_resources handles worker cancellation timeout."""

    # Create a dummy task that sleeps longer than the timeout
    async def dummy_coro():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    real_task = asyncio.create_task(dummy_coro())
    state.worker_task = real_task

    # We need to spy on the cancel method or ensure it was called.
    # Since we can't easily spy on a built-in method of a Task object in some python versions without side effects,
    # we'll rely on the fact that calling cancel() schedules cancellation.

    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await _shutdown_resources()

        # Allow the loop to process the cancellation
        await asyncio.sleep(0)

        # Verify the task is done (cancelled)
        assert real_task.done()


@pytest.mark.asyncio
async def test_shutdown_resources_process_join_and_terminate():
    """Test _shutdown_resources calls join() after terminate() with timeout.

    Regression test: Ensures the STREAM_PROCESS cleanup properly joins after
    terminate to prevent multiprocessing atexit handler hangs on Ctrl+C.
    """
    mock_stream_process = MagicMock()
    mock_stream_process.is_alive.return_value = False  # Process terminates successfully
    mock_stream_queue = MagicMock()

    state.STREAM_PROCESS = mock_stream_process
    state.STREAM_QUEUE = mock_stream_queue

    with patch("api_utils.app._close_page_logic", new_callable=AsyncMock):
        await _shutdown_resources()

    # Verify terminate was called
    mock_stream_process.terminate.assert_called_once()
    # Verify join was called with timeout (NOT blocking forever)
    mock_stream_process.join.assert_called_with(timeout=3)
    # Verify kill was NOT called since process terminated successfully
    mock_stream_process.kill.assert_not_called()
    # Verify queue was closed
    mock_stream_queue.close.assert_called_once()
    mock_stream_queue.join_thread.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_resources_process_kill_fallback():
    """Test _shutdown_resources kills process if terminate times out.

    Regression test: Ensures the STREAM_PROCESS is killed if it doesn't
    respond to terminate within the timeout period.
    """
    mock_stream_process = MagicMock()
    # Process is still alive after terminate
    mock_stream_process.is_alive.return_value = True
    mock_stream_queue = MagicMock()

    state.STREAM_PROCESS = mock_stream_process
    state.STREAM_QUEUE = mock_stream_queue

    with patch("api_utils.app._close_page_logic", new_callable=AsyncMock):
        await _shutdown_resources()

    # Verify terminate was called
    mock_stream_process.terminate.assert_called_once()
    # Verify join was called (first time with timeout=3)
    assert mock_stream_process.join.call_count >= 1
    # Verify kill was called since process was still alive
    mock_stream_process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_resources_queue_cleanup_error_handling():
    """Test _shutdown_resources handles queue cleanup errors gracefully.

    Regression test: Ensures queue cleanup exceptions don't prevent
    the rest of shutdown from completing.
    """
    mock_stream_process = MagicMock()
    mock_stream_process.is_alive.return_value = False
    mock_stream_queue = MagicMock()
    # Simulate queue cleanup error
    mock_stream_queue.close.side_effect = Exception("Queue already closed")

    state.STREAM_PROCESS = mock_stream_process
    state.STREAM_QUEUE = mock_stream_queue

    # Should not raise exception
    with patch("api_utils.app._close_page_logic", new_callable=AsyncMock):
        await _shutdown_resources()

    # Verify process cleanup still happened
    mock_stream_process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_resources_no_process_no_queue():
    """Test _shutdown_resources handles case where process/queue don't exist.

    Regression test: Ensures shutdown doesn't fail when resources were never
    created (e.g., startup failed early).
    """
    state.STREAM_PROCESS = None
    state.STREAM_QUEUE = None
    state.worker_task = None
    state.page_instance = None
    state.browser_instance = None
    state.playwright_manager = None

    # Should not raise exception
    await _shutdown_resources()


@pytest.mark.asyncio
async def test_lifespan_direct_debug_mode():
    """Test lifespan with direct_debug_no_browser mode."""
    app_mock = MagicMock()

    # Page not ready, but mode allows it
    state.is_page_ready = False

    with (
        patch("api_utils.app._setup_logging", return_value=(None, None)),
        patch("api_utils.app._initialize_globals"),
        patch("api_utils.app._initialize_proxy_settings"),
        patch("api_utils.app.load_excluded_models"),
        patch("api_utils.app._start_stream_proxy", new_callable=AsyncMock),
        patch("api_utils.app._initialize_browser_and_page", new_callable=AsyncMock),
        patch("api_utils.app._shutdown_resources", new_callable=AsyncMock),
        patch("api_utils.queue_worker", new_callable=AsyncMock),
        patch("api_utils.app.restore_original_streams"),
        patch(
            "api_utils.app.get_environment_variable",
            return_value="direct_debug_no_browser",
        ),
    ):
        from api_utils.app import lifespan

        async with lifespan(app_mock):
            assert state.worker_task is not None


@pytest.mark.asyncio
async def test_lifespan_page_not_ready_error():
    """Test lifespan raises error if page not ready and not debug mode."""
    app_mock = MagicMock()

    # Page not ready and not debug mode - should fail
    state.is_page_ready = False

    with (
        patch("api_utils.app._setup_logging", return_value=(None, None)),
        patch("api_utils.app._initialize_globals"),
        patch("api_utils.app._initialize_proxy_settings"),
        patch("api_utils.app.load_excluded_models"),
        patch("api_utils.app._start_stream_proxy", new_callable=AsyncMock),
        patch("api_utils.app._initialize_browser_and_page", new_callable=AsyncMock),
        patch("api_utils.app._shutdown_resources", new_callable=AsyncMock),
        patch("api_utils.app.restore_original_streams"),
        patch("api_utils.app.get_environment_variable", return_value="unknown"),
    ):
        from api_utils.app import lifespan

        with pytest.raises(RuntimeError, match="Application startup failed"):
            async with lifespan(app_mock):
                pass


"""
Extended tests for api_utils/app.py - Coverage completion.

Focus: Cover the last 2 uncovered lines (86, 265).
Strategy: Test edge cases for proxy settings and middleware path matching.
"""


def test_initialize_proxy_settings_no_proxy_configured():
    """
    测试场景: 完全没有配置任何代理
    预期: 记录 "[代理] 未配置" 日志 (line 87)
    """
    state.PLAYWRIGHT_PROXY_SETTINGS = None
    mock_logger = MagicMock()
    state.logger = mock_logger

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("api_utils.app.NO_PROXY_ENV", None),
    ):
        # 返回 None 表示没有配置任何代理
        mock_get_env.side_effect = lambda key, default=None: {
            "STREAM_PORT": "0",
            "UNIFIED_PROXY_CONFIG": None,
            "HTTPS_PROXY": None,
            "HTTP_PROXY": None,
        }.get(key, default)

        _initialize_proxy_settings()

    # 验证: PLAYWRIGHT_PROXY_SETTINGS 应该为 None
    assert state.PLAYWRIGHT_PROXY_SETTINGS is None

    # 验证: 记录了 "[代理] 未配置" 日志 (line 87)
    mock_logger.debug.assert_any_call("[代理] 未配置")


@pytest.mark.asyncio
async def test_api_key_auth_middleware_excluded_path_subpath():
    """
    测试场景: 请求路径是排除路径的子路径,且以 /v1/ 开头
    预期: 绕过认证,调用 call_next (line 265)

    注意: 为了触发 line 265,路径必须:
    1. 以 /v1/ 开头 (通过 line 257-258 检查)
    2. 匹配 excluded_paths 中的路径或其子路径 (触发 lines 261-265)
    """
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    # 添加一个以 /v1/ 开头的排除路径
    middleware.excluded_paths.append("/v1/models")

    request = MagicMock()
    request.url.path = "/v1/models/abc"  # /v1/models 的子路径
    call_next = AsyncMock()
    call_next.return_value = MagicMock()  # Mock response

    # 即使配置了 API 密钥,排除路径的子路径也应该通过
    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        response = await middleware.dispatch(request, call_next)

        # 验证: call_next 被调用 (line 265)
        call_next.assert_called_once_with(request)

        # 验证: 返回了 call_next 的响应
        assert response is not None
