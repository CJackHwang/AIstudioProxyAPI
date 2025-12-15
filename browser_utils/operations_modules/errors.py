# --- browser_utils/operations_modules/errors.py ---
import asyncio
import logging
from typing import Optional

from playwright.async_api import Error as PlaywrightAsyncError
from playwright.async_api import Page as AsyncPage

from config import ERROR_TOAST_SELECTOR
from logging_utils import set_request_id

logger = logging.getLogger("AIStudioProxyServer")


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


async def save_error_snapshot(
    error_name: str = "error",
    error_exception: Optional[Exception] = None,
    error_stage: str = "",
    additional_context: Optional[dict] = None,
    locators: Optional[dict] = None,
):
    """
    保存错误快照 (Enhanced wrapper).

    This function supports both legacy usage and enhanced context capture.
    For new code, use save_comprehensive_snapshot() from debug_utils directly
    for even more control.

    Args:
        error_name: Error name with optional req_id suffix (e.g., "error_hbfu521")
        error_exception: The exception that triggered the snapshot (optional)
        error_stage: Description of the error stage (optional)
        additional_context: Extra context dict to include in metadata (optional)
        locators: Dict of named locators to capture states for (optional)
    """
    from browser_utils.debug_utils import save_error_snapshot_enhanced

    await save_error_snapshot_enhanced(
        error_name,
        error_exception=error_exception,
        error_stage=error_stage,
        additional_context=additional_context,
        locators=locators,
    )
