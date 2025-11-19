import logging
import logging.handlers
import os
import sys
from typing import Tuple

class SSLWarningFilter(logging.Filter):
    def filter(self, record):
        return "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" not in record.getMessage()

from config import LOG_DIR, ACTIVE_AUTH_DIR, SAVED_AUTH_DIR, APP_LOG_FILE_PATH
from models import StreamToLogger, WebSocketLogHandler, WebSocketConnectionManager


def setup_server_logging(
    logger_instance: logging.Logger,
    log_ws_manager: WebSocketConnectionManager,
    log_level_name: str = "INFO",
    redirect_print_str: str = "false"
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
    redirect_print = redirect_print_str.lower() in ('true', '1', 'yes')
    
    # 创建必要的目录
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(ACTIVE_AUTH_DIR, exist_ok=True)
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
    
    # 设置文件日志格式器
    file_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s')
    
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
            print(f"警告 (setup_server_logging): 尝试移除旧的 app.log 文件 '{APP_LOG_FILE_PATH}' 失败: {e}。将依赖 mode='w' 进行截断。", file=sys.__stderr__)
    
    # 添加文件处理器
    file_handler = logging.handlers.RotatingFileHandler(
        APP_LOG_FILE_PATH, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8', mode='w'
    )
    file_handler.setFormatter(file_log_formatter)
    logger_instance.addHandler(file_handler)
    
    # 添加WebSocket处理器
    if log_ws_manager is None:
        print("严重警告 (setup_server_logging): log_ws_manager 未初始化！WebSocket 日志功能将不可用。", file=sys.__stderr__)
    else:
        ws_handler = WebSocketLogHandler(log_ws_manager)
        ws_handler.setLevel(logging.INFO)
        logger_instance.addHandler(ws_handler)
    
    # 添加控制台处理器
    console_server_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s [SERVER] - %(message)s')
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_server_log_formatter)
    console_handler.setLevel(log_level)
    logger_instance.addHandler(console_handler)
    
    # 保存原始流
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    # 重定向print输出（如果需要）
    if redirect_print:
        print("--- 注意：server.py 正在将其 print 输出重定向到日志系统 (文件、WebSocket 和控制台记录器) ---", file=original_stderr)
        stdout_redirect_logger = logging.getLogger("AIStudioProxyServer.stdout")
        stdout_redirect_logger.setLevel(logging.INFO)
        stdout_redirect_logger.propagate = True
        sys.stdout = StreamToLogger(stdout_redirect_logger, logging.INFO)
        stderr_redirect_logger = logging.getLogger("AIStudioProxyServer.stderr")
        stderr_redirect_logger.setLevel(logging.ERROR)
        stderr_redirect_logger.propagate = True
        sys.stderr = StreamToLogger(stderr_redirect_logger, logging.ERROR)
    else:
        print("--- server.py 的 print 输出未被重定向到日志系统 (将使用原始 stdout/stderr) ---", file=original_stderr)
    
    # 配置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    
    # Suppress asyncio/SSL warnings
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.setLevel(logging.CRITICAL)
    asyncio_logger.addFilter(SSLWarningFilter())
    
    # 记录初始化信息
    logger_instance.info("=" * 5 + " AIStudioProxyServer 日志系统已在 lifespan 中初始化 " + "=" * 5)
    logger_instance.info(f"日志级别设置为: {logging.getLevelName(log_level)}")
    logger_instance.info(f"日志文件路径: {APP_LOG_FILE_PATH}")
    logger_instance.info(f"控制台日志处理器已添加。")
    logger_instance.info(f"Print 重定向 (由 SERVER_REDIRECT_PRINT 环境变量控制): {'启用' if redirect_print else '禁用'}")
    
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
    print("已恢复 server.py 的原始 stdout 和 stderr 流。", file=sys.__stderr__) 