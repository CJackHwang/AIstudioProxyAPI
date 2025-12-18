"""
超时和时间配置模块
包含所有超时时间、轮询间隔等时间相关配置
"""

import os

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# --- 响应等待配置 ---
RESPONSE_COMPLETION_TIMEOUT = int(
    os.environ.get("RESPONSE_COMPLETION_TIMEOUT", "300000")
)  # 5 minutes total timeout (in ms)
INITIAL_WAIT_MS_BEFORE_POLLING = int(
    os.environ.get("INITIAL_WAIT_MS_BEFORE_POLLING", "500")
)  # ms, initial wait before polling for response completion

# --- 轮询间隔配置 ---
POLLING_INTERVAL = int(os.environ.get("POLLING_INTERVAL", "300"))  # ms
POLLING_INTERVAL_STREAM = int(os.environ.get("POLLING_INTERVAL_STREAM", "180"))  # ms

# --- 静默超时配置 ---
SILENCE_TIMEOUT_MS = int(os.environ.get("SILENCE_TIMEOUT_MS", "60000"))  # ms

# --- 页面操作超时配置 ---
POST_SPINNER_CHECK_DELAY_MS = int(os.environ.get("POST_SPINNER_CHECK_DELAY_MS", "500"))
FINAL_STATE_CHECK_TIMEOUT_MS = int(
    os.environ.get("FINAL_STATE_CHECK_TIMEOUT_MS", "1500")
)
POST_COMPLETION_BUFFER = int(os.environ.get("POST_COMPLETION_BUFFER", "700"))

# --- 清理聊天相关超时 ---
CLEAR_CHAT_VERIFY_TIMEOUT_MS = int(
    os.environ.get("CLEAR_CHAT_VERIFY_TIMEOUT_MS", "5000")
)
CLEAR_CHAT_VERIFY_INTERVAL_MS = int(
    os.environ.get("CLEAR_CHAT_VERIFY_INTERVAL_MS", "2000")
)

# --- 点击和剪贴板操作超时 ---
CLICK_TIMEOUT_MS = int(os.environ.get("CLICK_TIMEOUT_MS", "3000"))
CLIPBOARD_READ_TIMEOUT_MS = int(os.environ.get("CLIPBOARD_READ_TIMEOUT_MS", "3000"))

# --- 元素等待超时 ---
WAIT_FOR_ELEMENT_TIMEOUT_MS = int(
    os.environ.get("WAIT_FOR_ELEMENT_TIMEOUT_MS", "10000")
)  # Timeout for waiting for elements like overlays

# --- 流相关配置 ---
PSEUDO_STREAM_DELAY = float(os.environ.get("PSEUDO_STREAM_DELAY", "0.01"))

# --- 快速失败配置 (Fast-Fail) ---
# 发送按钮启用超时 - 降低以实现快速失败检测 (从 100000ms 降至 5000ms)
SUBMIT_BUTTON_ENABLE_TIMEOUT_MS = int(
    os.environ.get("SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", "5000")
)

# --- 选择器超时配置 ---
# 快速存在性检查超时 (用于 DOM 中元素是否存在的快速检测)
SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS = int(
    os.environ.get("SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS", "500")
)
# 元素可见性等待超时 (一般 UI 操作)
SELECTOR_VISIBILITY_TIMEOUT_MS = int(
    os.environ.get("SELECTOR_VISIBILITY_TIMEOUT_MS", "5000")
)
# 启动时关键选择器可见性超时 (允许稍长，因为页面可能仍在加载)
STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS = int(
    os.environ.get("STARTUP_SELECTOR_VISIBILITY_TIMEOUT_MS", "30000")
)
