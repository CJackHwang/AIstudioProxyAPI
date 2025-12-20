# --- browser_utils/operations_modules/errors.py ---
import asyncio
import json
import logging
import traceback
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from playwright.async_api import Error as PlaywrightAsyncError
from playwright.async_api import Page as AsyncPage
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config import ERROR_TOAST_SELECTOR
from logging_utils import set_request_id

logger = logging.getLogger("AIStudioProxyServer")


class ErrorCategory(Enum):
    """错误类型分类，用于标准化错误快照保存行为。"""

    TIMEOUT = "timeout"  # 超时错误 (Playwright TimeoutError, asyncio.TimeoutError)
    PLAYWRIGHT = "playwright"  # Playwright 浏览器错误
    NETWORK = "network"  # 网络/连接错误
    CLIENT = "client"  # 客户端断开连接
    VALIDATION = "validation"  # 验证错误 (ValueError, TypeError)
    CANCELLED = "cancelled"  # 任务取消
    UNKNOWN = "unknown"  # 未分类错误


def categorize_error(exception: BaseException) -> ErrorCategory:
    """
    根据异常类型自动分类错误。

    Args:
        exception: 要分类的异常对象

    Returns:
        ErrorCategory: 错误分类枚举值
    """
    exc_type = type(exception)
    exc_name = exc_type.__name__.lower()
    exc_module = exc_type.__module__ or ""

    # 取消错误 - 特殊处理
    if isinstance(exception, asyncio.CancelledError):
        return ErrorCategory.CANCELLED

    # 超时错误
    if isinstance(exception, (PlaywrightTimeoutError, asyncio.TimeoutError)):
        return ErrorCategory.TIMEOUT
    if "timeout" in exc_name:
        return ErrorCategory.TIMEOUT

    # Playwright 错误
    if isinstance(exception, PlaywrightAsyncError):
        return ErrorCategory.PLAYWRIGHT
    if "playwright" in exc_module.lower():
        return ErrorCategory.PLAYWRIGHT

    # 网络/连接错误
    network_keywords = ["connection", "network", "socket", "http", "ssl", "connect"]
    if any(kw in exc_name for kw in network_keywords):
        return ErrorCategory.NETWORK
    if any(kw in str(exception).lower() for kw in ["connection", "network", "socket"]):
        return ErrorCategory.NETWORK

    # 客户端断开
    if "clientdisconnected" in exc_name or "disconnect" in exc_name:
        return ErrorCategory.CLIENT

    # 验证错误
    if isinstance(exception, (ValueError, TypeError, AttributeError)):
        return ErrorCategory.VALIDATION

    return ErrorCategory.UNKNOWN


async def detect_and_extract_page_error(page: AsyncPage, req_id: str) -> Optional[str]:
    """检测并提取页面错误"""
    set_request_id(req_id)
    error_toast_locator = page.locator(ERROR_TOAST_SELECTOR).last
    try:
        await error_toast_locator.wait_for(state="visible", timeout=500)
        message_locator = error_toast_locator.locator("span.content-text")
        error_message = await message_locator.text_content(timeout=500)
        if error_message:
            logger.error(f"检测到并提取错误消息: {error_message}")
            return error_message.strip()
        else:
            logger.warning("检测到错误提示框，但无法提取消息。")
            return "检测到错误提示框，但无法提取特定消息。"
    except PlaywrightAsyncError:
        return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"检查页面错误时出错: {e}")
        return None


