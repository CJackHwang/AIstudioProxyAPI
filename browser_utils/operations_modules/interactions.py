# --- browser_utils/operations_modules/interactions.py ---
import asyncio
import logging
import time
from typing import Callable, Optional

from playwright.async_api import (
    Error as PlaywrightAsyncError,
)
from playwright.async_api import (
    Locator,
)
from playwright.async_api import (
    Page as AsyncPage,
)

from browser_utils.operations_modules.errors import save_error_snapshot
from config import (
    CHAT_TURN_SELECTOR,
    CLICK_TIMEOUT_MS,
    DEBUG_LOGS_ENABLED,
    INITIAL_WAIT_MS_BEFORE_POLLING,
    RESPONSE_COMPLETION_TIMEOUT,
)
from models import ClientDisconnectedError

logger = logging.getLogger("AIStudioProxyServer")


async def get_raw_text_content(
    response_element: Locator, previous_text: str, req_id: str
) -> str:
    """从响应元素获取原始文本内容"""
    raw_text = previous_text
    try:
        await response_element.wait_for(state="attached", timeout=1000)
        pre_element = response_element.locator("pre").last
        pre_found_and_visible = False
        try:
            await pre_element.wait_for(state="visible", timeout=250)
            pre_found_and_visible = True
        except PlaywrightAsyncError:
            pass

        if pre_found_and_visible:
            try:
                raw_text = await pre_element.inner_text(timeout=500)
            except PlaywrightAsyncError as pre_err:
                if DEBUG_LOGS_ENABLED:
                    logger.debug(f"(获取原始文本) 获取 pre 元素内部文本失败: {pre_err}")
        else:
            try:
                raw_text = await response_element.inner_text(timeout=500)
            except PlaywrightAsyncError as e_parent:
                if DEBUG_LOGS_ENABLED:
                    logger.debug(f"(获取原始文本) 获取响应元素内部文本失败: {e_parent}")
    except PlaywrightAsyncError as e_parent:
        if DEBUG_LOGS_ENABLED:
            logger.debug(f"(获取原始文本) 响应元素未准备好: {e_parent}")
    except asyncio.CancelledError:
        raise
    except Exception as e_unexpected:
        logger.warning(f"(获取原始文本) 意外错误: {e_unexpected}")

    if raw_text != previous_text:
        if DEBUG_LOGS_ENABLED:
            preview = raw_text[:100].replace("\n", "\\n")
            logger.debug(
                f"(获取原始文本) 文本已更新，长度: {len(raw_text)}，预览: '{preview}...'"
            )
    return raw_text


