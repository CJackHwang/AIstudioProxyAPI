"""
FastAPI应用初始化和生命周期管理
"""

import asyncio
import multiprocessing
import queue  # <-- FIX: Added missing import for queue.Empty
import sys
import time
from asyncio import Lock, Queue
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import stream

# --- 导入集中状态模块 ---
from api_utils.server_state import state

# --- browser_utils模块导入 ---
from browser_utils import (
    _close_page_logic,  # pyright: ignore[reportPrivateUsage]
    _handle_initial_model_state_and_storage,  # pyright: ignore[reportPrivateUsage]
    _initialize_page_logic,  # pyright: ignore[reportPrivateUsage]
    enable_temporary_chat_mode,
    load_excluded_models,
)

# --- FIX: Replaced star import with explicit imports ---
from config import EXCLUDED_MODELS_FILENAME, NO_PROXY_ENV, get_environment_variable

# --- logging_utils模块导入 ---
from logging_utils import restore_original_streams, setup_server_logging

# --- models模块导入 ---
from models import WebSocketConnectionManager

from . import auth_utils


# --- Lifespan Context Manager ---
def _setup_logging() -> Any:
    """Setup logging system with WebSocket handler."""
    log_level_env = get_environment_variable("SERVER_LOG_LEVEL", "INFO")
    redirect_print_env = get_environment_variable("SERVER_REDIRECT_PRINT", "false")
    state.log_ws_manager = WebSocketConnectionManager()
    return setup_server_logging(
        logger_instance=state.logger,
        log_ws_manager=state.log_ws_manager,
        log_level_name=log_level_env,
        redirect_print_str=redirect_print_env,
    )


def _initialize_globals() -> None:
    """Initialize global locks and queues."""
    state.request_queue = Queue()
    state.processing_lock = Lock()
    state.model_switching_lock = Lock()
    state.params_cache_lock = Lock()
    auth_utils.initialize_keys()
    state.logger.debug("API keys and global locks initialized.")


def _initialize_proxy_settings() -> None:
    """Configure Playwright proxy settings based on environment."""
    STREAM_PORT = get_environment_variable("STREAM_PORT")
    if STREAM_PORT == "0":
        proxy_server_env = get_environment_variable(
            "HTTPS_PROXY"
        ) or get_environment_variable("HTTP_PROXY")
    else:
        proxy_server_env = f"http://127.0.0.1:{STREAM_PORT or 3120}/"

    if proxy_server_env:
        state.PLAYWRIGHT_PROXY_SETTINGS = {"server": proxy_server_env}
        if NO_PROXY_ENV:
            state.PLAYWRIGHT_PROXY_SETTINGS["bypass"] = NO_PROXY_ENV.replace(",", ";")
        state.logger.debug(
            f"[代理] 已配置: {state.PLAYWRIGHT_PROXY_SETTINGS.get('server', 'N/A')}"
        )
    else:
        state.logger.debug("[代理] 未配置")


async def _start_stream_proxy() -> None:
    """Start the stream proxy subprocess if configured."""
    STREAM_PORT = get_environment_variable("STREAM_PORT")
    if STREAM_PORT != "0":
        port = int(STREAM_PORT or 3120)
        STREAM_PROXY_SERVER_ENV = (
            get_environment_variable("UNIFIED_PROXY_CONFIG")
            or get_environment_variable("HTTPS_PROXY")
            or get_environment_variable("HTTP_PROXY")
        )
        state.logger.info(f"[系统] 启动流式代理服务 (端口: {port})")
        state.STREAM_QUEUE = multiprocessing.Queue()
        state.STREAM_PROCESS = multiprocessing.Process(
            target=stream.start,
            args=(state.STREAM_QUEUE, port, STREAM_PROXY_SERVER_ENV),
        )
        state.STREAM_PROCESS.start()
        state.logger.debug(
            "STREAM proxy process started. Waiting for 'READY' signal..."
        )

        # Wait for the proxy to be ready
        try:
            # Use asyncio.to_thread to wait for the blocking queue.get()
            # Set a timeout to avoid waiting forever
            ready_signal = await asyncio.to_thread(state.STREAM_QUEUE.get, timeout=15)
            if ready_signal == "READY":
                state.logger.info("[系统] 流式代理就绪")
            else:
                state.logger.warning(
                    f"Received unexpected signal from proxy: {ready_signal}"
                )
        except queue.Empty:
            state.logger.error(
                "Timed out waiting for STREAM proxy to become ready. Startup will likely fail."
            )
            raise RuntimeError("STREAM proxy failed to start in time.")


