import asyncio
import re
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import expect as expect_async

from config import (
    CLICK_TIMEOUT_MS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_STOP_SEQUENCES,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    ENABLE_GOOGLE_SEARCH,
    ENABLE_URL_CONTEXT,
    GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR,
    MAX_OUTPUT_TOKENS_SELECTOR,
    STOP_SEQUENCE_INPUT_SELECTOR,
    TEMPERATURE_INPUT_SELECTOR,
    TOP_P_INPUT_SELECTOR,
    USE_URL_CONTEXT_SELECTOR,
)
from models import ClientDisconnectedError

from .base import BaseController


class ParameterController(BaseController):
    """Handles parameter adjustments (temperature, tokens, etc.)."""

    async def adjust_parameters(
        self,
        request_params: Dict[str, Any],
        page_params_cache: Dict[str, Any],
        params_cache_lock: asyncio.Lock,
        model_id_to_use: Optional[str],
        parsed_model_list: List[Dict[str, Any]],
        check_client_disconnected: Callable,
    ):
        """调整所有请求参数。"""
        await self._check_disconnect(
            check_client_disconnected, "Start Parameter Adjustment"
        )

        # 调整温度
        temp_to_set = request_params.get("temperature", DEFAULT_TEMPERATURE)
        await self._adjust_temperature(
            temp_to_set, page_params_cache, params_cache_lock, check_client_disconnected
        )
        await self._check_disconnect(
            check_client_disconnected, "After Temperature Adjustment"
        )

        # 调整最大Token
        max_tokens_to_set = request_params.get(
            "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS
        )
        await self._adjust_max_tokens(
            max_tokens_to_set,
            page_params_cache,
            params_cache_lock,
            model_id_to_use,
            parsed_model_list,
            check_client_disconnected,
        )
        await self._check_disconnect(
            check_client_disconnected, "After Max Tokens Adjustment"
        )

        # 调整停止序列
        stop_to_set = request_params.get("stop", DEFAULT_STOP_SEQUENCES)
        await self._adjust_stop_sequences(
            stop_to_set, page_params_cache, params_cache_lock, check_client_disconnected
        )
        await self._check_disconnect(
            check_client_disconnected, "After Stop Sequences Adjustment"
        )

        # 调整Top P
        top_p_to_set = request_params.get("top_p", DEFAULT_TOP_P)
        await self._adjust_top_p(top_p_to_set, check_client_disconnected)
        await self._check_disconnect(
            check_client_disconnected, "End Parameter Adjustment"
        )

        # 确保工具面板已展开，以便调整高级设置
        await self._ensure_tools_panel_expanded(check_client_disconnected)

        # 调整URL CONTEXT（允许按请求控制）
        if ENABLE_URL_CONTEXT:
            await self._open_url_content(check_client_disconnected)
        else:
            self.logger.debug("[Param] URL Context 功能已禁用，跳过调整")

        # 调整"思考预算" - handled by ThinkingController but called here to maintain flow?
        # Ideally adjust_parameters should coordinate, but if we split, we need to ensure method availability.
        # We will assume the final class inherits from all mixins.
        thinking_handler = getattr(self, "_handle_thinking_budget", None)
        if thinking_handler:
            await thinking_handler(
                request_params, model_id_to_use, check_client_disconnected
            )

        # 调整 Google Search 开关
        await self._adjust_google_search(
            request_params, model_id_to_use, check_client_disconnected
        )

    async def _adjust_temperature(
        self,
        temperature: float,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """调整温度参数。"""
        async with params_cache_lock:
            clamped_temp = max(0.0, min(2.0, temperature))
            if clamped_temp != temperature:
                self.logger.warning(
                    f"Temperature {temperature} out of range [0, 2], clamped to {clamped_temp}"
                )

            cached_temp = page_params_cache.get("temperature")
            if cached_temp is not None and abs(cached_temp - clamped_temp) < 0.001:
                self.logger.debug(f"[Param] Temperature: {clamped_temp} (缓存)")
                return

            # Need to check page value
            temp_input_locator = self.page.locator(TEMPERATURE_INPUT_SELECTOR)

            try:
                await expect_async(temp_input_locator).to_be_visible(timeout=5000)
                await self._check_disconnect(
                    check_client_disconnected, "温度调整 - 输入框可见后"
                )

                current_temp_str = await temp_input_locator.input_value(timeout=3000)
                await self._check_disconnect(
                    check_client_disconnected, "温度调整 - 读取输入框值后"
                )

                current_temp_float = float(current_temp_str)

                # Silent Success: Page value matches - single concise log
                if abs(current_temp_float - clamped_temp) < 0.001:
                    self.logger.debug(
                        f"[Param] Temperature: {clamped_temp} (与页面一致)"
                    )
                    page_params_cache["temperature"] = current_temp_float
                else:
                    # Value differs - show update process
                    self.logger.debug(
                        f"[Param] Temperature: {current_temp_float} -> {clamped_temp}"
                    )
                    await temp_input_locator.fill(str(clamped_temp), timeout=5000)
                    await self._check_disconnect(
                        check_client_disconnected, "温度调整 - 填充输入框后"
                    )

                    await asyncio.sleep(0.1)
                    new_temp_str = await temp_input_locator.input_value(timeout=3000)
                    new_temp_float = float(new_temp_str)

                    if abs(new_temp_float - clamped_temp) < 0.001:
                        self.logger.debug(
                            f"[Param] Temperature: 已更新 -> {new_temp_float}"
                        )
                        page_params_cache["temperature"] = new_temp_float
                    else:
                        self.logger.warning(
                            f"Temperature update failed. Page shows: {new_temp_float}, expected: {clamped_temp}."
                        )
                        page_params_cache.pop("temperature", None)
                        from browser_utils.operations import save_error_snapshot

                        await save_error_snapshot(
                            f"temperature_verify_fail_{self.req_id}"
                        )

            except ValueError as ve:
                self.logger.error(
                    f" 转换温度值为浮点数时出错. 错误: {ve}。清除缓存中的温度。"
                )
                page_params_cache.pop("temperature", None)
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot(f"temperature_value_error_{self.req_id}")
            except Exception as pw_err:
                if isinstance(pw_err, asyncio.CancelledError):
                    raise
                self.logger.error(
                    f" 操作温度输入框时发生错误: {pw_err}。清除缓存中的温度。"
                )
                page_params_cache.pop("temperature", None)
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot(f"temperature_playwright_error_{self.req_id}")
                if isinstance(pw_err, ClientDisconnectedError):
                    raise

    async def _adjust_max_tokens(
        self,
        max_tokens: int,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        model_id_to_use: Optional[str],
        parsed_model_list: list,
        check_client_disconnected: Callable,
    ):
        """调整最大输出Token参数。"""
        async with params_cache_lock:
            min_val_for_tokens = 1
            max_val_for_tokens_from_model = 65536

            if model_id_to_use and parsed_model_list:
                current_model_data = next(
                    (m for m in parsed_model_list if m.get("id") == model_id_to_use),
                    None,
                )
                if (
                    current_model_data
                    and current_model_data.get("supported_max_output_tokens")
                    is not None
                ):
                    try:
                        supported_tokens = int(
                            current_model_data["supported_max_output_tokens"]
                        )
                        if supported_tokens > 0:
                            max_val_for_tokens_from_model = supported_tokens
                        else:
                            self.logger.warning(
                                f"Model {model_id_to_use} has invalid supported_max_output_tokens: {supported_tokens}"
                            )
                    except (ValueError, TypeError):
                        self.logger.warning(
                            f"Model {model_id_to_use} supported_max_output_tokens parse failed"
                        )

            clamped_max_tokens = max(
                min_val_for_tokens, min(max_val_for_tokens_from_model, max_tokens)
            )
            if clamped_max_tokens != max_tokens:
                self.logger.debug(
                    f"[Param] Max Tokens: {max_tokens} -> {clamped_max_tokens} (超出限制)"
                )

            cached_max_tokens = page_params_cache.get("max_output_tokens")
            if (
                cached_max_tokens is not None
                and cached_max_tokens == clamped_max_tokens
            ):
                self.logger.debug(f"[Param] Max Tokens: {clamped_max_tokens} (缓存)")
                return

            # Need to check page value
            max_tokens_input_locator = self.page.locator(MAX_OUTPUT_TOKENS_SELECTOR)

            try:
                await expect_async(max_tokens_input_locator).to_be_visible(timeout=5000)
                await self._check_disconnect(
                    check_client_disconnected, "最大输出Token调整 - 输入框可见后"
                )

                current_max_tokens_str = await max_tokens_input_locator.input_value(
                    timeout=3000
                )
                current_max_tokens_int = int(current_max_tokens_str)

                # Silent Success: Page value matches - single concise log
                if current_max_tokens_int == clamped_max_tokens:
                    self.logger.debug(
                        f"[Param] Max Tokens: {clamped_max_tokens} (与页面一致)"
                    )
                    page_params_cache["max_output_tokens"] = current_max_tokens_int
                else:
                    # Value differs - show update process
                    self.logger.debug(
                        f"[Param] Max Tokens: {current_max_tokens_int} -> {clamped_max_tokens}"
                    )
                    await max_tokens_input_locator.fill(
                        str(clamped_max_tokens), timeout=5000
                    )
                    await self._check_disconnect(
                        check_client_disconnected, "最大输出Token调整 - 填充输入框后"
                    )

                    await asyncio.sleep(0.1)
                    new_max_tokens_str = await max_tokens_input_locator.input_value(
                        timeout=3000
                    )
                    new_max_tokens_int = int(new_max_tokens_str)

                    if new_max_tokens_int == clamped_max_tokens:
                        self.logger.debug(
                            f"[Param] Max Tokens: 已更新 -> {new_max_tokens_int}"
                        )
                        page_params_cache["max_output_tokens"] = new_max_tokens_int
                    else:
                        self.logger.warning(
                            f"Max Tokens update failed. Page shows: {new_max_tokens_int}, expected: {clamped_max_tokens}."
                        )
                        page_params_cache.pop("max_output_tokens", None)
                        from browser_utils.operations import save_error_snapshot

                        await save_error_snapshot(
                            f"max_tokens_verify_fail_{self.req_id}"
                        )

            except (ValueError, TypeError) as ve:
                self.logger.error(f"转换最大输出 Tokens 值时出错: {ve}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot(f"max_tokens_value_error_{self.req_id}")
            except Exception as e:
                if isinstance(e, asyncio.CancelledError):
                    raise
                self.logger.error(f"调整最大输出 Tokens 时出错: {e}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot(f"max_tokens_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _get_current_stop_sequences(self) -> set:
        """从页面读取当前显示的停止序列 (基于移除按钮的 aria-label)。"""
        try:
            # 策略：遍历所有 mat-chip 内的移除按钮
            # 实际 DOM 结构: <mat-chip><button class="remove-button" aria-label="Remove X">
            # aria-label 格式为 "Remove {text}" (例如 "Remove 1")
            # 使用 remove-button class 确保只匹配停止序列的移除按钮

            remove_btns = self.page.locator(
                'mat-chip button.remove-button[aria-label*="Remove"]'
            )
            count = await remove_btns.count()
            current_stops = set()

            for i in range(count):
                label = await remove_btns.nth(i).get_attribute("aria-label")
                if label and label.startswith("Remove "):
                    # 提取 "Remove " 之后的文本
                    text = label[7:].strip()
                    if text:
                        current_stops.add(text)
                else:
                    self.logger.warning(
                        f" 找到移除按钮但 aria-label 格式不匹配: {label}"
                    )

            self.logger.debug(f"[Param] 当前页面 Stop Sequences: {current_stops}")
            return current_stops
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.warning(f"读取当前停止序列失败: {e}")
            return set()

    async def _adjust_stop_sequences(
        self,
        stop_sequences,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """Adjust stop sequences parameter with Silent Success pattern."""
        async with params_cache_lock:
            self.logger.debug(
                f"[Param] Stop Sequences 输入: {stop_sequences} (类型: {type(stop_sequences).__name__})"
            )

            # Normalize input to set
            normalized_requested_stops: set = set()
            if stop_sequences is not None:
                if isinstance(stop_sequences, str):
                    if stop_sequences.strip():
                        normalized_requested_stops.add(stop_sequences.strip())
                elif isinstance(stop_sequences, list):
                    for s in stop_sequences:
                        if isinstance(s, str) and s.strip():
                            normalized_requested_stops.add(s.strip())

            self.logger.debug(f"[Param] 规范化后: {normalized_requested_stops}")

            # Format for display
            display_val = (
                "Empty"
                if not normalized_requested_stops
                else str(sorted(normalized_requested_stops))
            )

            # Read current page state
            current_page_stops = await self._get_current_stop_sequences()

            # Silent Success: If page matches, single concise log
            if current_page_stops == normalized_requested_stops:
                self.logger.debug(f"[Param] Stop Sequences: {display_val} (与页面一致)")
                page_params_cache["stop_sequences"] = normalized_requested_stops
                return

            stop_input_locator = self.page.locator(STOP_SEQUENCE_INPUT_SELECTOR)

            # Calculate delta
            to_add = normalized_requested_stops - current_page_stops
            to_remove = current_page_stops - normalized_requested_stops

            # Log the update intent
            current_display = (
                "Empty" if not current_page_stops else str(sorted(current_page_stops))
            )
            self.logger.debug(
                f"[Param] Stop Sequences: {current_display} -> {display_val}"
            )
            self.logger.debug(f"[Param] Delta - 添加: {to_add}, 移除: {to_remove}")

            try:
                # 1. Remove excess sequences
                if to_remove:
                    for text_to_remove in to_remove:
                        await self._check_disconnect(
                            check_client_disconnected,
                            f"Removing stop: {text_to_remove}",
                        )
                        selector = f'mat-chip button.remove-button[aria-label="Remove {text_to_remove}"]'
                        remove_btn = self.page.locator(selector)

                        if await remove_btn.count() > 0:
                            await remove_btn.first.click(timeout=2000)
                            try:
                                await expect_async(remove_btn).to_have_count(
                                    0, timeout=3000
                                )
                                self.logger.debug(f"[Param] 已移除: {text_to_remove}")
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                self.logger.debug(
                                    f"[Param] Chip 可能未完全移除: {text_to_remove}"
                                )
                        else:
                            # Fallback: fuzzy match aria-label
                            fallback_selector = f'mat-chip button.remove-button[aria-label*="Remove {text_to_remove}"]'
                            fallback_btn = self.page.locator(fallback_selector)
                            if await fallback_btn.count() > 0:
                                await fallback_btn.first.click(timeout=2000)
                                self.logger.debug(
                                    f"[Param] 已移除 (模糊匹配): {text_to_remove}"
                                )
                            else:
                                self.logger.warning(
                                    f"Cannot find remove button for: {text_to_remove}"
                                )

                # 2. Add missing sequences
                if to_add:
                    await expect_async(stop_input_locator).to_be_visible(timeout=5000)
                    for seq in to_add:
                        await self._check_disconnect(
                            check_client_disconnected, f"Adding stop: {seq}"
                        )
                        await stop_input_locator.fill(seq, timeout=3000)
                        await stop_input_locator.press("Enter", timeout=3000)
                        await asyncio.sleep(0.2)
                        self.logger.debug(f"[Param] 已添加: {seq}")

                # 3. Verify final state
                final_page_stops = await self._get_current_stop_sequences()
                if final_page_stops == normalized_requested_stops:
                    page_params_cache["stop_sequences"] = normalized_requested_stops
                    self.logger.debug(f"[Param] Stop Sequences: {display_val} (已更新)")
                else:
                    self.logger.warning(
                        f"Stop Sequences verification failed. "
                        f"Expected: {normalized_requested_stops}, Actual: {final_page_stops}"
                    )
                    page_params_cache["stop_sequences"] = final_page_stops
                    from browser_utils.operations import save_error_snapshot

                    await save_error_snapshot(
                        f"stop_sequence_verify_fail_{self.req_id}"
                    )

            except Exception as e:
                if isinstance(e, asyncio.CancelledError):
                    raise
                self.logger.error(f"Stop Sequences error: {e}")
                page_params_cache.pop("stop_sequences", None)
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot(f"stop_sequence_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _adjust_top_p(self, top_p: float, check_client_disconnected: Callable):
        """调整Top P参数。"""
        clamped_top_p = max(0.0, min(1.0, top_p))

        if abs(clamped_top_p - top_p) > 1e-9:
            self.logger.warning(
                f"Top P {top_p} out of range [0, 1], clamped to {clamped_top_p}"
            )

        top_p_input_locator = self.page.locator(TOP_P_INPUT_SELECTOR)
        try:
            await expect_async(top_p_input_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "Top P 调整 - 输入框可见后"
            )

            current_top_p_str = await top_p_input_locator.input_value(timeout=3000)
            current_top_p_float = float(current_top_p_str)

            # Value differs - show update process
            if abs(current_top_p_float - clamped_top_p) > 1e-9:
                self.logger.debug(
                    f"[Param] Top P: {current_top_p_float} -> {clamped_top_p}"
                )
                await top_p_input_locator.fill(str(clamped_top_p), timeout=5000)
                await self._check_disconnect(
                    check_client_disconnected, "Top P 调整 - 填充输入框后"
                )

                # 验证设置是否成功
                await asyncio.sleep(0.1)
                new_top_p_str = await top_p_input_locator.input_value(timeout=3000)
                new_top_p_float = float(new_top_p_str)

                if abs(new_top_p_float - clamped_top_p) <= 1e-9:
                    self.logger.debug(f"[Param] Top P: 已更新 -> {new_top_p_float}")
                else:
                    self.logger.warning(
                        f"Top P update failed. Page shows: {new_top_p_float}, expected: {clamped_top_p}."
                    )
                    from browser_utils.operations import save_error_snapshot

                    await save_error_snapshot(f"top_p_verify_fail_{self.req_id}")
            else:
                # Silent Success: Page value matches - single concise log
                self.logger.debug(f"[Param] Top P: {clamped_top_p} (与页面一致)")

        except (ValueError, TypeError) as ve:
            self.logger.error(f"转换 Top P 值时出错: {ve}")
            from browser_utils.operations import save_error_snapshot

            await save_error_snapshot(f"top_p_value_error_{self.req_id}")
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"调整 Top P 时出错: {e}")
            from browser_utils.operations import save_error_snapshot

            await save_error_snapshot(f"top_p_error_{self.req_id}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _ensure_tools_panel_expanded(self, check_client_disconnected: Callable):
        """确保包含高级工具（URL上下文、思考预算等）的面板是展开的。"""
        self.logger.debug("[Param] 检查工具面板状态...")
        try:
            collapse_tools_locator = self.page.locator(
                'button[aria-label="Expand or collapse tools"]'
            )
            await expect_async(collapse_tools_locator).to_be_visible(timeout=5000)

            grandparent_locator = collapse_tools_locator.locator("xpath=../..")
            class_string = await grandparent_locator.get_attribute(
                "class", timeout=3000
            )

            if class_string and "expanded" not in class_string.split():
                self.logger.debug("[Param] 工具面板未展开，正在展开...")
                await collapse_tools_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(
                    check_client_disconnected, "展开工具面板后"
                )
                # 等待展开动画完成
                await expect_async(grandparent_locator).to_have_class(
                    re.compile(r".*expanded.*"), timeout=5000
                )
                self.logger.debug("[Param] 工具面板已成功展开")
            else:
                self.logger.debug("[Param] 工具面板已展开")
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"展开工具面板时发生错误: {e}")
            # 即使出错，也继续尝试执行后续操作，但记录错误
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _open_url_content(self, check_client_disconnected: Callable):
        """仅负责打开 URL Context 开关，前提是面板已展开。"""
        try:
            self.logger.info("检查并启用 URL Context 开关...")
            use_url_content_selector = self.page.locator(USE_URL_CONTEXT_SELECTOR)
            await expect_async(use_url_content_selector).to_be_visible(timeout=5000)

            is_checked = await use_url_content_selector.get_attribute("aria-checked")
            if "false" == is_checked:
                self.logger.info("URL Context 开关未开启，正在点击以开启...")
                await use_url_content_selector.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(
                    check_client_disconnected, "点击URLCONTEXT后"
                )
                self.logger.info("URL Context 开关已点击。")
            else:
                self.logger.info("URL Context 开关已处于开启状态。")
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"操作 USE_URL_CONTEXT_SELECTOR 时发生错误:{e}。")
            if isinstance(e, ClientDisconnectedError):
                raise

    def _should_enable_google_search(self, request_params: Dict[str, Any]) -> bool:
        """Determine if Google Search should be enabled based on request or defaults."""
        if "tools" in request_params and request_params.get("tools") is not None:
            tools = request_params.get("tools")
            has_google_search_tool = False
            if isinstance(tools, list):
                for tool in tools:
                    if isinstance(tool, dict):
                        if tool.get("google_search_retrieval") is not None:
                            has_google_search_tool = True
                            break
                        if tool.get("function", {}).get("name") == "googleSearch":
                            has_google_search_tool = True
                            break
            self.logger.debug(
                f"[Param] Tools 参数: Google Search = {has_google_search_tool}"
            )
            return has_google_search_tool
        else:
            self.logger.debug(f"[Param] Tools: 未指定 (默认 {ENABLE_GOOGLE_SEARCH})")
            return ENABLE_GOOGLE_SEARCH

    def _supports_google_search(self, model_id: Optional[str]) -> bool:
        """Check if a model supports Google Search based on model ID pattern."""
        if not model_id:
            return True  # Default to true for unknown models

        model_lower = model_id.lower()

        # Gemini 2.0 models don't support Google Search
        if "gemini-2.0" in model_lower or "gemini2.0" in model_lower:
            return False

        # All other models support Google Search
        return True

    async def _adjust_google_search(
        self,
        request_params: Dict[str, Any],
        model_id: Optional[str],
        check_client_disconnected: Callable,
    ):
        """Adjust Google Search toggle with Silent Success pattern."""
        # Check if model supports Google Search before attempting toggle
        if not self._supports_google_search(model_id):
            self.logger.debug("[Param] Google Search: 该模型不支持此功能，跳过")
            return

        should_enable_search = self._should_enable_google_search(request_params)
        desired_state = "On" if should_enable_search else "Off"

        toggle_selector = GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR

        try:
            toggle_locator = self.page.locator(toggle_selector)
            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "Google Search toggle visible"
            )

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            is_currently_checked = is_checked_str == "true"
            current_state = "On" if is_currently_checked else "Off"

            if should_enable_search == is_currently_checked:
                self.logger.debug(
                    f"[Param] Google Search: {desired_state} (与页面一致)"
                )
                return

            self.logger.debug(
                f"[Param] Google Search: {current_state} -> {desired_state}"
            )
            try:
                await toggle_locator.scroll_into_view_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
            await self._check_disconnect(
                check_client_disconnected, "Google Search toggle clicked"
            )
            await asyncio.sleep(0.5)  # Wait for UI update
            new_state = await toggle_locator.get_attribute("aria-checked")
            if (new_state == "true") == should_enable_search:
                self.logger.debug(f"[Param] Google Search: {desired_state} (已更新)")
            else:
                actual = "On" if new_state == "true" else "Off"
                self.logger.warning(
                    f"Google Search toggle failed. Expected: {desired_state}, Actual: {actual}"
                )

        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            # AssertionError from expect_async visibility check is expected for models
            # that don't have Google Search tool (e.g., gemini-2.0-flash-lite)
            if isinstance(e, AssertionError) and "visible" in str(e).lower():
                self.logger.debug("[Param] Google Search: 该模型不支持此功能，跳过")
            else:
                self.logger.error(f"Google Search toggle error: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
