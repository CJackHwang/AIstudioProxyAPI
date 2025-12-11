import asyncio
import base64
import mimetypes
from typing import Callable, List

from playwright.async_api import TimeoutError
from playwright.async_api import expect as expect_async

from browser_utils.operations import save_error_snapshot
from config import (
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
    UPLOAD_BUTTON_SELECTOR,
)
from logging_utils import set_request_id
from models import ClientDisconnectedError

from .base import BaseController


class InputController(BaseController):
    """Handles prompt input and submission."""

    async def submit_prompt(
        self, prompt: str, image_list: List, check_client_disconnected: Callable
    ):
        """提交提示到页面。"""
        set_request_id(self.req_id)
        self.logger.info(f"填充并提交提示 ({len(prompt)} chars)...")
        prompt_textarea_locator = self.page.locator(PROMPT_TEXTAREA_SELECTOR)
        autosize_wrapper_locator = self.page.locator("ms-prompt-box .text-wrapper")
        legacy_autosize_wrapper = self.page.locator(
            "ms-prompt-box ms-autosize-textarea"
        )
        submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)

        try:
            await expect_async(prompt_textarea_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "After Input Visible"
            )

            # 使用 JavaScript 填充文本
            await prompt_textarea_locator.evaluate(
                """
                (element, text) => {
                    element.value = text;
                    element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                }
                """,
                prompt,
            )
            autosize_target = autosize_wrapper_locator
            if await autosize_target.count() == 0:
                autosize_target = legacy_autosize_wrapper
            if await autosize_target.count() > 0:
                try:
                    await autosize_target.first.evaluate(
                        '(element, text) => { element.setAttribute("data-value", text); }',
                        prompt,
                    )
                except Exception as autosize_err:
                    self.logger.debug(
                        f" autosize wrapper update skipped: {autosize_err}"
                    )
            await self._check_disconnect(check_client_disconnected, "After Input Fill")

            # 上传（仅使用菜单 + 隐藏 input 设置文件；处理可能的授权弹窗）
            try:
                self.logger.info(f" 待上传附件数量: {len(image_list)}")
            except Exception:
                pass
            if len(image_list) > 0:
                ok = await self._open_upload_menu_and_choose_file(image_list)
                if not ok:
                    self.logger.error(" 在上传文件时发生错误: 通过菜单方式未能设置文件")

            # 等待发送按钮启用 (使用可配置的快速失败超时)
            from config.timeouts import SUBMIT_BUTTON_ENABLE_TIMEOUT_MS

            wait_timeout_ms_submit_enabled = SUBMIT_BUTTON_ENABLE_TIMEOUT_MS
            start_time = asyncio.get_event_loop().time()
            self.logger.info(
                f" 等待发送按钮启用 (最大 {wait_timeout_ms_submit_enabled}ms)..."
            )

            try:
                while True:
                    await self._check_disconnect(
                        check_client_disconnected, "Waiting for Submit Button Enabled"
                    )

                    try:
                        # 使用短超时轮询检查，以便能响应中断信号
                        if await submit_button_locator.is_enabled(timeout=500):
                            self.logger.info(" 发送按钮已启用。")
                            break
                    except Exception:
                        # 忽略临时错误（如元素尚未出现）
                        pass

                    if (
                        asyncio.get_event_loop().time() - start_time
                    ) * 1000 > wait_timeout_ms_submit_enabled:
                        raise TimeoutError(
                            f"Submit button not enabled within {wait_timeout_ms_submit_enabled}ms"
                        )

                    await asyncio.sleep(0.5)

            except Exception as e_pw_enabled:
                self.logger.error(f" 等待发送按钮启用超时或错误: {e_pw_enabled}")
                await save_error_snapshot(f"submit_button_enable_timeout_{self.req_id}")
                raise

            await self._check_disconnect(
                check_client_disconnected, "After Submit Button Enabled"
            )
            await asyncio.sleep(0.3)

            # 优先点击按钮提交，其次回车提交，最后组合键提交
            button_clicked = False
            try:
                self.logger.info(" 尝试点击提交按钮...")
                # 提交前再处理一次潜在对话框，避免按钮点击被拦截
                await self._handle_post_upload_dialog()
                await submit_button_locator.click(timeout=5000)
                self.logger.info(" 提交按钮点击完成。")
                button_clicked = True
            except Exception as click_err:
                self.logger.error(f" 提交按钮点击失败: {click_err}")
                await save_error_snapshot(f"submit_button_click_fail_{self.req_id}")

            if not button_clicked:
                self.logger.info(" 按钮提交失败，尝试回车键提交...")
                submitted_successfully = await self._try_enter_submit(
                    prompt_textarea_locator, check_client_disconnected
                )
                if not submitted_successfully:
                    self.logger.info(" 回车提交失败，尝试组合键提交...")
                    combo_ok = await self._try_combo_submit(
                        prompt_textarea_locator, check_client_disconnected
                    )
                    if not combo_ok:
                        self.logger.error(" 组合键提交也失败。")
                        raise Exception(
                            "Submit failed: Button, Enter, and Combo key all failed"
                        )

            await self._check_disconnect(check_client_disconnected, "After Submit")

        except Exception as e_input_submit:
            if isinstance(e_input_submit, asyncio.CancelledError):
                raise
            self.logger.error(f" 输入和提交过程中发生错误: {e_input_submit}")
            if not isinstance(e_input_submit, ClientDisconnectedError):
                await save_error_snapshot(f"input_submit_error_{self.req_id}")
            raise

    async def _open_upload_menu_and_choose_file(self, files_list: List[str]) -> bool:
        """通过'Insert assets'菜单选择'上传/Upload'项并打开文件选择器设置文件。"""
        try:
            # 若上一次菜单/对话的透明遮罩仍在，先尝试关闭
            try:
                tb = self.page.locator(
                    "div.cdk-overlay-backdrop.cdk-overlay-transparent-backdrop.cdk-overlay-backdrop-showing"
                )
                if await tb.count() > 0 and await tb.first.is_visible(timeout=300):
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
            except Exception:
                pass

            trigger = self.page.locator(UPLOAD_BUTTON_SELECTOR).first
            await expect_async(trigger).to_be_visible(timeout=3000)
            await trigger.click()
            menu_container = self.page.locator("div.cdk-overlay-container")
            # 等待菜单显示
            try:
                await expect_async(
                    menu_container.locator("div[role='menu']").first
                ).to_be_visible(timeout=3000)
            except Exception:
                # 再尝试一次触发
                try:
                    await trigger.click()
                    await expect_async(
                        menu_container.locator("div[role='menu']").first
                    ).to_be_visible(timeout=3000)
                except Exception:
                    self.logger.warning(" 未能显示上传菜单面板。")
                    return False

            # 仅使用 aria-label='Upload File' 的菜单项
            try:
                upload_btn = menu_container.locator(
                    "div[role='menu'] button[role='menuitem'][aria-label='Upload File']"
                )
                if await upload_btn.count() == 0:
                    # 退化到按文本匹配 Upload File
                    upload_btn = menu_container.locator(
                        "div[role='menu'] button[role='menuitem']:has-text('Upload File')"
                    )
                if await upload_btn.count() == 0:
                    self.logger.warning(" 未找到 'Upload File' 菜单项。")
                    return False
                btn = upload_btn.first
                await expect_async(btn).to_be_visible(timeout=2000)
                # 优先使用内部隐藏 input[type=file]
                input_loc = btn.locator('input[type="file"]')
                if await input_loc.count() > 0:
                    await input_loc.set_input_files(files_list)
                    self.logger.info(
                        f" 通过菜单项(Upload File) 隐藏 input 设置文件成功: {len(files_list)} 个"
                    )
                else:
                    # 回退为原生文件选择器
                    async with self.page.expect_file_chooser() as fc_info:
                        await btn.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(files_list)
                    self.logger.info(
                        f" 通过文件选择器设置文件成功: {len(files_list)} 个"
                    )
            except Exception as e_set:
                self.logger.error(f" 设置文件失败: {e_set}")
                return False
            # 关闭可能残留的菜单遮罩
            try:
                backdrop = self.page.locator(
                    "div.cdk-overlay-backdrop.cdk-overlay-backdrop-showing, div.cdk-overlay-backdrop.cdk-overlay-transparent-backdrop.cdk-overlay-backdrop-showing"
                )
                if await backdrop.count() > 0:
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
            except Exception:
                pass
            # 处理可能的授权弹窗
            await self._handle_post_upload_dialog()
            return True
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f" 通过上传菜单设置文件失败: {e}")
            return False

    async def _handle_post_upload_dialog(self):
        """处理上传后可能出现的授权/版权确认对话框，优先点击同意类按钮，不主动关闭重要对话框。"""
        try:
            overlay_container = self.page.locator("div.cdk-overlay-container")
            if await overlay_container.count() == 0:
                return

            # 候选同意按钮的文本/属性
            agree_texts = [
                "Agree",
                "I agree",
                "Allow",
                "Continue",
                "OK",
                "确定",
                "同意",
                "继续",
                "允许",
            ]
            # 统一在 overlay 容器内查找可见按钮
            for text in agree_texts:
                try:
                    btn = overlay_container.locator(f"button:has-text('{text}')")
                    if await btn.count() > 0 and await btn.first.is_visible(
                        timeout=300
                    ):
                        await btn.first.click()
                        self.logger.info(f" 上传后对话框: 点击按钮 '{text}'。")
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue
            # 若存在带 aria-label 的版权按钮
            try:
                acknow_btn_locator = self.page.locator(
                    'button[aria-label*="copyright" i], button[aria-label*="acknowledge" i]'
                )
                if (
                    await acknow_btn_locator.count() > 0
                    and await acknow_btn_locator.first.is_visible(timeout=300)
                ):
                    await acknow_btn_locator.first.click()
                    self.logger.info(
                        " 上传后对话框: 点击版权确认按钮 (aria-label 匹配)。"
                    )
                    await asyncio.sleep(0.3)
            except Exception:
                pass

            # 等待遮罩层消失（尽量不强制 ESC，避免意外取消）
            try:
                overlay_backdrop = self.page.locator(
                    "div.cdk-overlay-backdrop.cdk-overlay-backdrop-showing"
                )
                if await overlay_backdrop.count() > 0:
                    try:
                        await expect_async(overlay_backdrop).to_be_hidden(timeout=3000)
                        self.logger.info(" 上传后对话框遮罩层已隐藏。")
                    except Exception:
                        self.logger.warning(
                            " 上传后对话框遮罩层仍存在，后续提交可能被拦截。"
                        )
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _ensure_files_attached(
        self, wrapper_locator, expected_min: int = 1, timeout_ms: int = 5000
    ) -> bool:
        """轮询检查输入区域内 file input 的 files 是否 >= 期望数量。"""
        end = asyncio.get_event_loop().time() + (timeout_ms / 1000)
        while asyncio.get_event_loop().time() < end:
            try:
                # NOTE: normalize JS eval string to avoid parser confusion
                counts = await wrapper_locator.evaluate(
                    """
                    (el) => {
                      const result = {inputs:0, chips:0, blobs:0};
                      try { el.querySelectorAll('input[type="file"]').forEach(i => { result.inputs += (i.files ? i.files.length : 0); }); } catch(e){}
                      try { result.chips = el.querySelectorAll('button[aria-label*="Remove" i], button[aria-label*="asset" i]').length; } catch(e){}
                      try { result.blobs = el.querySelectorAll('img[src^="blob:"], video[src^="blob:"]').length; } catch(e){}
                      return result;
                    }
                    """
                )

                total = 0
                if isinstance(counts, dict):
                    total = max(
                        int(counts.get("inputs") or 0),
                        int(counts.get("chips") or 0),
                        int(counts.get("blobs") or 0),
                    )
                if total >= expected_min:
                    self.logger.info(
                        f" 已检测到已附加文件: inputs={counts.get('inputs')}, chips={counts.get('chips')}, blobs={counts.get('blobs')} (>= {expected_min})"
                    )
                    return True
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(0.2)
        self.logger.warning(f" 未能在超时内检测到已附加文件 (期望 >= {expected_min})")
        return False

    async def _simulate_drag_drop_files(
        self, target_locator, files_list: List[str]
    ) -> None:
        """将本地文件以拖放事件的方式注入到目标元素。
        仅负责触发 dragenter/dragover/drop，不在此处做附加验证以节省时间。
        """
        payloads = []
        for path in files_list:
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                b64 = base64.b64encode(raw).decode("ascii")
                mime, _ = mimetypes.guess_type(path)
                payloads.append(
                    {
                        "name": path.split("/")[-1],
                        "mime": mime or "application/octet-stream",
                        "b64": b64,
                    }
                )
            except Exception as e:
                self.logger.warning(f" 读取文件失败，跳过拖放: {path} - {e}")

        if not payloads:
            raise Exception("无可用文件用于拖放")

        candidates = [
            target_locator,
            self.page.locator(PROMPT_TEXTAREA_SELECTOR),
            self.page.locator("ms-prompt-box .text-wrapper"),
            self.page.locator("ms-prompt-box"),
        ]

        last_err = None
        for idx, cand in enumerate(candidates):
            try:
                await expect_async(cand).to_be_visible(timeout=3000)
                await cand.evaluate(
                    """
                    (el, files) => {
                      const dt = new DataTransfer();
                      for (const p of files) {
                        const bstr = atob(p.b64);
                        const len = bstr.length;
                        const u8 = new Uint8Array(len);
                        for (let i = 0; i < len; i++) u8[i] = bstr.charCodeAt(i);
                        const blob = new Blob([u8], { type: p.mime || 'application/octet-stream' });
                        const file = new File([blob], p.name, { type: p.mime || 'application/octet-stream' });
                        dt.items.add(file);
                      }
                      const evEnter = new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evEnter);
                      const evOver = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evOver);
                      const evDrop = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evDrop);
                    }
                    """,
                    payloads,
                )
                await asyncio.sleep(0.5)
                self.logger.info(
                    f" 拖放事件已在候选目标 {idx + 1}/{len(candidates)} 上触发。"
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as e_try:
                last_err = e_try
                continue

        # 兜底：在 document.body 上尝试一次
        try:
            await self.page.evaluate(
                """
                (files) => {
                  const dt = new DataTransfer();
                  for (const p of files) {
                    const bstr = atob(p.b64);
                    const len = bstr.length;
                    const u8 = new Uint8Array(len);
                    for (let i = 0; i < len; i++) u8[i] = bstr.charCodeAt(i);
                    const blob = new Blob([u8], { type: p.mime || 'application/octet-stream' });
                    const file = new File([blob], p.name, { type: p.mime || 'application/octet-stream' });
                    dt.items.add(file);
                  }
                  const el = document.body;
                  const evEnter = new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evEnter);
                  const evOver = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evOver);
                  const evDrop = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evDrop);
                }
                """,
                payloads,
            )
            await asyncio.sleep(0.5)
            self.logger.info(" 拖放事件已在 document.body 上触发（兜底）。")
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        raise last_err or Exception("拖放未能在任何候选目标上触发")

    async def _try_enter_submit(
        self, prompt_textarea_locator, check_client_disconnected: Callable
    ) -> bool:
        """优先使用回车键提交。"""
        import os

        try:
            # 检测操作系统
            host_os_from_launcher = os.environ.get("HOST_OS_FOR_SHORTCUT")

            if host_os_from_launcher == "Darwin":
                pass
            elif host_os_from_launcher in ["Windows", "Linux"]:
                pass
            else:
                # 浏览器环境，无需特殊OS检测
                pass

            await prompt_textarea_locator.focus(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "After Input Focus")
            await asyncio.sleep(0.1)

            # 记录提交前的输入框内容，用于验证
            original_content = ""
            try:
                original_content = (
                    await prompt_textarea_locator.input_value(timeout=2000) or ""
                )
            except Exception:
                # 如果无法获取原始内容，仍然尝试提交
                pass

            # 尝试回车键提交
            self.logger.info(" 尝试回车键提交")
            try:
                await self.page.keyboard.press("Enter")
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await prompt_textarea_locator.press("Enter")
                except Exception:
                    pass

            await self._check_disconnect(check_client_disconnected, "After Enter Press")
            await asyncio.sleep(2.0)

            # 验证提交是否成功
            submission_success = False
            try:
                # 方法1: 检查原始输入框是否清空
                current_content = (
                    await prompt_textarea_locator.input_value(timeout=2000) or ""
                )
                if original_content and not current_content.strip():
                    self.logger.info(" 验证方法1: 输入框已清空，回车键提交成功")
                    submission_success = True

                # 方法2: 检查提交按钮状态
                if not submission_success:
                    submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                    try:
                        is_disabled = await submit_button_locator.is_disabled(
                            timeout=2000
                        )
                        if is_disabled:
                            self.logger.info(
                                " 验证方法2: 提交按钮已禁用，回车键提交成功"
                            )
                            submission_success = True
                    except Exception:
                        pass

                # 方法3: 检查是否有响应容器出现
                if not submission_success:
                    try:
                        response_container = self.page.locator(
                            RESPONSE_CONTAINER_SELECTOR
                        )
                        container_count = await response_container.count()
                        if container_count > 0:
                            # 检查最后一个容器是否是新的
                            last_container = response_container.last
                            is_vis = await last_container.is_visible(timeout=1000)
                            if is_vis:
                                self.logger.info(
                                    " 验证方法3: 检测到响应容器，回车键提交成功"
                                )
                                submission_success = True
                    except Exception:
                        pass
            except Exception as verify_err:
                self.logger.warning(f" 回车键提交验证过程出错: {verify_err}")
                # 出错时假定提交成功，让后续流程继续
                submission_success = True

            if submission_success:
                self.logger.info(" 回车键提交成功")
                return True
            else:
                self.logger.warning(" 回车键提交验证失败")
                return False
        except asyncio.CancelledError:
            raise
        except Exception as shortcut_err:
            self.logger.warning(f" 回车键提交失败: {shortcut_err}")
            return False

    async def _try_combo_submit(
        self, prompt_textarea_locator, check_client_disconnected: Callable
    ) -> bool:
        """尝试使用组合键提交 (Meta/Control + Enter)。"""
        import os

        try:
            host_os_from_launcher = os.environ.get("HOST_OS_FOR_SHORTCUT")
            is_mac_determined = False
            if host_os_from_launcher == "Darwin":
                is_mac_determined = True
            elif host_os_from_launcher in ["Windows", "Linux"]:
                is_mac_determined = False
            else:
                try:
                    user_agent_data_platform = await self.page.evaluate(
                        "() => navigator.userAgentData?.platform || ''"
                    )
                except Exception:
                    user_agent_string = await self.page.evaluate(
                        "() => navigator.userAgent || ''"
                    )
                    user_agent_string_lower = user_agent_string.lower()
                    if (
                        "macintosh" in user_agent_string_lower
                        or "mac os x" in user_agent_string_lower
                    ):
                        user_agent_data_platform = "macOS"
                    else:
                        user_agent_data_platform = "Other"
                is_mac_determined = "mac" in user_agent_data_platform.lower()

            shortcut_modifier = "Meta" if is_mac_determined else "Control"
            shortcut_key = "Enter"

            await prompt_textarea_locator.focus(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "After Input Focus")
            await asyncio.sleep(0.1)

            # 记录提交前的输入框内容，用于验证
            original_content = ""
            try:
                original_content = (
                    await prompt_textarea_locator.input_value(timeout=2000) or ""
                )
            except Exception:
                pass

            self.logger.info(f" 尝试组合键提交: {shortcut_modifier}+{shortcut_key}")
            try:
                await self.page.keyboard.press(f"{shortcut_modifier}+{shortcut_key}")
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await self.page.keyboard.down(shortcut_modifier)
                    await asyncio.sleep(0.05)
                    await self.page.keyboard.press(shortcut_key)
                    await asyncio.sleep(0.05)
                    await self.page.keyboard.up(shortcut_modifier)
                except Exception:
                    pass

            await self._check_disconnect(check_client_disconnected, "After Combo Press")
            await asyncio.sleep(2.0)

            submission_success = False
            try:
                current_content = (
                    await prompt_textarea_locator.input_value(timeout=2000) or ""
                )
                if original_content and not current_content.strip():
                    self.logger.info(" 验证方法1: 输入框已清空，组合键提交成功")
                    submission_success = True
                if not submission_success:
                    submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                    try:
                        is_disabled = await submit_button_locator.is_disabled(
                            timeout=2000
                        )
                        if is_disabled:
                            self.logger.info(
                                " 验证方法2: 提交按钮已禁用，组合键提交成功"
                            )
                            submission_success = True
                    except Exception:
                        pass
                if not submission_success:
                    try:
                        response_container = self.page.locator(
                            RESPONSE_CONTAINER_SELECTOR
                        )
                        container_count = await response_container.count()
                        if container_count > 0:
                            last_container = response_container.last
                            is_vis = await last_container.is_visible(timeout=1000)
                            if is_vis:
                                self.logger.info(
                                    " 验证方法3: 检测到响应容器，组合键提交成功"
                                )
                                submission_success = True
                    except Exception:
                        pass
            except Exception as verify_err:
                if isinstance(verify_err, asyncio.CancelledError):
                    raise
                self.logger.warning(f" 组合键提交验证过程出错: {verify_err}")
                submission_success = True

            if submission_success:
                self.logger.info(" 组合键提交成功")
                return True
            else:
                self.logger.warning(" 组合键提交验证失败")
                return False
        except Exception as combo_err:
            if isinstance(combo_err, asyncio.CancelledError):
                raise
            self.logger.warning(f" 组合键提交失败: {combo_err}")
            return False