async def _initialize_browser_and_page() -> None:
    """Initialize Playwright browser connection and page."""
    from playwright.async_api import async_playwright

    state.logger.debug("[内核] 正在启动 Playwright...")
    state.playwright_manager = await async_playwright().start()
    state.is_playwright_ready = True

    ws_endpoint = get_environment_variable("CAMOUFOX_WS_ENDPOINT")
    launch_mode = get_environment_variable("LAUNCH_MODE", "unknown")

    if not ws_endpoint and launch_mode != "direct_debug_no_browser":
        raise ValueError("CAMOUFOX_WS_ENDPOINT environment variable is missing.")

    if ws_endpoint:
        state.logger.debug(f"Connecting to browser at: {ws_endpoint}")
        state.browser_instance = await state.playwright_manager.firefox.connect(
            ws_endpoint, timeout=30000
        )
        state.is_browser_connected = True
        state.logger.info(f"[浏览器] 已连接 (版本: {state.browser_instance.version})")

        state.page_instance, state.is_page_ready = await _initialize_page_logic(
            state.browser_instance
        )
        if state.is_page_ready:
            await _handle_initial_model_state_and_storage(state.page_instance)
            await enable_temporary_chat_mode(state.page_instance)
            state.logger.info("[系统] 页面初始化成功")
        else:
            state.logger.error("Page initialization failed.")

    if not state.model_list_fetch_event.is_set():
        state.model_list_fetch_event.set()


async def _shutdown_resources() -> None:
    """Gracefully shut down all resources."""
    logger = state.logger
    logger.debug("[系统] 正在关闭资源...")

    # Signal all streaming generators to exit immediately
    state.should_exit = True

    if state.STREAM_PROCESS:
        state.STREAM_PROCESS.terminate()
        # Wait for process to terminate with timeout to avoid atexit hang
        state.STREAM_PROCESS.join(timeout=3)
        if state.STREAM_PROCESS.is_alive():
            logger.warning("STREAM proxy did not terminate, killing...")
            state.STREAM_PROCESS.kill()
            state.STREAM_PROCESS.join(timeout=1)
        # Close the queue to prevent resource leaks
        if state.STREAM_QUEUE:
            try:
                state.STREAM_QUEUE.close()
                state.STREAM_QUEUE.join_thread()
            except Exception:
                pass
        logger.debug("STREAM proxy terminated.")

    if state.worker_task and not state.worker_task.done():
        logger.debug("Cancelling worker task...")
        state.worker_task.cancel()
        try:
            await asyncio.wait_for(state.worker_task, timeout=2.0)
            logger.debug("Worker task cancelled.")
        except asyncio.TimeoutError:
            logger.warning("Worker task did not respond to cancellation within 2s.")
        except asyncio.CancelledError:
            logger.debug("Worker task cancelled.")

    if state.page_instance:
        await _close_page_logic()

    if state.browser_instance and state.browser_instance.is_connected():
        await state.browser_instance.close()
        logger.debug("Browser connection closed.")

    if state.playwright_manager:
        await state.playwright_manager.stop()
        logger.debug("Playwright stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI application life cycle management."""
    # Import queue_worker from api_utils (not server to avoid circular import)
    from api_utils import queue_worker

    original_streams = sys.stdout, sys.stderr
    initial_stdout, initial_stderr = _setup_logging()
    logger = state.logger

    _initialize_globals()
    _initialize_proxy_settings()
    load_excluded_models(EXCLUDED_MODELS_FILENAME)

    state.is_initializing = True
    startup_start_time = time.time()
    logger.info("[系统] AI Studio 代理服务器启动中...")

    try:
        await _start_stream_proxy()
        await _initialize_browser_and_page()

        launch_mode = get_environment_variable("LAUNCH_MODE", "unknown")
        if state.is_page_ready or launch_mode == "direct_debug_no_browser":
            state.worker_task = asyncio.create_task(queue_worker())
            logger.debug("Request processing worker started.")
        else:
            raise RuntimeError("Failed to initialize browser/page, worker not started.")

        startup_duration = time.time() - startup_start_time
        logger.info(f"[系统] 服务器启动完成 (耗时: {startup_duration:.2f}秒)")
        state.is_initializing = False
        yield
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.critical(f"Application startup failed: {e}", exc_info=True)
        await _shutdown_resources()
        raise RuntimeError(f"Application startup failed: {e}") from e
    finally:
        logger.info("[系统] 服务器关闭中...")
        await _shutdown_resources()
        restore_original_streams(initial_stdout, initial_stderr)
        restore_original_streams(*original_streams)
        logger.info("[系统] 服务器已关闭")


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.excluded_paths = [
            "/v1/models",
            "/health",
            "/docs",
            "/openapi.json",
            # FastAPI 自动生成的其他文档路径
            "/redoc",
            "/favicon.ico",
        ]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not auth_utils.API_KEYS:  # 如果 API_KEYS 为空，则不进行验证
            return await call_next(request)

        # 检查是否是需要保护的路径
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)

        # 检查是否是排除的路径
        for excluded_path in self.excluded_paths:
            if request.url.path == excluded_path or request.url.path.startswith(
                excluded_path + "/"
            ):
                return await call_next(request)

        # 支持多种认证头格式以兼容OpenAI标准
        api_key = None

        # 1. 优先检查标准的 Authorization: Bearer <token> 头
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]  # 移除 "Bearer " 前缀

        # 2. 回退到自定义的 X-API-Key 头（向后兼容）
        if not api_key:
            api_key = request.headers.get("X-API-Key")

        if not api_key or not auth_utils.verify_api_key(api_key):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid or missing API key. Please provide a valid API key using 'Authorization: Bearer <your_key>' or 'X-API-Key: <your_key>' header.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )
        return await call_next(request)


