import asyncio
from typing import Callable

from playwright.async_api import expect as expect_async

from browser_utils.operations import (
    _get_final_response_content,
    _wait_for_response_completion,
    save_error_snapshot,
)
from config import (
    EDIT_MESSAGE_BUTTON_SELECTOR,
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    RESPONSE_TEXT_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
)
from logging_utils import set_request_id
from models import ClientDisconnectedError

from .base import BaseController


class ResponseController(BaseController):
    """Handles retrieval of AI responses."""

    async def get_response(
        self, check_client_disconnected: Callable[[str], bool]
    ) -> str:
        """获取响应内容。"""
        set_request_id(self.req_id)
        self.logger.debug("[Response] 等待并获取响应...")

        try:
            # 等待响应容器出现
            response_container_locator = self.page.locator(
                RESPONSE_CONTAINER_SELECTOR
            ).last
            response_element_locator = response_container_locator.locator(
                RESPONSE_TEXT_SELECTOR
            )

            self.logger.debug("[Response] 等待响应元素附加到 DOM...")
            await expect_async(response_element_locator).to_be_attached(timeout=90000)
            await self._check_disconnect(
                check_client_disconnected, "获取响应 - 响应元素已附加"
            )

            # 等待响应完成
            submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            edit_button_locator = self.page.locator(EDIT_MESSAGE_BUTTON_SELECTOR)
            input_field_locator = self.page.locator(PROMPT_TEXTAREA_SELECTOR)

            self.logger.debug("[Response] 等待响应完成...")
            completion_detected = await _wait_for_response_completion(
                self.page,
                input_field_locator,
                submit_button_locator,
                edit_button_locator,
                self.req_id,
                check_client_disconnected,
            )

            if not completion_detected:
                self.logger.warning("响应完成检测失败，尝试获取当前内容")
            else:
                self.logger.debug("[Response] 响应完成检测成功")

            # 获取最终响应内容
            final_content = await _get_final_response_content(
                self.page, self.req_id, check_client_disconnected
            )

            if not final_content or not final_content.strip():
                self.logger.warning("获取到的响应内容为空")
                await save_error_snapshot(f"empty_response_{self.req_id}")
                # 不抛出异常，返回空内容让上层处理
                return ""

            self.logger.debug(f"[Response] 成功获取 ({len(final_content)} chars)")
            return final_content

        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                self.logger.info("获取响应任务被取消")
                raise
            self.logger.error(f"获取响应时出错: {e}")
            if not isinstance(e, ClientDisconnectedError):
                await save_error_snapshot(f"get_response_error_{self.req_id}")
            raise

    async def ensure_generation_stopped(
        self, check_client_disconnected: Callable
    ) -> None:
        """
        确保生成已停止。
        如果提交按钮仍处于启用状态，则点击它以停止生成。
        等待直到提交按钮变为禁用状态。
        """
        submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)

        # 检查客户端连接状态
        check_client_disconnected("确保生成停止 - 前置检查")
        await asyncio.sleep(0.5)  # 给UI一点时间更新

        # 检查按钮是否仍然启用，如果启用则直接点击停止
        try:
            is_button_enabled = await submit_button_locator.is_enabled(timeout=2000)

            if is_button_enabled:
                # 流式响应完成后按钮仍启用，直接点击停止
                self.logger.debug("[Cleanup] 发送按钮状态: 启用 -> 点击停止")
                await submit_button_locator.click(timeout=5000, force=True)
            else:
                self.logger.debug("[Cleanup] 发送按钮状态: 已禁用 (无需操作)")
        except Exception as button_check_err:
            if isinstance(button_check_err, asyncio.CancelledError):
                raise
            self.logger.warning(f"检查按钮状态失败: {button_check_err}")

        # 等待按钮最终禁用
        try:
            await expect_async(submit_button_locator).to_be_disabled(timeout=30000)
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.warning(f"确保生成停止时超时或错误: {e}")
            # 即使超时也不抛出异常，因为这只是清理步骤
