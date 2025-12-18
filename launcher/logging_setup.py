import logging
import logging.handlers
import os
import sys

from launcher.config import LAUNCHER_LOG_FILE_PATH, LOG_DIR
from logging_utils import GridFormatter, PlainGridFormatter, set_source

logger = logging.getLogger("CamoufoxLauncher")


def setup_launcher_logging(log_level: int = logging.INFO) -> None:
    """
    设置启动器日志系统 (使用 GridFormatter)

    Args:
        log_level: 日志级别
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    # 设置 source 为 LAUNCHER
    set_source("LAUNCHER")

    # 使用 PlainGridFormatter 用于文件日志
    file_log_formatter = PlainGridFormatter()

    # 使用 GridFormatter 用于控制台 (彩色输出)
    console_log_formatter = GridFormatter(show_tree=True, colorize=True)

    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(log_level)
    logger.propagate = False

    if os.path.exists(LAUNCHER_LOG_FILE_PATH):
        try:
            os.remove(LAUNCHER_LOG_FILE_PATH)
        except OSError:
            pass

    file_handler = logging.handlers.RotatingFileHandler(
        LAUNCHER_LOG_FILE_PATH,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
        mode="w",
    )
    file_handler.setFormatter(file_log_formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(console_log_formatter)
    logger.addHandler(stream_handler)

    logger.info(f"日志级别设置为: {logging.getLevelName(logger.getEffectiveLevel())}")
    logger.debug(f"日志文件路径: {LAUNCHER_LOG_FILE_PATH}")