async def get_response_via_edit_button(
    page: AsyncPage, req_id: str, check_client_disconnected: Callable
) -> Optional[str]:
    """通过编辑按钮获取响应"""
    logger.info("(Helper) 尝试通过编辑按钮获取响应...")
    last_message_container = page.locator(CHAT_TURN_SELECTOR).last
    edit_button = last_message_container.get_by_label("Edit")
    finish_edit_button = last_message_container.get_by_label("Stop editing")
    autosize_textarea_locator = last_message_container.locator("ms-autosize-textarea")
    actual_textarea_locator = last_message_container.locator("textarea")

    try:
        logger.info("- 尝试悬停最后一条消息以显示 'Edit' 按钮...")
        try:
            # 对消息容器执行悬停操作
            await last_message_container.hover(
                timeout=CLICK_TIMEOUT_MS / 2
            )  # 使用一半的点击超时作为悬停超时
            await asyncio.sleep(0.3)  # 等待悬停效果生效
            check_client_disconnected("编辑响应 - 悬停后: ")
        except asyncio.CancelledError:
            raise
        except ClientDisconnectedError:
            raise
        except Exception as hover_err:
            logger.warning(
                f"   - (get_response_via_edit_button) 悬停最后一条消息失败 (忽略): {type(hover_err).__name__}"
            )
            # 即使悬停失败，也继续尝试后续操作，Playwright的expect_async可能会处理

        logger.info("- 定位并点击 'Edit' 按钮...")
        try:
            from playwright.async_api import expect as expect_async

            await expect_async(edit_button).to_be_visible(timeout=CLICK_TIMEOUT_MS)
            check_client_disconnected("编辑响应 - 'Edit' 按钮可见后: ")
            await edit_button.click(timeout=CLICK_TIMEOUT_MS)
            logger.info("- 'Edit' 按钮已点击。")
        except asyncio.CancelledError:
            raise
        except Exception as edit_btn_err:
            logger.error(
                f"   - 'Edit' 按钮不可见或点击失败: {edit_btn_err}", exc_info=True
            )
            await save_error_snapshot(f"edit_response_edit_button_failed_{req_id}")
            return None

        check_client_disconnected("编辑响应 - 点击 'Edit' 按钮后: ")
        await asyncio.sleep(0.3)
        check_client_disconnected("编辑响应 - 点击 'Edit' 按钮后延时后: ")

        logger.info("- 从文本区域获取内容...")
        response_content = None
        textarea_failed = False

        try:
            target_locator = autosize_textarea_locator
            if await target_locator.count() == 0:
                target_locator = actual_textarea_locator

            if await target_locator.count() == 0:
                raise RuntimeError("未找到可编辑的文本区域")

            await expect_async(target_locator).to_be_visible(timeout=CLICK_TIMEOUT_MS)
            check_client_disconnected("编辑响应 - 文本区域可见后: ")

            if await autosize_textarea_locator.count() > 0 and response_content is None:
                try:
                    data_value_content = await autosize_textarea_locator.get_attribute(
                        "data-value"
                    )
                    check_client_disconnected(
                        "编辑响应 - get_attribute data-value 后: "
                    )
                    if data_value_content is not None:
                        response_content = str(data_value_content)
                        logger.info("- 从 data-value 获取内容成功。")
                except asyncio.CancelledError:
                    raise
                except Exception as data_val_err:
                    logger.warning(f"- 获取 data-value 失败: {data_val_err}")
                    check_client_disconnected(
                        "编辑响应 - get_attribute data-value 错误后: "
                    )

            if response_content is None and await actual_textarea_locator.count() > 0:
                logger.info(
                    "   - data-value 获取失败或不存在，尝试从 textarea 获取 input_value..."
                )
                try:
                    await expect_async(actual_textarea_locator).to_be_visible(
                        timeout=CLICK_TIMEOUT_MS / 2
                    )
                    input_val_content = await actual_textarea_locator.input_value(
                        timeout=CLICK_TIMEOUT_MS / 2
                    )
                    check_client_disconnected("编辑响应 - input_value 后: ")
                    response_content = str(input_val_content)
                    logger.info("- 从 input_value 获取内容成功。")
                except asyncio.CancelledError:
                    raise
                except Exception as input_val_err:
                    logger.warning(f"- 获取 input_value 也失败: {input_val_err}")
                    check_client_disconnected("编辑响应 - input_value 错误后: ")

            if response_content is not None:
                response_content = response_content.strip()
                content_preview = response_content[:100].replace("\\n", "\\\\n")
                logger.info(
                    f"   - 最终获取内容 (长度={len(response_content)}): '{content_preview}...'"
                )
            else:
                logger.warning(
                    "   - 所有方法 (data-value, input_value) 内容获取均失败或返回 None。"
                )
                textarea_failed = True

        except asyncio.CancelledError:
            raise
        except Exception as textarea_err:
            logger.error(
                f"   - 定位或处理文本区域时失败: {textarea_err}", exc_info=True
            )
            textarea_failed = True
            response_content = None
            check_client_disconnected("编辑响应 - 获取文本区域错误后: ")

        if not textarea_failed:
            logger.info("- 定位并点击 'Stop editing' 按钮...")
            try:
                await expect_async(finish_edit_button).to_be_visible(
                    timeout=CLICK_TIMEOUT_MS
                )
                check_client_disconnected("编辑响应 - 'Stop editing' 按钮可见后: ")
                await finish_edit_button.click(timeout=CLICK_TIMEOUT_MS)
                logger.info("- 'Stop editing' 按钮已点击。")
            except asyncio.CancelledError:
                raise
            except Exception as finish_btn_err:
                logger.warning(
                    f"   - 'Stop editing' 按钮不可见或点击失败: {finish_btn_err}"
                )
                await save_error_snapshot(
                    f"edit_response_finish_button_failed_{req_id}"
                )
            check_client_disconnected("编辑响应 - 点击 'Stop editing' 后: ")
            await asyncio.sleep(0.2)
            check_client_disconnected("编辑响应 - 点击 'Stop editing' 后延时后: ")
        else:
            logger.info("- 跳过点击 'Stop editing' 按钮，因为文本区域读取失败。")

        return response_content

    except ClientDisconnectedError:
        logger.info("(Helper Edit) 客户端断开连接。")
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("通过编辑按钮获取响应过程中发生意外错误")
        await save_error_snapshot(f"edit_response_unexpected_error_{req_id}")
        return None


