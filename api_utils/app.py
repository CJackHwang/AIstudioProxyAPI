"""
FastAPI应用初始化和生命周期管理
"""

import asyncio
import multiprocessing
import os
import sys
import queue  # <-- FIX: Added missing import for queue.Empty
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable
from playwright.async_api import Browser as AsyncBrowser, Playwright as AsyncPlaywright

# --- FIX: Replaced star import with explicit imports ---
from config import NO_PROXY_ENV, EXCLUDED_MODELS_FILENAME, get_environment_variable

# --- models模块导入 ---
from models import WebSocketConnectionManager

# --- logging_utils模块导入 ---
from logging_utils import setup_server_logging, restore_original_streams

# --- browser_utils模块导入 ---
from browser_utils import (
    _initialize_page_logic,
    _close_page_logic,
    load_excluded_models,
    _handle_initial_model_state_and_storage,
    enable_temporary_chat_mode
)

import stream
from asyncio import Queue, Lock
from . import auth_utils

# 全局状态变量（这些将在server.py中被引用）
playwright_manager: Optional[AsyncPlaywright] = None
browser_instance: Optional[AsyncBrowser] = None
page_instance = None
is_playwright_ready = False
is_browser_connected = False
is_page_ready = False
is_initializing = False

global_model_list_raw_json = None
parsed_model_list = []
model_list_fetch_event = None

current_ai_studio_model_id = None
model_switching_lock = None

excluded_model_ids = set()

request_queue = None
processing_lock = None
worker_task = None

page_params_cache = {}
params_cache_lock = None

log_ws_manager = None

STREAM_QUEUE = None
STREAM_PROCESS = None

# --- Lifespan Context Manager ---
def _setup_logging():
    import server
    log_level_env = get_environment_variable('SERVER_LOG_LEVEL', 'INFO')
    redirect_print_env = get_environment_variable('SERVER_REDIRECT_PRINT', 'false')
    server.log_ws_manager = WebSocketConnectionManager()
    return setup_server_logging(
        logger_instance=server.logger,
        log_ws_manager=server.log_ws_manager,
        log_level_name=log_level_env,
        redirect_print_str=redirect_print_env
    )

def _initialize_globals():
    import server
    server.request_queue = Queue()
    server.processing_lock = Lock()
    server.model_switching_lock = Lock()
    server.params_cache_lock = Lock()
    auth_utils.initialize_keys()
    
    # Initialize Auth Rotation Lock
    from config.global_state import GlobalState
    GlobalState.init_rotation_lock()
    
    server.logger.info("API keys and global locks initialized.")

def _initialize_proxy_settings():
    import server
    STREAM_PORT = get_environment_variable('STREAM_PORT')
    if STREAM_PORT == '0':
        PROXY_SERVER_ENV = get_environment_variable('HTTPS_PROXY') or get_environment_variable('HTTP_PROXY')
    else:
        PROXY_SERVER_ENV = f"http://127.0.0.1:{STREAM_PORT or 3120}/"
    
    if PROXY_SERVER_ENV:
        server.PLAYWRIGHT_PROXY_SETTINGS = {'server': PROXY_SERVER_ENV}
        if NO_PROXY_ENV:
            server.PLAYWRIGHT_PROXY_SETTINGS['bypass'] = NO_PROXY_ENV.replace(',', ';')
        server.logger.info(f"Playwright proxy settings configured: {server.PLAYWRIGHT_PROXY_SETTINGS}")
    else:
        server.logger.info("No proxy configured for Playwright.")

async def _start_stream_proxy():
    import server
    STREAM_PORT = get_environment_variable('STREAM_PORT')
    if STREAM_PORT != '0':
        port = int(STREAM_PORT or 3120)
        STREAM_PROXY_SERVER_ENV = (
            get_environment_variable('UNIFIED_PROXY_CONFIG')
            or get_environment_variable('HTTPS_PROXY')
            or get_environment_variable('HTTP_PROXY')
        )
        server.logger.info(f"Starting STREAM proxy on port {port} with upstream proxy: {STREAM_PROXY_SERVER_ENV}")
        server.STREAM_QUEUE = multiprocessing.Queue()
        server.STREAM_PROCESS = multiprocessing.Process(target=stream.start, args=(server.STREAM_QUEUE, port, STREAM_PROXY_SERVER_ENV))
        server.STREAM_PROCESS.start()
        server.logger.info("STREAM proxy process started. Waiting for 'READY' signal...")

        # --- FIX: Wait for the proxy to be ready ---
        try:
            # Use asyncio.to_thread to wait for the blocking queue.get()
            # Set a timeout to avoid waiting forever
            ready_signal = await asyncio.to_thread(server.STREAM_QUEUE.get, timeout=15)
            if ready_signal == "READY":
                server.logger.info("✅ Received 'READY' signal from STREAM proxy.")
            else:
                server.logger.warning(f"Received unexpected signal from proxy: {ready_signal}")
        except queue.Empty:
            server.logger.error("❌ Timed out waiting for STREAM proxy to become ready. Startup will likely fail.")
            raise RuntimeError("STREAM proxy failed to start in time.")

