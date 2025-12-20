# --- config/selector_utils.py ---
"""
选择器工具模块
提供用于处理动态 UI 结构的选择器回退逻辑
"""

import asyncio
import logging
from typing import List, Optional, Tuple

from playwright.async_api import Locator, Page

from config.timeouts import (
    SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS,
    SELECTOR_VISIBILITY_TIMEOUT_MS,
)

logger = logging.getLogger("AIStudioProxyServer")


# --- 输入区域容器选择器 (按优先级排序) ---
# Google AI Studio 会不定期更改 UI 结构，此列表包含所有已知的容器选择器
# 优先尝试当前 UI，回退到旧 UI
# 注意: 顺序很重要！第一个选择器会被优先尝试，每个失败的选择器会增加启动时间
INPUT_WRAPPER_SELECTORS: List[str] = [
    # 当前 UI 结构 (2024-12 确认有效)
    "ms-chunk-editor",
    # 备用 UI 结构 (可能在其他版本或区域有效)
    "ms-prompt-input-wrapper .prompt-input-wrapper",
    "ms-prompt-input-wrapper",
    # 过渡期 UI (ms-prompt-box) - 历史版本，保留作为回退
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
    timeout_per_selector: int = SELECTOR_VISIBILITY_TIMEOUT_MS,
    existence_check_timeout: int = SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS,  # kept for API compat
    fallback_timeout_per_selector: int = SELECTOR_VISIBILITY_TIMEOUT_MS,  # kept for API compat
) -> Tuple[Optional[Locator], Optional[str]]:
    """
    尝试多个选择器并返回第一个可见元素的 Locator。

    使用主动 DOM 监听策略 (Playwright MutationObserver):
    - 对第一个选择器使用较长超时（主选择器，最可能成功）
    - 后续选择器使用较短超时作为回退

    Args:
        page: Playwright 页面实例
        selectors: 要尝试的选择器列表（按优先级排序）
        description: 元素描述（用于日志记录）
        timeout_per_selector: 主选择器的超时时间（毫秒）

    Returns:
        Tuple[Optional[Locator], Optional[str]]:
            - 可见元素的 Locator，如果都失败则为 None
            - 成功的选择器字符串，如果都失败则为 None
    """
    from playwright.async_api import expect as expect_async

    if not selectors:
        logger.warning(f"[Selector] {description}: 没有提供选择器")
        return None, None

    # 主选择器使用较长超时（最可能成功，值得等待）
    primary_selector = selectors[0]
    primary_timeout = timeout_per_selector

    # 回退选择器使用较短超时
    fallback_timeout = min(2000, timeout_per_selector // 2)

    logger.debug(
        f"[Selector] {description}: 开始主动监听 '{primary_selector}' (超时: {primary_timeout}ms)"
    )

    # 尝试主选择器（使用 Playwright 的 MutationObserver 主动监听）
    try:
        locator = page.locator(primary_selector)
        await expect_async(locator).to_be_visible(timeout=primary_timeout)
        logger.debug(f"[Selector] {description}: '{primary_selector}' 元素可见")
        return locator, primary_selector
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug(
            f"[Selector] {description}: '{primary_selector}' 超时 ({primary_timeout}ms) - {type(e).__name__}"
        )

    # 回退到其他选择器
    if len(selectors) > 1:
        logger.debug(
            f"[Selector] {description}: 尝试 {len(selectors) - 1} 个回退选择器 (超时: {fallback_timeout}ms)"
        )
        for idx, selector in enumerate(selectors[1:], 2):
            try:
                locator = page.locator(selector)
                await expect_async(locator).to_be_visible(timeout=fallback_timeout)
                logger.debug(
                    f"[Selector] {description}: '{selector}' 元素可见 (回退 {idx}/{len(selectors)})"
                )
                return locator, selector
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    f"[Selector] {description}: '{selector}' 超时 (回退 {idx}/{len(selectors)})"
                )

    logger.warning(
        f"[Selector] {description}: 所有选择器均未找到可见元素 "
        f"(尝试了 {len(selectors)} 个选择器)"
    )
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