async def get_response_via_copy_button(
    page: AsyncPage, req_id: str, check_client_disconnected: Callable
) -> Optional[str]:
    """通过复制按钮获取响应"""
    logger.info("(Helper) 尝试通过复制按钮获取响应...")
    last_message_container = page.locator(CHAT_TURN_SELECTOR).last
    more_options_button = last_message_container.get_by_label("Open options")
    copy_markdown_button = page.get_by_role("menuitem", name="Copy markdown")

    try:
        logger.info("- 尝试悬停最后一条消息以显示选项...")
        await last_message_container.hover(timeout=CLICK_TIMEOUT_MS)
        check_client_disconnected("复制响应 - 悬停后: ")
        await asyncio.sleep(0.5)
        check_client_disconnected("复制响应 - 悬停后延时后: ")
        logger.info("- 已悬停。")

        logger.info("- 定位并点击 '更多选项' 按钮...")
        try:
            from playwright.async_api import expect as expect_async

            await expect_async(more_options_button).to_be_visible(
                timeout=CLICK_TIMEOUT_MS
            )
            check_client_disconnected("复制响应 - 更多选项按钮可见后: ")
            await more_options_button.click(timeout=CLICK_TIMEOUT_MS)
            logger.info("- '更多选项' 已点击 (通过 get_by_label)。")
        except asyncio.CancelledError:
            raise
        except Exception as more_opts_err:
            logger.error(
                f"   - '更多选项' 按钮 (通过 get_by_label) 不可见或点击失败: {more_opts_err}"
            )
            await save_error_snapshot(f"copy_response_more_options_failed_{req_id}")
            return None

        check_client_disconnected("复制响应 - 点击更多选项后: ")
        await asyncio.sleep(0.5)
        check_client_disconnected("复制响应 - 点击更多选项后延时后: ")

        logger.info("- 定位并点击 '复制 Markdown' 按钮...")
        copy_success = False
        try:
            await expect_async(copy_markdown_button).to_be_visible(
                timeout=CLICK_TIMEOUT_MS
            )
            check_client_disconnected("复制响应 - 复制按钮可见后: ")
            await copy_markdown_button.click(timeout=CLICK_TIMEOUT_MS, force=True)
            copy_success = True
            logger.info("- 已点击 '复制 Markdown' (通过 get_by_role)。")
        except asyncio.CancelledError:
            raise
        except Exception as copy_err:
            logger.error(
                f"   - '复制 Markdown' 按钮 (通过 get_by_role) 点击失败: {copy_err}"
            )
            await save_error_snapshot(f"copy_response_copy_button_failed_{req_id}")
            return None

        if not copy_success:
            logger.error("- 未能点击 '复制 Markdown' 按钮。")
            return None

        check_client_disconnected("复制响应 - 点击复制按钮后: ")
        await asyncio.sleep(0.5)
        check_client_disconnected("复制响应 - 点击复制按钮后延时后: ")

        logger.info("- 正在读取剪贴板内容...")
        try:
            clipboard_content = await page.evaluate("navigator.clipboard.readText()")
            check_client_disconnected("复制响应 - 读取剪贴板后: ")
            if clipboard_content:
                content_preview = clipboard_content[:100].replace("\n", "\\\\n")
                logger.info(
                    f"   - 成功获取剪贴板内容 (长度={len(clipboard_content)}): '{content_preview}...'"
                )
                return clipboard_content
            else:
                logger.error("- 剪贴板内容为空。")
                return None
        except asyncio.CancelledError:
            raise
        except Exception as clipboard_err:
            if "clipboard-read" in str(clipboard_err):
                logger.error(
                    f"   - 读取剪贴板失败: 可能是权限问题。错误: {clipboard_err}"
                )
            else:
                logger.error(f"- 读取剪贴板失败: {clipboard_err}", exc_info=True)
            await save_error_snapshot(f"copy_response_clipboard_read_failed_{req_id}")
            return None

    except ClientDisconnectedError:
        logger.info("(Helper Copy) 客户端断开连接。")
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("复制响应过程中发生意外错误")
        await save_error_snapshot(f"copy_response_unexpected_error_{req_id}")
        return None