def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    app = FastAPI(
        title="AI Studio Proxy Server (集成模式)",
        description="通过 Playwright与 AI Studio 交互的代理服务器。",
        version="0.6.0-integrated",
        lifespan=lifespan,
    )

    # 添加中间件
    app.add_middleware(APIKeyAuthMiddleware)

    # 注册路由
    # Import aggregated modular routers
    from fastapi.responses import FileResponse

    from .routers import (
        add_api_key,
        auth_files_router,
        cancel_request,
        chat_completions,
        delete_api_key,
        get_api_info,
        get_api_keys,
        get_queue_status,
        health_check,
        list_models,
        model_capabilities_router,
        ports_router,
        proxy_router,
        read_index,
        serve_react_assets,
        test_api_key,
        websocket_log_endpoint,
    )

    app.get("/", response_class=FileResponse)(read_index)
    app.get("/assets/{filename:path}")(serve_react_assets)  # React built assets
    app.get("/api/info")(get_api_info)
    app.get("/health")(health_check)
    app.get("/v1/models")(list_models)
    app.post("/v1/chat/completions")(chat_completions)
    app.post("/v1/cancel/{req_id}")(cancel_request)
    app.get("/v1/queue")(get_queue_status)
    app.websocket("/ws/logs")(websocket_log_endpoint)

    # Model capabilities endpoint (single source of truth)
    app.include_router(model_capabilities_router)

    # Proxy, auth, and port management routers
    app.include_router(proxy_router)
    app.include_router(auth_files_router)
    app.include_router(ports_router)

    # Server control and helper routers
    from api_utils.routers import helper_router, server_router

    app.include_router(server_router)
    app.include_router(helper_router)

    # API密钥管理端点
    app.get("/api/keys")(get_api_keys)
    app.post("/api/keys")(add_api_key)
    app.post("/api/keys/test")(test_api_key)
    app.delete("/api/keys")(delete_api_key)

    return app
