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
    existence_check_timeout: int = SELECTOR_EXISTENCE_CHECK_TIMEOUT_MS,
    fallback_timeout_per_selector: int = SELECTOR_VISIBILITY_TIMEOUT_MS,
) -> Tuple[Optional[Locator], Optional[str]]:
    """
    尝试多个选择器并返回第一个可见元素的 Locator。

    使用三阶段优化策略:
    1. 快速存在性检查 (count) - 避免对不存在的选择器等待完整超时
    2. 可见性等待 - 仅对存在的元素进行完整超时等待
    3. 回退模式 - 如果 DOM 未加载，使用较短超时依次尝试所有选择器

    Args:
        page: Playwright 页面实例
        selectors: 要尝试的选择器列表（按优先级排序）
        description: 元素描述（用于日志记录）
        timeout_per_selector: Phase 2 每个选择器的可见性等待超时时间（毫秒）
        existence_check_timeout: Phase 1 存在性检查的超时时间（毫秒），默认500ms
        fallback_timeout_per_selector: Phase 3 回退模式每个选择器的超时时间（毫秒），
            默认5000ms，防止 N 个选择器 × 长超时 = 慢启动

    Returns:
        Tuple[Optional[Locator], Optional[str]]:
            - 可见元素的 Locator，如果都失败则为 None
            - 成功的选择器字符串，如果都失败则为 None
    """
    from playwright.async_api import expect as expect_async

    # Phase 1: 快速存在性检查，找出存在的选择器
    existing_selectors: List[str] = []
    phase1_timeouts: List[str] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            # 快速检查元素是否存在于 DOM 中
            count = await asyncio.wait_for(
                locator.count(),
                timeout=existence_check_timeout / 1000,  # 转换为秒
            )
            if count > 0:
                existing_selectors.append(selector)
                logger.debug(
                    f"[Selector] {description}: '{selector}' 存在于 DOM ({count}个)"
                )
            else:
                logger.debug(
                    f"[Selector] {description}: '{selector}' 不存在于 DOM (count=0)"
                )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            phase1_timeouts.append(selector)
            logger.debug(
                f"[Selector] {description}: '{selector}' 存在性检查超时 "
                f"({existence_check_timeout}ms)"
            )
        except Exception as e:
            logger.debug(
                f"[Selector] {description}: '{selector}' 存在性检查异常: {type(e).__name__}"
            )

    # 如果有超时，记录汇总日志
    if phase1_timeouts:
        logger.debug(
            f"[Selector] {description}: Phase 1 完成 - "
            f"找到 {len(existing_selectors)} 个, 超时 {len(phase1_timeouts)} 个"
        )

    # Phase 2: 对存在的选择器进行可见性等待
    for selector in existing_selectors:
        try:
            locator = page.locator(selector)
            await expect_async(locator).to_be_visible(timeout=timeout_per_selector)
            logger.debug(f"[Selector] {description}: '{selector}' 元素可见")
            return locator, selector
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(
                f"[Selector] {description}: '{selector}' 可见性等待失败 "
                f"({timeout_per_selector}ms) - {type(e).__name__}"
            )

    # Phase 3: 回退 - 如果快速检查都失败，使用较短超时依次等待所有选择器
    # 这处理了元素尚未加载到 DOM 的情况 (例如页面仍在渲染)
    # 使用 fallback_timeout_per_selector (默认5s) 而非 timeout_per_selector (可能30s)
    # 以避免 N 个选择器 × 长超时 = 慢启动
    if not existing_selectors and selectors:
        logger.debug(
            f"[Selector] {description}: Phase 1 未找到任何元素，进入 Phase 3 回退模式 "
            f"(每个选择器超时: {fallback_timeout_per_selector}ms, 共 {len(selectors)} 个)"
        )
        for idx, selector in enumerate(selectors, 1):
            try:
                locator = page.locator(selector)
                await expect_async(locator).to_be_visible(
                    timeout=fallback_timeout_per_selector
                )
                logger.debug(
                    f"[Selector] {description}: '{selector}' 元素可见 (回退 {idx}/{len(selectors)})"
                )
                return locator, selector
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(
                    f"[Selector] {description}: '{selector}' 回退超时 "
                    f"({fallback_timeout_per_selector}ms, {idx}/{len(selectors)}) - {type(e).__name__}"
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
