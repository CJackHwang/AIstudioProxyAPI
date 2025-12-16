# --- config/selector_utils.py ---
"""
选择器工具模块
提供用于处理动态 UI 结构的选择器回退逻辑
"""

import asyncio
import logging
from typing import List, Optional, Tuple

from playwright.async_api import Locator, Page

logger = logging.getLogger("AIStudioProxyServer")


# --- 输入区域容器选择器 (按优先级排序) ---
# Google AI Studio 会不定期更改 UI 结构，此列表包含所有已知的容器选择器
# 优先尝试当前 UI，回退到旧 UI
INPUT_WRAPPER_SELECTORS: List[str] = [
    # 当前 UI 结构 (ms-prompt-input-wrapper / ms-chunk-editor)
    "ms-prompt-input-wrapper .prompt-input-wrapper",
    "ms-prompt-input-wrapper",
    "ms-chunk-editor",
    # 过渡期 UI (ms-prompt-box) - 已弃用但保留作为回退
    "ms-prompt-box .prompt-box-container",
    "ms-prompt-box",
]

# --- 自动调整容器选择器 ---
AUTOSIZE_WRAPPER_SELECTORS: List[str] = [
    # 当前 UI 结构
    "ms-prompt-input-wrapper .text-wrapper",
    "ms-prompt-input-wrapper ms-autosize-textarea",
    "ms-chunk-input .text-wrapper",
    "ms-autosize-textarea",
    # 过渡期 UI (ms-prompt-box) - 已弃用但保留作为回退
    "ms-prompt-box .text-wrapper",
    "ms-prompt-box ms-autosize-textarea",
]


async def find_first_visible_locator(
    page: Page,
    selectors: List[str],
    description: str = "element",
    timeout_per_selector: int = 1000,
) -> Tuple[Optional[Locator], Optional[str]]:
    """
    尝试多个选择器并返回第一个可见元素的 Locator。

    与 find_first_available_locator 类似，但会等待元素可见。
    适用于需要等待 UI 渲染完成的场景。

    Args:
        page: Playwright 页面实例
        selectors: 要尝试的选择器列表（按优先级排序）
        description: 元素描述（用于日志记录）
        timeout_per_selector: 每个选择器的等待超时时间（毫秒）

    Returns:
        Tuple[Optional[Locator], Optional[str]]:
            - 可见元素的 Locator，如果都失败则为 None
            - 成功的选择器字符串，如果都失败则为 None
    """
    from playwright.async_api import expect as expect_async

    for selector in selectors:
        try:
            locator = page.locator(selector)
            await expect_async(locator).to_be_visible(timeout=timeout_per_selector)
            logger.debug(f"{description}: 选择器 '{selector}' 元素可见")
            return locator, selector
        except asyncio.CancelledError:
            raise
        except Exception:
            # 元素不可见或超时，继续尝试下一个
            continue

    logger.warning(f"{description}: 所有选择器均未找到可见元素")
    return None, None


def build_combined_selector(selectors: List[str]) -> str:
    """
    将多个选择器组合为单个 CSS 选择器字符串（用逗号分隔）。

    这对于创建能匹配多个 UI 结构的选择器很有用。

    Args:
        selectors: 要组合的选择器列表

    Returns:
        str: 组合后的选择器字符串

    Example:
        combined = build_combined_selector([
            "ms-prompt-box .text-wrapper",
            "ms-prompt-input-wrapper .text-wrapper"
        ])
        # 返回: "ms-prompt-box .text-wrapper, ms-prompt-input-wrapper .text-wrapper"
    """
    return ", ".join(selectors)
