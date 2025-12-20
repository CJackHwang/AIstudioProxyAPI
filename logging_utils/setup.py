import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

from config import (
    ACTIVE_AUTH_DIR,
    APP_LOG_FILE_PATH,
    JSON_LOGS_ENABLED,
    LOG_DIR,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    SAVED_AUTH_DIR,
)
from models import StreamToLogger, WebSocketConnectionManager, WebSocketLogHandler

from .core.error_handler import setup_global_exception_handlers
from .grid_logger import (
    GridFormatter,
    JSONFormatter,
    PlainGridFormatter,
)


class ColoredFormatter(logging.Formatter):
    """Cross-platform colored formatter using ANSI codes (legacy, kept for compatibility)."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[0m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[41m\033[97m",
    }
    RESET = "\033[0m"

    def __init__(
        self, fmt: Any = None, datefmt: Any = None, use_color: bool = True
    ) -> None:
        super().__init__(fmt, datefmt)
        self.use_color = use_color

        if use_color and sys.platform == "win32":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                self.use_color = False

    def formatTime(self, record: logging.LogRecord, datefmt: Any = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/Chicago"))
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S")
            s = "%s,%03d" % (s, record.msecs)
        return s

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color and record.levelname in self.COLORS:
            original_levelname = record.levelname
            record.levelname = (
                f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
            )
            result = super().format(record)
            record.levelname = original_levelname
            return result
        return super().format(record)


def setup_server_logging(
    logger_instance: logging.Logger,
    log_ws_manager: Optional[WebSocketConnectionManager],
    log_level_name: str = "INFO",
    redirect_print_str: str = "false",
) -> Tuple[object, object]:
    """
    设置服务器日志系统

    Args:
        logger_instance: 主要的日志器实例
        log_ws_manager: WebSocket连接管理器
        log_level_name: 日志级别名称
        redirect_print_str: 是否重定向print输出

    Returns:
        Tuple[object, object]: 原始的stdout和stderr流
    """
    log_level = getattr(logging, log_level_name.upper(), logging.INFO)
    redirect_print = redirect_print_str.lower() in ("true", "1", "yes")

    # 创建必要的目录
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(ACTIVE_AUTH_DIR, exist_ok=True)
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)

    # 设置文件日志格式器 (plain grid format, no ANSI codes)
    file_log_formatter = PlainGridFormatter()

    # 清理现有的处理器
    if logger_instance.hasHandlers():
        logger_instance.handlers.clear()
    logger_instance.setLevel(log_level)
    logger_instance.propagate = False

    # 移除旧的日志文件
    if os.path.exists(APP_LOG_FILE_PATH):
        try:
            os.remove(APP_LOG_FILE_PATH)
        except OSError as e:
            print(
                f"警告 (setup_server_logging): 尝试移除旧的 app.log 文件 '{APP_LOG_FILE_PATH}' 失败: {e}。将依赖 mode='w' 进行截断。",
                file=sys.__stderr__,
            )

    # 添加文件处理器
    # Use JSONFormatter for file logging if JSON_LOGS_ENABLED, otherwise PlainGridFormatter
    if JSON_LOGS_ENABLED:
        file_log_formatter = JSONFormatter()
    else:
        file_log_formatter = PlainGridFormatter()

    file_handler = logging.handlers.RotatingFileHandler(
        APP_LOG_FILE_PATH,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
        mode="w",
    )
    file_handler.setFormatter(file_log_formatter)
    logger_instance.addHandler(file_handler)

    # 添加WebSocket处理器 (使用 PlainGridFormatter, 无 ANSI 代码)
    if log_ws_manager is None:
        print(
            "严重警告 (setup_server_logging): log_ws_manager 未初始化！WebSocket 日志功能将不可用。",
            file=sys.__stderr__,
        )
    else:
        ws_handler = WebSocketLogHandler(log_ws_manager)
        ws_handler.setLevel(log_level)  # Match console handler behavior
        ws_handler.setFormatter(PlainGridFormatter())
        logger_instance.addHandler(ws_handler)

    # 添加控制台处理器 (使用 GridFormatter 彩色输出)
    console_grid_formatter = GridFormatter(show_tree=True, colorize=True)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_grid_formatter)
    console_handler.setLevel(log_level)
    logger_instance.addHandler(console_handler)

    # 添加 AbortError 过滤器 (过滤 Playwright 导航取消产生的良性错误)
    from logging_utils import AbortErrorFilter

    logger_instance.addFilter(AbortErrorFilter())

    # 保存原始流
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # 重定向print输出（如果需要）
    if redirect_print:
        print(
            "--- 注意：server.py 正在将其 print 输出重定向到日志系统 (文件、WebSocket 和控制台记录器) ---",
            file=original_stderr,
        )
        stdout_redirect_logger = logging.getLogger("AIStudioProxyServer.stdout")
        stdout_redirect_logger.setLevel(logging.INFO)
        stdout_redirect_logger.propagate = True
        sys.stdout = StreamToLogger(stdout_redirect_logger, logging.INFO)
        stderr_redirect_logger = logging.getLogger("AIStudioProxyServer.stderr")
        stderr_redirect_logger.setLevel(logging.ERROR)
        stderr_redirect_logger.propagate = True
        sys.stderr = StreamToLogger(stderr_redirect_logger, logging.ERROR)
    else:
        print(
            "--- server.py 的 print 输出未被重定向到日志系统 (将使用原始 stdout/stderr) ---",
            file=original_stderr,
        )

    # 配置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.ERROR)

    # 记录初始化信息
    logger_instance.info(
        "=" * 5 + " AIStudioProxyServer 日志系统已在 lifespan 中初始化 " + "=" * 5
    )
    logger_instance.info(f"日志级别设置为: {logging.getLevelName(log_level)}")
    logger_instance.debug(f"日志文件路径: {APP_LOG_FILE_PATH}")
    logger_instance.info("控制台日志处理器已添加。")
    logger_instance.info(
        f"Print 重定向 (由 SERVER_REDIRECT_PRINT 环境变量控制): {'启用' if redirect_print else '禁用'}"
    )

    # 安装全局异常处理器以捕获未处理的异常
    setup_global_exception_handlers()

    return original_stdout, original_stderr


def restore_original_streams(original_stdout: object, original_stderr: object) -> None:
    """
    恢复原始的stdout和stderr流

    Args:
        original_stdout: 原始的stdout流
        original_stderr: 原始的stderr流
    """
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    # 静默恢复，不输出额外日志噪音