async def _initialize_browser_and_page():
    import server
    from playwright.async_api import async_playwright
    
    server.logger.info("Starting Playwright...")
    server.playwright_manager = await async_playwright().start()
    server.is_playwright_ready = True
    server.logger.info("Playwright started.")

    ws_endpoint = get_environment_variable('CAMOUFOX_WS_ENDPOINT')
    launch_mode = get_environment_variable('LAUNCH_MODE', 'unknown')

    if not ws_endpoint and launch_mode != "direct_debug_no_browser":
        raise ValueError("CAMOUFOX_WS_ENDPOINT environment variable is missing.")

    if ws_endpoint:
        server.logger.info(f"Connecting to browser at: {ws_endpoint}")
        server.browser_instance = await server.playwright_manager.firefox.connect(ws_endpoint, timeout=30000)
        server.is_browser_connected = True
        server.logger.info(f"Connected to browser: {server.browser_instance.version}")
        
        server.page_instance, server.is_page_ready = await _initialize_page_logic(server.browser_instance)
        if server.is_page_ready:
            await _handle_initial_model_state_and_storage(server.page_instance)
            await enable_temporary_chat_mode(server.page_instance)
            server.logger.info("Page initialized successfully.")
        else:
            server.logger.error("Page initialization failed.")
    
    if not server.model_list_fetch_event.is_set():
        server.model_list_fetch_event.set()

async def _shutdown_resources():
    import server
    logger = server.logger
    logger.info("Shutting down resources...")
    
    if server.STREAM_PROCESS:
        server.STREAM_PROCESS.terminate()
        logger.info("STREAM proxy terminated.")

    if server.worker_task and not server.worker_task.done():
        server.worker_task.cancel()
        try:
            await asyncio.wait_for(server.worker_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        logger.info("Worker task stopped.")

    if server.page_instance:
        await _close_page_logic()
    
    if server.browser_instance and server.browser_instance.is_connected():
        await server.browser_instance.close()
        logger.info("Browser connection closed.")
    
    if server.playwright_manager:
        await server.playwright_manager.stop()
        logger.info("Playwright stopped.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI application life cycle management"""
    import server
    from server import queue_worker

    original_streams = sys.stdout, sys.stderr
    initial_stdout, initial_stderr = _setup_logging()
    logger = server.logger

    _initialize_globals()
    _initialize_proxy_settings()
    load_excluded_models(EXCLUDED_MODELS_FILENAME)
    
    server.is_initializing = True
    logger.info("Starting AI Studio Proxy Server...")

    try:
        await _start_stream_proxy()
        await _initialize_browser_and_page()
        
        launch_mode = get_environment_variable('LAUNCH_MODE', 'unknown')
        if server.is_page_ready or launch_mode == "direct_debug_no_browser":
            server.worker_task = asyncio.create_task(queue_worker())
            logger.info("Request processing worker started.")
        else:
            raise RuntimeError("Failed to initialize browser/page, worker not started.")

        # [CRITICAL FIX] Start the Quota Watchdog in the background
        logger.info("👀 Starting Quota Watchdog Task...")
        app.state.watchdog_task = asyncio.create_task(server.quota_watchdog())

        logger.info("Server startup complete.")
        server.is_initializing = False
        yield
    except Exception as e:
        logger.critical(f"Application startup failed: {e}", exc_info=True)
        await _shutdown_resources()
        raise RuntimeError(f"Application startup failed: {e}") from e
    finally:
        logger.info("Shutting down server...")

        # [CRITICAL FIX] Cancel the watchdog on shutdown
        if hasattr(app.state, "watchdog_task"):
            logger.info("💤 Stopping Quota Watchdog...")
            app.state.watchdog_task.cancel()
            try:
                await app.state.watchdog_task
            except asyncio.CancelledError:
                pass

        await _shutdown_resources()
        restore_original_streams(initial_stdout, initial_stderr)
        restore_original_streams(*original_streams)
        logger.info("Server shutdown complete.")


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
            "/favicon.ico"
        ]

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        if not auth_utils.API_KEYS:  # 如果 API_KEYS 为空，则不进行验证
            return await call_next(request)

        # 检查是否是需要保护的路径
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)

        # 检查是否是排除的路径
        for excluded_path in self.excluded_paths:
            if request.url.path == excluded_path or request.url.path.startswith(excluded_path + "/"):
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
                        "code": "invalid_api_key"
                    }
                }
            )
        return await call_next(request)

def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    app = FastAPI(
        title="AI Studio Proxy Server (集成模式)",
        description="通过 Playwright与 AI Studio 交互的代理服务器。",
        version="0.6.0-integrated",
        lifespan=lifespan
    )
    
    # 添加中间件
    app.add_middleware(APIKeyAuthMiddleware)

    # 注册路由
    # Import aggregated modular routers
    from .routers import (
        read_index, get_css, get_js, get_api_info,
        health_check, list_models, chat_completions,
        cancel_request, get_queue_status, websocket_log_endpoint,
        get_api_keys, add_api_key, test_api_key, delete_api_key
    )
    from fastapi.responses import FileResponse
    
    app.get("/", response_class=FileResponse)(read_index)
    app.get("/webui.css")(get_css)
    app.get("/webui.js")(get_js)
    app.get("/api/info")(get_api_info)
    app.get("/health")(health_check)
    app.get("/v1/models")(list_models)
    app.post("/v1/chat/completions")(chat_completions)
    app.post("/v1/cancel/{req_id}")(cancel_request)
    app.get("/v1/queue")(get_queue_status)
    app.websocket("/ws/logs")(websocket_log_endpoint)

    # API密钥管理端点
    app.get("/api/keys")(get_api_keys)
    app.post("/api/keys")(add_api_key)
    app.post("/api/keys/test")(test_api_key)
    app.delete("/api/keys")(delete_api_key)

    return app