async def _wait_for_response_completion(
    page: AsyncPage,
    prompt_textarea_locator: Locator,
    submit_button_locator: Locator,
    edit_button_locator: Locator,
    req_id: str,
    check_client_disconnected_func: Callable,
    timeout_ms=RESPONSE_COMPLETION_TIMEOUT,
    initial_wait_ms=INITIAL_WAIT_MS_BEFORE_POLLING,
) -> bool:
    """等待响应完成"""
    from playwright.async_api import TimeoutError

    logger.info(f"(WaitV3) 开始等待响应完成... (超时: {timeout_ms}ms)")
    await asyncio.sleep(initial_wait_ms / 1000)  # Initial brief wait

    start_time = time.time()
    wait_timeout_ms_short = 3000  # 3 seconds for individual element checks

    consecutive_empty_input_submit_disabled_count = 0

    while True:
        try:
            check_client_disconnected_func("等待响应完成 - 循环开始")
        except ClientDisconnectedError:
            logger.info("(WaitV3) 客户端断开连接，中止等待。")
            return False

        current_time_elapsed_ms = (time.time() - start_time) * 1000
        if current_time_elapsed_ms > timeout_ms:
            logger.error(f"(WaitV3) 等待响应完成超时 ({timeout_ms}ms)。")
            await save_error_snapshot(f"wait_completion_v3_overall_timeout_{req_id}")
            return False

        try:
            check_client_disconnected_func("等待响应完成 - 超时检查后")
        except ClientDisconnectedError:
            return False

        # --- 主要条件: 输入框空 & 提交按钮禁用 ---
        is_input_empty = await prompt_textarea_locator.input_value() == ""
        is_submit_disabled = False
        try:
            is_submit_disabled = await submit_button_locator.is_disabled(
                timeout=wait_timeout_ms_short
            )
        except TimeoutError:
            logger.warning(
                "(WaitV3) 检查提交按钮是否禁用超时。为本次检查假定其未禁用。"
            )

        try:
            check_client_disconnected_func("等待响应完成 - 按钮状态检查后")
        except ClientDisconnectedError:
            return False

        if is_input_empty and is_submit_disabled:
            consecutive_empty_input_submit_disabled_count += 1
            if DEBUG_LOGS_ENABLED:
                logger.debug(
                    f"(WaitV3) 主要条件满足: 输入框空，提交按钮禁用 (计数: {consecutive_empty_input_submit_disabled_count})。"
                )

            # --- 最终确认: 编辑按钮可见 ---
            try:
                if await edit_button_locator.is_visible(timeout=wait_timeout_ms_short):
                    logger.info(
                        "(WaitV3) 响应完成: 输入框空，提交按钮禁用，编辑按钮可见。"
                    )
                    return True  # 明确完成
            except TimeoutError:
                if DEBUG_LOGS_ENABLED:
                    logger.debug("(WaitV3) 主要条件满足后，检查编辑按钮可见性超时。")

            try:
                check_client_disconnected_func("等待响应完成 - 编辑按钮检查后")
            except ClientDisconnectedError:
                return False

            # 启发式完成: 如果主要条件持续满足，但编辑按钮仍未出现
            if (
                consecutive_empty_input_submit_disabled_count >= 3
            ):  # 例如，大约 1.5秒 (3 * 0.5秒轮询)
                logger.warning(
                    f"(WaitV3) 响应可能已完成 (启发式): 输入框空，提交按钮禁用，但在 {consecutive_empty_input_submit_disabled_count} 次检查后编辑按钮仍未出现。假定完成。后续若内容获取失败，可能与此有关。"
                )
                return True  # 启发式完成
        else:  # 主要条件 (输入框空 & 提交按钮禁用) 未满足
            consecutive_empty_input_submit_disabled_count = 0  # 重置计数器
            if DEBUG_LOGS_ENABLED:
                reasons = []
                if not is_input_empty:
                    reasons.append("输入框非空")
                if not is_submit_disabled:
                    reasons.append("提交按钮非禁用")
                logger.debug(
                    f"(WaitV3) 主要条件未满足 ({', '.join(reasons)}). 继续轮询..."
                )

        await asyncio.sleep(0.5)  # 轮询间隔


async def _get_final_response_content(
    page: AsyncPage, req_id: str, check_client_disconnected: Callable
) -> Optional[str]:
    """获取最终响应内容"""
    logger.info("(Helper GetContent) 开始获取最终响应内容...")
    response_content = await get_response_via_edit_button(
        page, req_id, check_client_disconnected
    )
    if response_content is not None:
        logger.info("(Helper GetContent) 成功通过编辑按钮获取内容。")
        return response_content

    logger.warning(
        "(Helper GetContent) 编辑按钮方法失败或返回空，回退到复制按钮方法..."
    )
    response_content = await get_response_via_copy_button(
        page, req_id, check_client_disconnected
    )
    if response_content is not None:
        logger.info("(Helper GetContent) 成功通过复制按钮获取内容。")
        return response_content

    logger.error("(Helper GetContent) 所有获取响应内容的方法均失败。")
    await save_error_snapshot(f"get_content_all_methods_failed_{req_id}")
    return None