async def save_minimal_snapshot(
    error_name: str,
    req_id: str = "unknown",
    error_category: Optional[ErrorCategory] = None,
    error_exception: Optional[BaseException] = None,
    additional_context: Optional[dict] = None,
) -> str:
    """
    保存最小化错误快照 (无需浏览器/页面)。

    当浏览器或页面不可用时，仍保存有价值的调试信息。
    现在包含更多上下文: 环境变量、队列状态、锁状态、人类可读摘要。

    Args:
        error_name: 错误名称
        req_id: 请求 ID
        error_category: 错误分类 (可选)
        error_exception: 触发快照的异常 (可选)
        additional_context: 额外上下文信息 (可选)

    Returns:
        str: 快照目录路径，失败时返回空字符串
    """
    try:
        import os
        import platform
        import sys

        # 生成时间戳 (使用本地时间)
        now = datetime.now().astimezone()
        iso_timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        date_str = iso_timestamp.split("T")[0]
        time_component = iso_timestamp.split("T")[1].replace(":", "-").replace(".", "-")

        # 创建目录结构 (使用项目根目录的 errors_py)
        # Path: operations_modules -> browser_utils -> project_root
        base_error_dir = Path(__file__).parent.parent.parent / "errors_py"
        date_dir = base_error_dir / date_str
        snapshot_dir_name = f"{time_component}_{req_id}_{error_name}_minimal"
        snapshot_dir = date_dir / snapshot_dir_name
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # 自动分类错误 (如果未提供分类且有异常)
        if error_category is None and error_exception is not None:
            error_category = categorize_error(error_exception)

        # === 1. 构建详细元数据 ===
        metadata: dict = {
            "snapshot_info": {
                "type": "minimal",
                "reason": "Browser/page unavailable",
                "timestamp_iso": iso_timestamp,
                "timestamp_local": now.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            },
            "error": {
                "name": error_name,
                "category": error_category.value if error_category else "unknown",
                "req_id": req_id,
            },
            "system": {
                "platform": platform.platform(),
                "python_version": sys.version.split()[0],
                "pid": os.getpid(),
                "cwd": os.getcwd(),
            },
        }

        # 添加异常详情
        if error_exception is not None:
            tb_lines = traceback.format_exception(
                type(error_exception), error_exception, error_exception.__traceback__
            )
            metadata["exception"] = {
                "type": type(error_exception).__name__,
                "module": type(error_exception).__module__,
                "message": str(error_exception),
                "args": [str(a) for a in getattr(error_exception, "args", [])[:5]],
                "traceback": "".join(tb_lines),
            }

        # 添加额外上下文
        if additional_context:
            metadata["additional_context"] = additional_context

        # === 2. 捕获应用状态 ===
        try:
            import server

            # 基本标志
            metadata["application_state"] = {
                "flags": {
                    "is_playwright_ready": getattr(server, "is_playwright_ready", None),
                    "is_browser_connected": getattr(
                        server, "is_browser_connected", None
                    ),
                    "is_page_ready": getattr(server, "is_page_ready", None),
                    "is_initializing": getattr(server, "is_initializing", None),
                },
                "current_model": getattr(server, "current_ai_studio_model_id", None),
                "excluded_models_count": len(getattr(server, "excluded_model_ids", [])),
            }

            # 队列状态
            rq = getattr(server, "request_queue", None)
            if rq:
                try:
                    metadata["application_state"]["request_queue_size"] = rq.qsize()
                except Exception:
                    metadata["application_state"]["request_queue_size"] = "N/A"

            # 锁状态
            pl = getattr(server, "processing_lock", None)
            ml = getattr(server, "model_switching_lock", None)
            metadata["application_state"]["locks"] = {
                "processing_lock": pl.locked()
                if pl and hasattr(pl, "locked")
                else None,
                "model_switching_lock": ml.locked()
                if ml and hasattr(ml, "locked")
                else None,
            }

            # 流队列
            sq = getattr(server, "STREAM_QUEUE", None)
            metadata["application_state"]["stream_queue_active"] = sq is not None

        except Exception as server_err:
            metadata["application_state"] = {"error": str(server_err)}

        # === 3. 环境变量 (安全过滤) ===
        safe_env_keys = [
            "HEADLESS",
            "DEBUG_LOGS_ENABLED",
            "DEFAULT_MODEL",
            "LAUNCH_MODE",
            "RESPONSE_COMPLETION_TIMEOUT",
            "HOST_OS_FOR_SHORTCUT",
            "PORT",
            "STREAM_PROXY_PORT",
            "LOG_LEVEL",
        ]
        metadata["environment"] = {
            k: os.environ.get(k, "not set") for k in safe_env_keys
        }

        # === 4. 保存 metadata.json ===
        metadata_path = snapshot_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # === 5. 创建人类可读 SUMMARY.txt ===
        summary_path = snapshot_dir / "SUMMARY.txt"
        summary_lines = [
            "=" * 60,
            "ERROR SNAPSHOT SUMMARY",
            "=" * 60,
            "",
            f"Timestamp: {metadata['snapshot_info']['timestamp_local']}",
            f"Request ID: {req_id}",
            f"Error Name: {error_name}",
            f"Category: {error_category.value if error_category else 'unknown'}",
            "Snapshot Type: MINIMAL (browser unavailable)",
            "",
            "-" * 60,
            "EXCEPTION DETAILS",
            "-" * 60,
        ]

        if error_exception:
            summary_lines.extend(
                [
                    f"Type: {type(error_exception).__name__}",
                    f"Message: {error_exception}",
                    "",
                    "Traceback:",
                    metadata["exception"]["traceback"],
                ]
            )
        else:
            summary_lines.append("No exception provided")

        summary_lines.extend(
            [
                "",
                "-" * 60,
                "APPLICATION STATE",
                "-" * 60,
            ]
        )

        app_state = metadata.get("application_state", {})
        flags = app_state.get("flags", {})
        for key, val in flags.items():
            summary_lines.append(f"  {key}: {val}")

        summary_lines.extend(
            [
                f"  Current Model: {app_state.get('current_model', 'N/A')}",
                f"  Queue Size: {app_state.get('request_queue_size', 'N/A')}",
                "",
                "-" * 60,
                "FILES IN SNAPSHOT",
                "-" * 60,
                "  - SUMMARY.txt (this file)",
                "  - metadata.json (full details)",
                "",
                "=" * 60,
            ]
        )

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))

        logger.info(f"[Snapshot] 保存最小化快照: {snapshot_dir.name}")
        return str(snapshot_dir)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[Snapshot] 最小化快照保存失败: {e}")
        return ""


