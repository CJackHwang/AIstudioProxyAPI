"""
UI State Management
"""

import asyncio
import json
import logging

from playwright.async_api import Page as AsyncPage

from logging_utils import set_request_id

logger = logging.getLogger("AIStudioProxyServer")


async def _verify_ui_state_settings(page: AsyncPage, req_id: str = "unknown") -> dict:
    """
    验证UI状态设置是否正确

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        dict: 包含验证结果的字典
    """
    # Don't set lifecycle phase names as request IDs - they appear as ghost prefixes
    # Only set actual request IDs (7-char alphanumerics)
    if req_id not in ("initial", "set_mod", "set_model", "reload", "unknown", ""):
        set_request_id(req_id)
    try:
        logger.debug("[State] 验证 UI 状态...")

        # 获取当前localStorage设置
        prefs_str = await page.evaluate(
            "() => localStorage.getItem('aiStudioUserPreference')"
        )

        if not prefs_str:
            logger.warning("localStorage.aiStudioUserPreference 不存在")
            return {
                "exists": False,
                "isAdvancedOpen": None,
                "areToolsOpen": None,
                "needsUpdate": True,
                "error": "localStorage不存在",
            }

        try:
            prefs = json.loads(prefs_str)
            is_advanced_open = prefs.get("isAdvancedOpen")
            are_tools_open = prefs.get("areToolsOpen")

            # 检查是否需要更新
            needs_update = (is_advanced_open is not True) or (
                are_tools_open is not True
            )

            result = {
                "exists": True,
                "isAdvancedOpen": is_advanced_open,
                "areToolsOpen": are_tools_open,
                "needsUpdate": needs_update,
                "prefs": prefs,
            }

            if needs_update:
                logger.debug(
                    f"[State] 状态不匹配: adv={is_advanced_open}, tools={are_tools_open} (需更新)"
                )
            # No log needed when state is correct
            return result

        except json.JSONDecodeError as e:
            logger.error(f"解析localStorage JSON失败: {e}")
            return {
                "exists": False,
                "isAdvancedOpen": None,
                "areToolsOpen": None,
                "needsUpdate": True,
                "error": f"JSON解析失败: {e}",
            }

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"验证UI状态设置时发生错误: {e}")
        return {
            "exists": False,
            "isAdvancedOpen": None,
            "areToolsOpen": None,
            "needsUpdate": True,
            "error": f"验证失败: {e}",
        }


async def _force_ui_state_settings(page: AsyncPage, req_id: str = "unknown") -> bool:
    """
    强制设置UI状态

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        bool: 设置是否成功
    """
    try:
        logger.debug("[State] 强制设置 UI 状态...")

        # 首先验证当前状态
        current_state = await _verify_ui_state_settings(page, req_id)

        if not current_state["needsUpdate"]:
            logger.debug("[State] 状态已正确，无需更新")
            return True

        # 获取现有preferences或创建新的
        prefs = current_state.get("prefs", {})

        # 强制设置关键配置
        prefs["isAdvancedOpen"] = True
        prefs["areToolsOpen"] = True

        # 保存到localStorage
        prefs_str = json.dumps(prefs)
        await page.evaluate(
            "(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)",
            prefs_str,
        )

        logger.debug("[State] 已设置: isAdvancedOpen=true, areToolsOpen=true")

        # 验证设置是否成功
        verify_state = await _verify_ui_state_settings(page, req_id)
        if not verify_state["needsUpdate"]:
            logger.debug("[State] 设置验证成功")
            return True
        else:
            logger.warning("UI状态设置验证失败，可能需要重试")
            return False

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"强制设置UI状态时发生错误: {e}")
        return False


async def _force_ui_state_with_retry(
    page: AsyncPage,
    req_id: str = "unknown",
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> bool:
    """
    带重试机制的UI状态强制设置

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）

    Returns:
        bool: 设置是否最终成功
    """
    for attempt in range(1, max_retries + 1):
        success = await _force_ui_state_settings(page, req_id)
        if success:
            return True

        if attempt < max_retries:
            logger.debug(f"[State] 重试 {attempt}/{max_retries}...")
            await asyncio.sleep(retry_delay)
        else:
            logger.warning(f"[State] {max_retries} 次尝试后仍失败")

    return False


async def _verify_and_apply_ui_state(page: AsyncPage, req_id: str = "unknown") -> bool:
    """
    验证并应用UI状态设置的完整流程

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        bool: 操作是否成功
    """
    try:
        logger.debug("[State] 开始验证并应用 UI 状态...")

        # 首先验证当前状态
        state = await _verify_ui_state_settings(page, req_id)

        if state["needsUpdate"]:
            logger.debug("[State] 需要更新，应用强制设置...")
            return await _force_ui_state_with_retry(page, req_id)
        else:
            return True

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"验证并应用UI状态设置时发生错误: {e}")
        return False
