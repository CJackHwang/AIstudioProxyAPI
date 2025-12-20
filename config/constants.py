"""
常量配置模块
包含所有固定的常量定义，如模型名称、标记符、文件名等
"""

import json
import os

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# --- 模型相关常量 ---
MODEL_NAME = os.environ.get("MODEL_NAME", "AI-Studio_Proxy_API")
CHAT_COMPLETION_ID_PREFIX = os.environ.get("CHAT_COMPLETION_ID_PREFIX", "chatcmpl-")
DEFAULT_FALLBACK_MODEL_ID = os.environ.get("DEFAULT_FALLBACK_MODEL_ID", "no model list")

# --- 默认参数值 ---
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_MAX_OUTPUT_TOKENS = int(os.environ.get("DEFAULT_MAX_OUTPUT_TOKENS", "65536"))
DEFAULT_TOP_P = float(os.environ.get("DEFAULT_TOP_P", "0.95"))
# --- 默认功能开关 ---
ENABLE_URL_CONTEXT = os.environ.get("ENABLE_URL_CONTEXT", "false").lower() in (
    "true",
    "1",
    "yes",
)
ENABLE_THINKING_BUDGET = os.environ.get("ENABLE_THINKING_BUDGET", "false").lower() in (
    "true",
    "1",
    "yes",
)
DEFAULT_THINKING_BUDGET = int(os.environ.get("DEFAULT_THINKING_BUDGET", "8192"))
# Separate defaults for Pro (2 levels) and Flash (4 levels)
_raw_level_pro = os.environ.get("DEFAULT_THINKING_LEVEL_PRO", "high").lower()
DEFAULT_THINKING_LEVEL_PRO = (
    _raw_level_pro if _raw_level_pro in ("high", "low") else "high"
)
_raw_level_flash = os.environ.get("DEFAULT_THINKING_LEVEL_FLASH", "high").lower()
DEFAULT_THINKING_LEVEL_FLASH = (
    _raw_level_flash
    if _raw_level_flash in ("high", "medium", "low", "minimal")
    else "high"
)
ENABLE_GOOGLE_SEARCH = os.environ.get("ENABLE_GOOGLE_SEARCH", "false").lower() in (
    "true",
    "1",
    "yes",
)

# 默认停止序列 - 支持 JSON 格式配置
try:
    DEFAULT_STOP_SEQUENCES = json.loads(os.environ.get("DEFAULT_STOP_SEQUENCES", "[]"))
except (json.JSONDecodeError, TypeError):
    DEFAULT_STOP_SEQUENCES = []  # type: ignore[reportConstantRedefinition]  # 回退到默认值 (空列表)

# --- URL模式 ---
AI_STUDIO_URL_PATTERN = os.environ.get("AI_STUDIO_URL_PATTERN", "aistudio.google.com/")
MODELS_ENDPOINT_URL_CONTAINS = os.environ.get(
    "MODELS_ENDPOINT_URL_CONTAINS", "MakerSuiteService/ListModels"
)

# --- 输入标记符 ---
USER_INPUT_START_MARKER_SERVER = os.environ.get(
    "USER_INPUT_START_MARKER_SERVER", "__USER_INPUT_START__"
)
USER_INPUT_END_MARKER_SERVER = os.environ.get(
    "USER_INPUT_END_MARKER_SERVER", "__USER_INPUT_END__"
)

# --- 文件名常量 ---
EXCLUDED_MODELS_FILENAME = os.environ.get(
    "EXCLUDED_MODELS_FILENAME", "excluded_models.txt"
)

# --- 流状态配置 ---
STREAM_TIMEOUT_LOG_STATE = {
    "consecutive_timeouts": 0,
    "last_error_log_time": 0.0,  # 使用 time.monotonic()
    "suppress_until_time": 0.0,  # 使用 time.monotonic()
    "max_initial_errors": int(os.environ.get("STREAM_MAX_INITIAL_ERRORS", "3")),
    "warning_interval_after_suppress": float(
        os.environ.get("STREAM_WARNING_INTERVAL_AFTER_SUPPRESS", "60.0")
    ),
    "suppress_duration_after_initial_burst": float(
        os.environ.get("STREAM_SUPPRESS_DURATION_AFTER_INITIAL_BURST", "400.0")
    ),
}