async def save_error_snapshot(
    error_name: str = "error",
    error_exception: Optional[Exception] = None,
    error_stage: str = "",
    additional_context: Optional[dict] = None,
    locators: Optional[dict] = None,
):
    """
    保存错误快照 (Robust wrapper with guaranteed save).

    This function ensures that SOMETHING is always saved when called.
    If browser/page is unavailable, falls back to minimal snapshot.

    Args:
        error_name: Error name with optional req_id suffix (e.g., "error_hbfu521")
        error_exception: The exception that triggered the snapshot (optional)
        error_stage: Description of the error stage (optional)
        additional_context: Extra context dict to include in metadata (optional)
        locators: Dict of named locators to capture states for (optional)
    """
    # 解析 req_id
    name_parts = error_name.split("_")
    req_id = (
        name_parts[-1]
        if len(name_parts) > 1 and len(name_parts[-1]) == 7
        else "unknown"
    )

    # 自动分类错误
    error_category = None
    if error_exception is not None:
        error_category = categorize_error(error_exception)
        # 如果是取消错误，不保存快照
        if error_category == ErrorCategory.CANCELLED:
            logger.debug(f"[Snapshot] 跳过取消错误快照: {error_name}")
            return

    # 添加分类到上下文
    context = additional_context.copy() if additional_context else {}
    if error_category:
        context["error_category"] = error_category.value

    try:
        from browser_utils.debug_utils import save_error_snapshot_enhanced

        await save_error_snapshot_enhanced(
            error_name,
            error_exception=error_exception,
            error_stage=error_stage,
            additional_context=context,
            locators=locators,
        )
    except asyncio.CancelledError:
        raise
    except Exception as enhanced_err:
        # 增强快照失败，尝试最小化快照
        logger.warning(f"[Snapshot] 增强快照失败 ({enhanced_err})，尝试最小化快照...")
        await save_minimal_snapshot(
            error_name=error_name,
            req_id=req_id,
            error_category=error_category,
            error_exception=error_exception,
            additional_context=context,
        )
