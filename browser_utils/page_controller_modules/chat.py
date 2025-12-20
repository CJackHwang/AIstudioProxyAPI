import asyncio
from typing import Callable

from playwright.async_api import TimeoutError
from playwright.async_api import expect as expect_async

from browser_utils.initialization import enable_temporary_chat_mode
from browser_utils.operations import save_error_snapshot
from config import (
    CLEAR_CHAT_BUTTON_SELECTOR,
    CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR,
    CLEAR_CHAT_VERIFY_TIMEOUT_MS,
    CLICK_TIMEOUT_MS,
    OVERLAY_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
    WAIT_FOR_ELEMENT_TIMEOUT_MS,
)
from models import ClientDisconnectedError

from .base import BaseController


class ChatController(BaseController):
    """Handles chat history management."""

    async def clear_chat_history(self, check_client_disconnected: Callable):
        """清空聊天记录。"""
        self.logger.debug("[Chat] 开始清空聊天记录")
        await self._check_disconnect(check_client_disconnected, "Start Clear Chat")

        try:
            # 一般是使用流式代理时遇到,流式输出已结束,但页面上AI仍回复个不停,此时会锁住清空按钮,但页面仍是/new_chat,而跳过后续清空操作
            # 导致后续请求无法发出而卡住,故先检查并点击发送按钮(此时是停止功能)
            submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            try:
                self.logger.debug("[Chat] 检查发送按钮状态...")
                # 使用较短的超时时间（1秒），避免长时间阻塞，因为这不是清空流程的常见步骤
                await expect_async(submit_button_locator).to_be_enabled(timeout=1000)
                self.logger.debug("[Chat] 发送按钮可用，点击并等待 1 秒...")
                await submit_button_locator.click(timeout=CLICK_TIMEOUT_MS)
                try:
                    await expect_async(submit_button_locator).to_be_disabled(
                        timeout=1200
                    )
                except Exception:
                    pass
                self.logger.debug("[Chat] 发送按钮点击完成")
            except asyncio.CancelledError:
                raise
            except Exception:
                # 如果发送按钮不可用、超时或发生Playwright相关错误，记录日志并继续
                self.logger.debug(
                    "[Cleanup] 发送按钮不可用/Playwright错误 (符合预期)，继续检查清空按钮"
                )

            clear_chat_button_locator = self.page.locator(CLEAR_CHAT_BUTTON_SELECTOR)
            confirm_button_locator = self.page.locator(
                CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR
            )
            overlay_locator = self.page.locator(OVERLAY_SELECTOR)

            can_attempt_clear = False
            try:
                await expect_async(clear_chat_button_locator).to_be_enabled(
                    timeout=3000
                )
                can_attempt_clear = True
                self.logger.debug("[Chat] 清空按钮可用")
            except Exception as e_enable:
                is_new_chat_url = "/prompts/new_chat" in self.page.url.rstrip("/")
                if is_new_chat_url:
                    self.logger.info(
                        '"清空聊天"按钮不可用 (预期，因为在 new_chat 页面)。跳过清空操作。'
                    )
                else:
                    self.logger.warning(
                        f'等待"清空聊天"按钮可用失败: {e_enable}。清空操作可能无法执行。'
                    )

            await self._check_disconnect(
                check_client_disconnected, '清空聊天 - "清空聊天"按钮可用性检查后'
            )

            if can_attempt_clear:
                await self._execute_chat_clear(
                    clear_chat_button_locator,
                    confirm_button_locator,
                    overlay_locator,
                    check_client_disconnected,
                )
                await self._verify_chat_cleared(check_client_disconnected)
                self.logger.debug("[Chat] 重新启用临时聊天模式")
                await enable_temporary_chat_mode(self.page)

        except Exception as e_clear:
            if isinstance(e_clear, asyncio.CancelledError):
                raise
            self.logger.error(f"清空聊天过程中发生错误: {e_clear}")
            error_name = getattr(e_clear, "name", "")
            if not (
                isinstance(e_clear, ClientDisconnectedError)
                or (error_name and "Disconnect" in error_name)
            ):
                # Capture locator states for debugging
                clear_btn_loc = self.page.locator(CLEAR_CHAT_BUTTON_SELECTOR)
                confirm_btn_loc = self.page.locator(CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR)
                submit_btn_loc = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                overlay_loc = self.page.locator(OVERLAY_SELECTOR)

                await save_error_snapshot(
                    f"clear_chat_error_{self.req_id}",
                    error_exception=e_clear,
                    error_stage="清空聊天流程异常",
                    additional_context={
                        "page_url": self.page.url,
                        "is_new_chat_page": "/prompts/new_chat" in self.page.url,
                    },
                    locators={
                        "clear_chat_button": clear_btn_loc,
                        "confirm_button": confirm_btn_loc,
                        "submit_button": submit_btn_loc,
                        "overlay": overlay_loc,
                    },
                )
            raise

    async def _execute_chat_clear(
        self,
        clear_chat_button_locator,
        confirm_button_locator,
        overlay_locator,
        check_client_disconnected: Callable,
    ):
        """执行清空聊天操作"""
        overlay_initially_visible = False
        try:
            if await overlay_locator.is_visible(timeout=1000):
                overlay_initially_visible = True
                self.logger.debug("[Chat] 确认对话框已可见，直接点击“继续”")
        except TimeoutError:
            overlay_initially_visible = False
        except Exception:
            overlay_initially_visible = False
        except Exception as e_vis_check:
            self.logger.warning(
                f"检查遮罩层可见性时发生错误: {e_vis_check}。假定不可见。"
            )
            overlay_initially_visible = False

        await self._check_disconnect(
            check_client_disconnected, "清空聊天 - 初始遮罩层检查后"
        )

        if overlay_initially_visible:
            self.logger.debug("[Chat] 点击“继续”按钮")
            await confirm_button_locator.click(timeout=CLICK_TIMEOUT_MS)
        else:
            self.logger.debug("[Chat] 点击“清空聊天”按钮")
            # 若存在透明遮罩层拦截指针事件，先尝试清理
            try:
                await self._dismiss_backdrops()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            try:
                try:
                    await clear_chat_button_locator.scroll_into_view_if_needed()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                await clear_chat_button_locator.click(timeout=CLICK_TIMEOUT_MS)
            except asyncio.CancelledError:
                raise
            except Exception as first_click_err:
                self.logger.warning(
                    f"清空按钮第一次点击失败，尝试清理遮罩并强制点击: {first_click_err}"
                )
                try:
                    await self._dismiss_backdrops()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                try:
                    await clear_chat_button_locator.click(
                        timeout=CLICK_TIMEOUT_MS, force=True
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as force_click_err:
                    self.logger.error(f"清空按钮强制点击仍失败: {force_click_err}")
                    raise
            await self._check_disconnect(
                check_client_disconnected, '清空聊天 - 点击"清空聊天"后'
            )

            try:
                self.logger.debug("[Chat] 等待确认对话框...")
                await expect_async(overlay_locator).to_be_visible(
                    timeout=WAIT_FOR_ELEMENT_TIMEOUT_MS
                )
            except TimeoutError:
                error_msg = f"等待清空聊天确认遮罩层超时 (点击清空按钮后)。请求 ID: {self.req_id}"
                self.logger.error(error_msg)
                await save_error_snapshot(f"clear_chat_overlay_timeout_{self.req_id}")
                raise Exception(error_msg)

            await self._check_disconnect(
                check_client_disconnected, "清空聊天 - 遮罩层出现后"
            )
            self.logger.debug("[Chat] 点击“继续”按钮")
            try:
                await confirm_button_locator.scroll_into_view_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            try:
                await confirm_button_locator.click(timeout=CLICK_TIMEOUT_MS)
            except asyncio.CancelledError:
                raise
            except Exception as confirm_err:
                # 检查按钮/对话框是否已消失（操作已成功）
                err_str = str(confirm_err).lower()
                if "detached" in err_str or "not stable" in err_str:
                    try:
                        is_dialog_visible = await overlay_locator.is_visible(
                            timeout=500
                        )
                        if not is_dialog_visible:
                            self.logger.debug(
                                "[Chat] 点击时对话框已消失，清空操作已成功"
                            )
                            return  # 直接返回，无需后续等待
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                self.logger.warning(
                    f'首次点击"继续"失败，尝试 force 点击: {confirm_err}'
                )
                try:
                    await confirm_button_locator.click(
                        timeout=CLICK_TIMEOUT_MS, force=True
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as confirm_force_err:
                    # 再次检查对话框是否已消失
                    force_err_str = str(confirm_force_err).lower()
                    if "detached" in force_err_str or "not stable" in force_err_str:
                        try:
                            is_dialog_visible = await overlay_locator.is_visible(
                                timeout=500
                            )
                            if not is_dialog_visible:
                                self.logger.debug(
                                    "[Chat] force 点击时对话框已消失，清空操作已成功"
                                )
                                return
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass
                    self.logger.error(
                        f'"继续"按钮 force 点击仍失败: {confirm_force_err}'
                    )
                    raise

        await self._check_disconnect(
            check_client_disconnected, '清空聊天 - 点击"继续"后'
        )

        # 等待对话框消失
        max_retries_disappear = 3
        for attempt_disappear in range(max_retries_disappear):
            try:
                self.logger.debug(
                    f"[Chat] 等待对话框消失 ({attempt_disappear + 1}/{max_retries_disappear})"
                )
                await expect_async(confirm_button_locator).to_be_hidden(
                    timeout=CLEAR_CHAT_VERIFY_TIMEOUT_MS
                )
                await expect_async(overlay_locator).to_be_hidden(timeout=1000)
                self.logger.debug("[Chat] 对话框已消失")
                break
            except TimeoutError:
                self.logger.warning(
                    f"等待清空聊天确认对话框消失超时 (尝试 {attempt_disappear + 1}/{max_retries_disappear})。"
                )
                if attempt_disappear < max_retries_disappear - 1:
                    await self._check_disconnect(
                        check_client_disconnected,
                        f"清空聊天 - 重试消失检查 {attempt_disappear + 1} 前",
                    )
                    continue
                else:
                    error_msg = f"达到最大重试次数。清空聊天确认对话框未消失。请求 ID: {self.req_id}"
                    self.logger.error(error_msg)
                    await save_error_snapshot(
                        f"clear_chat_dialog_disappear_timeout_{self.req_id}"
                    )
                    raise Exception(error_msg)
            except ClientDisconnectedError:
                self.logger.info("客户端在等待清空确认对话框消失时断开连接。")
                raise
            except Exception as other_err:
                if isinstance(other_err, asyncio.CancelledError):
                    raise
                self.logger.warning(
                    f"等待清空确认对话框消失时发生其他错误: {other_err}"
                )
                if attempt_disappear < max_retries_disappear - 1:
                    continue
                else:
                    raise

    async def _dismiss_backdrops(self):
        """尝试关闭可能残留的 cdk 透明遮罩层以避免点击被拦截。"""
        try:
            backdrop = self.page.locator(
                "div.cdk-overlay-backdrop.cdk-overlay-backdrop-showing, div.cdk-overlay-backdrop.cdk-overlay-transparent-backdrop.cdk-overlay-backdrop-showing"
            )
            for i in range(3):
                cnt = 0
                try:
                    cnt = await backdrop.count()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    cnt = 0
                if cnt and cnt > 0:
                    self.logger.debug(
                        f"检测到透明遮罩层 ({cnt})，发送 ESC 关闭 (尝试 {i + 1}/3)。"
                    )
                    try:
                        await self.page.keyboard.press("Escape")
                        try:
                            await expect_async(backdrop).to_be_hidden(timeout=500)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                else:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _verify_chat_cleared(self, check_client_disconnected: Callable):
        """验证聊天已清空"""
        last_response_container = self.page.locator(RESPONSE_CONTAINER_SELECTOR).last
        await self._check_disconnect(
            check_client_disconnected, "After Clear Post-Check"
        )
        try:
            await expect_async(last_response_container).to_be_hidden(
                timeout=CLEAR_CHAT_VERIFY_TIMEOUT_MS - 500
            )
            self.logger.debug("[Chat] 验证通过，响应容器已隐藏")
        except asyncio.CancelledError:
            raise
        except Exception as verify_err:
            self.logger.warning(
                f"警告: 清空聊天验证失败 (最后响应容器未隐藏): {verify_err}"
            )
