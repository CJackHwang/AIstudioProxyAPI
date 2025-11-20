"""
PageController模块
封装了所有与Playwright页面直接交互的复杂逻辑。
"""
import asyncio
import base64
import mimetypes
import re
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import Page as AsyncPage
from playwright.async_api import TimeoutError
from playwright.async_api import expect as expect_async

from config import (
    CLEAR_CHAT_BUTTON_SELECTOR,
    CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR,
    CLEAR_CHAT_VERIFY_TIMEOUT_MS,
    CLICK_TIMEOUT_MS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_STOP_SEQUENCES,
    DEFAULT_TEMPERATURE,
    DEFAULT_THINKING_BUDGET,
    DEFAULT_TOP_P,
    EDIT_MESSAGE_BUTTON_SELECTOR,
    ENABLE_GOOGLE_SEARCH,
    ENABLE_THINKING_BUDGET,
    ENABLE_THINKING_MODE_TOGGLE_SELECTOR,
    ENABLE_URL_CONTEXT,
    GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR,
    MAT_CHIP_REMOVE_BUTTON_SELECTOR,
    MAX_OUTPUT_TOKENS_SELECTOR,
    OVERLAY_SELECTOR,
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    RESPONSE_TEXT_SELECTOR,
    SET_THINKING_BUDGET_TOGGLE_SELECTOR,
    STOP_SEQUENCE_INPUT_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
    TEMPERATURE_INPUT_SELECTOR,
    THINKING_BUDGET_INPUT_SELECTOR,
    THINKING_LEVEL_DROPDOWN_SELECTOR,
    THINKING_LEVEL_OPTION_HIGH_SELECTOR,
    THINKING_LEVEL_OPTION_LOW_SELECTOR,
    THINKING_LEVEL_SELECT_SELECTOR,
    TOP_P_INPUT_SELECTOR,
    UPLOAD_BUTTON_SELECTOR,
    USE_URL_CONTEXT_SELECTOR,
    WAIT_FOR_ELEMENT_TIMEOUT_MS,
    AI_STUDIO_URL_PATTERN,
)
from models import ClientDisconnectedError, QuotaExceededError
from .initialization import enable_temporary_chat_mode
from .operations import (
    _get_final_response_content,
    _wait_for_response_completion,
    check_quota_limit,
    save_error_snapshot,
)
from .thinking_normalizer import format_directive_log, normalize_reasoning_effort


class PageController:
    """封装了与AI Studio页面交互的所有操作。"""

    def __init__(self, page: AsyncPage, logger, req_id: str):
        self.page = page
        self.logger = logger
        self.req_id = req_id

    async def _check_disconnect(self, check_client_disconnected: Callable, stage: str):
        """检查客户端是否断开连接。"""
        if check_client_disconnected(stage):
            raise ClientDisconnectedError(
                f"[{self.req_id}] Client disconnected at stage: {stage}"
            )

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
        self.logger.info(f"[{self.req_id}] 开始调整所有请求参数...")
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
            self.logger.info(f"[{self.req_id}] URL Context 功能已禁用，跳过调整。")

        # 调整“思考预算”
        await self._handle_thinking_budget(
            request_params, model_id_to_use, check_client_disconnected
        )

        # 调整 Google Search 开关
        await self._adjust_google_search(request_params, check_client_disconnected)

    async def _handle_thinking_budget(
        self,
        request_params: Dict[str, Any],
        model_id_to_use: Optional[str],
        check_client_disconnected: Callable,
    ):
        """处理思考模式和预算的调整逻辑。"""
        reasoning_effort = request_params.get("reasoning_effort")

        directive = normalize_reasoning_effort(reasoning_effort)
        self.logger.info(f"[{self.req_id}] 思考模式指令: {format_directive_log(directive)}")

        uses_level = self._uses_thinking_level(
            model_id_to_use
        ) and await self._has_thinking_dropdown()

        def _should_enable_from_raw(rv: Any) -> bool:
            try:
                if isinstance(rv, str):
                    rs = rv.strip().lower()
                    if rs in ["high", "low", "none", "-1"]:
                        return True
                    v = int(rs)
                    return v > 0
                if isinstance(rv, int):
                    return rv > 0 or rv == -1
            except Exception:
                return False
            return False

        desired_enabled = directive.thinking_enabled or _should_enable_from_raw(
            reasoning_effort
        )

        has_main_toggle = self._model_has_main_thinking_toggle(model_id_to_use)
        if has_main_toggle:
            self.logger.info(
                f"[{self.req_id}] 开始设置主思考开关到: {'开启' if desired_enabled else '关闭'}"
            )
            await self._control_thinking_mode_toggle(
                should_be_enabled=desired_enabled,
                check_client_disconnected=check_client_disconnected,
            )
        else:
            self.logger.info(f"[{self.req_id}] 该模型无主思考开关，跳过开关设置。")

        if not desired_enabled:
            # 若关闭思考，则确保预算开关关闭（兼容旧UI）
            await self._control_thinking_budget_toggle(
                should_be_checked=False,
                check_client_disconnected=check_client_disconnected,
            )
            return

        # 2) 已开启思考：根据模型类型设置等级或预算
        if uses_level:
            rv = reasoning_effort
            level_to_set = None
            if isinstance(rv, str):
                rs = rv.strip().lower()
                if rs == "low":
                    level_to_set = "low"
                elif rs in ["high", "none", "-1"]:
                    level_to_set = "high"
                else:
                    try:
                        v = int(rs)
                        level_to_set = "high" if v >= 8000 else "low"
                    except Exception:
                        level_to_set = None
            elif isinstance(rv, int):
                level_to_set = "high" if rv >= 8000 or rv == -1 else "low"

            if level_to_set is None:
                self.logger.info(f"[{self.req_id}] 无法解析等级，保持当前等级。")
            else:
                await self._set_thinking_level(level_to_set, check_client_disconnected)
            return

        if not directive.thinking_enabled:
            self.logger.info(f"[{self.req_id}] 尝试关闭主思考开关...")
            success = await self._control_thinking_mode_toggle(
                should_be_enabled=False,
                check_client_disconnected=check_client_disconnected,
            )

            if not success:
                self.logger.warning(f"[{self.req_id}] 主思考开关不可用，使用降级方案：设置预算为 0")
                await self._control_thinking_budget_toggle(
                    should_be_checked=True,
                    check_client_disconnected=check_client_disconnected,
                )
                await self._set_thinking_budget_value(0, check_client_disconnected)
            return

        # 场景2和3: 开启思考模式
        self.logger.info(f"[{self.req_id}] 开启主思考开关...")
        await self._control_thinking_mode_toggle(
            should_be_enabled=True, check_client_disconnected=check_client_disconnected
        )

        # --- FIX START: Gemini 3.0 Bypass ---
        # Check if we are on the new Gemini 3.0 UI
        new_thinking_dropdown = self.page.locator(THINKING_LEVEL_DROPDOWN_SELECTOR)
        if await new_thinking_dropdown.is_visible(timeout=500):
            self.logger.info(
                f"[{self.req_id}] 检测到 Gemini 3.0+ UI (Thinking Level Dropdown). 跳过预算滑块配置。"
            )
            return
        # --- FIX END ---

        # 场景2: 开启思考，不限制预算
        if not directive.budget_enabled:
            self.logger.info(f"[{self.req_id}] 关闭手动预算限制...")
            await self._control_thinking_budget_toggle(
                should_be_checked=False,
                check_client_disconnected=check_client_disconnected,
            )

        # 场景3: 开启思考，限制预算
        else:
            value_to_set = directive.budget_value or 0
            model_lower = (model_id_to_use or "").lower()
            if "gemini-2.5-pro" in model_lower:
                value_to_set = min(value_to_set, 32768)
            elif "flash-lite" in model_lower:
                value_to_set = min(value_to_set, 24576)
            elif "flash" in model_lower:
                value_to_set = min(value_to_set, 24576)
            self.logger.info(
                f"[{self.req_id}] 开启手动预算限制并设置预算值: {value_to_set} tokens"
            )
            await self._control_thinking_budget_toggle(
                should_be_checked=True,
                check_client_disconnected=check_client_disconnected,
            )
            await self._set_thinking_budget_value(
                value_to_set, check_client_disconnected
            )

    async def _has_thinking_dropdown(self) -> bool:
        try:
            locator = self.page.locator(THINKING_LEVEL_SELECT_SELECTOR)
            count = await locator.count()
            if count == 0:
                return False
            try:
                await expect_async(locator.first).to_be_visible(timeout=2000)
                return True
            except Exception:
                return True
        except Exception:
            return False

    def _uses_thinking_level(self, model_id_to_use: Optional[str]) -> bool:
        """仅在 Gemini 3 Pro 系列上使用“思考等级”逻辑，其它模型一律使用预算。"""
        try:
            mid = (model_id_to_use or "").lower()
            return ("gemini-3" in mid) and ("pro" in mid)
        except Exception:
            return False

    def _model_has_main_thinking_toggle(self, model_id_to_use: Optional[str]) -> bool:
        try:
            mid = (model_id_to_use or "").lower()
            return "flash" in mid
        except Exception:
            return False

    async def _set_thinking_level(
        self, level: str, check_client_disconnected: Callable
    ):
        target_option_selector = (
            THINKING_LEVEL_OPTION_HIGH_SELECTOR
            if level.lower() == "high"
            else THINKING_LEVEL_OPTION_LOW_SELECTOR
        )
        try:
            trigger = self.page.locator(THINKING_LEVEL_SELECT_SELECTOR)
            await expect_async(trigger).to_be_visible(timeout=5000)
            await trigger.scroll_into_view_if_needed()
            await trigger.click(timeout=CLICK_TIMEOUT_MS)
            await self._check_disconnect(
                check_client_disconnected, "Thinking Level 打开后"
            )
            option = self.page.locator(target_option_selector)
            await expect_async(option).to_be_visible(timeout=5000)
            await option.click(timeout=CLICK_TIMEOUT_MS)
            await asyncio.sleep(0.2)
            try:
                await expect_async(
                    self.page.locator(
                        '[role="listbox"][aria-label="Thinking Level"], [role="listbox"][aria-label="Thinking level"]'
                    ).first
                ).to_be_hidden(timeout=2000)
            except Exception:
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            value_text = await trigger.locator(
                ".mat-mdc-select-value-text .mat-mdc-select-min-line"
            ).inner_text(timeout=3000)
            if value_text.strip().lower() == level.lower():
                self.logger.info(f"[{self.req_id}] 已设置 Thinking Level 为 {level}")
            else:
                self.logger.warning(
                    f"[{self.req_id}] Thinking Level 验证失败，页面值: {value_text}, 期望: {level}"
                )
        except Exception as e:
            self.logger.error(f"[{self.req_id}] 设置 Thinking Level 时出错: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _set_thinking_budget_value(
        self, token_budget: int, check_client_disconnected: Callable
    ):
        """设置思考预算的具体数值。"""
        self.logger.info(f"[{self.req_id}] 设置思考预算值: {token_budget} tokens")

        budget_input_locator = self.page.locator(THINKING_BUDGET_INPUT_SELECTOR)

        try:
            await expect_async(budget_input_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "思考预算调整 - 输入框可见后")

            adjusted_budget = token_budget

            try:
                await self.page.evaluate(
                    "([selector, desired]) => {\n"
                    "  const num = Number(desired);\n"
                    "  const el = document.querySelector(selector);\n"
                    "  if (!el) return false;\n"
                    "  const container = el.closest('[data-test-slider]') || el.parentElement;\n"
                    "  const inputs = container ? container.querySelectorAll('input') : [el];\n"
                    "  const ranges = container ? container.querySelectorAll('input[type=\"range\"]') : [];\n"
                    "  inputs.forEach(inp => {\n"
                    "    try {\n"
                    "      if (Number.isFinite(num)) {\n"
                    "        const curMaxAttr = inp.getAttribute('max');\n"
                    "        const curMax = curMaxAttr ? Number(curMaxAttr) : undefined;\n"
                    "        if (curMax !== undefined && curMax < num) {\n"
                    "          inp.setAttribute('max', String(num));\n"
                    "        }\n"
                    "        if (inp.max && Number(inp.max) < num) {\n"
                    "          inp.max = String(num);\n"
                    "        }\n"
                    "        inp.value = String(num);\n"
                    "        inp.dispatchEvent(new Event('input', { bubbles: true }));\n"
                    "        inp.dispatchEvent(new Event('change', { bubbles: true }));\n"
                    "        inp.dispatchEvent(new Event('blur', { bubbles: true }));\n"
                    "      }\n"
                    "    } catch (_) {}\n"
                    "  });\n"
                    "  ranges.forEach(r => {\n"
                    "    try {\n"
                    "      if (Number.isFinite(num)) {\n"
                    "        const curMaxAttr = r.getAttribute('max');\n"
                    "        const curMax = curMaxAttr ? Number(curMaxAttr) : undefined;\n"
                    "        if (curMax !== undefined && curMax < num) {\n"
                    "          r.setAttribute('max', String(num));\n"
                    "        }\n"
                    "        if (r.max && Number(r.max) < num) {\n"
                    "          r.max = String(num);\n"
                    "        }\n"
                    "        r.value = String(num);\n"
                    "        r.dispatchEvent(new Event('input', { bubbles: true }));\n"
                    "        r.dispatchEvent(new Event('change', { bubbles: true }));\n"
                    "      }\n"
                    "    } catch (_) {}\n"
                    "  });\n"
                    "  return true;\n"
                    "}",
                    [THINKING_BUDGET_INPUT_SELECTOR, adjusted_budget],
                )
            except Exception:
                pass

            self.logger.info(f"[{self.req_id}] 设置思考预算为: {adjusted_budget}")
            await budget_input_locator.fill(str(adjusted_budget), timeout=5000)
            await self._check_disconnect(check_client_disconnected, "思考预算调整 - 填充输入框后")

            # 验证
            try:
                await expect_async(budget_input_locator).to_have_value(
                    str(adjusted_budget), timeout=3000
                )
                self.logger.info(f"[{self.req_id}] ✅ 思考预算已成功更新为: {adjusted_budget}")
            except Exception:
                new_value_str = await budget_input_locator.input_value(timeout=3000)
                try:
                    new_value_int = int(new_value_str)
                except Exception:
                    new_value_int = -1
                if new_value_int == adjusted_budget:
                    self.logger.info(
                        f"[{self.req_id}] ✅ 思考预算已成功更新为: {new_value_str}"
                    )
                else:
                    # 最后回退：如果页面仍然小于请求值，尝试按页面 max 进行填充
                    try:
                        page_max_str = await budget_input_locator.get_attribute("max")
                        page_max_val = (
                            int(page_max_str) if page_max_str is not None else None
                        )
                    except Exception:
                        page_max_val = None
                    if page_max_val is not None and page_max_val < adjusted_budget:
                        self.logger.warning(
                            f"[{self.req_id}] 页面最大预算为 {page_max_val}，请求的预算 {adjusted_budget} 已调整为 {page_max_val}"
                        )
                        try:
                            await self.page.evaluate(
                                "([selector, desired]) => {\n"
                                "  const num = Number(desired);\n"
                                "  const el = document.querySelector(selector);\n"
                                "  if (!el) return false;\n"
                                "  const container = el.closest('[data-test-slider]') || el.parentElement;\n"
                                "  const inputs = container ? container.querySelectorAll('input') : [el];\n"
                                "  inputs.forEach(inp => {\n"
                                "    try { inp.value = String(num); inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true })); } catch (_) {}\n"
                                "  });\n"
                                "  return true;\n"
                                "}",
                                [THINKING_BUDGET_INPUT_SELECTOR, page_max_val],
                            )
                        except Exception:
                            pass
                        await budget_input_locator.fill(str(page_max_val), timeout=5000)
                        try:
                            await expect_async(budget_input_locator).to_have_value(
                                str(page_max_val), timeout=2000
                            )
                        except Exception:
                            pass
                    else:
                        self.logger.warning(
                            f"[{self.req_id}] ⚠️ 思考预算更新后验证失败。页面显示: {new_value_str}, 期望: {adjusted_budget}"
                        )

        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 调整思考预算时出错: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise

    def _should_enable_google_search(self, request_params: Dict[str, Any]) -> bool:
        """根据请求参数或默认配置决定是否应启用 Google Search。"""
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
            self.logger.info(
                f"[{self.req_id}] 请求中包含 'tools' 参数。检测到 Google Search 工具: {has_google_search_tool}。"
            )
            return has_google_search_tool
        else:
            self.logger.info(
                f"[{self.req_id}] 请求中不包含 'tools' 参数。使用默认配置 ENABLE_GOOGLE_SEARCH: {ENABLE_GOOGLE_SEARCH}。"
            )
            return ENABLE_GOOGLE_SEARCH

    async def _adjust_google_search(
        self, request_params: Dict[str, Any], check_client_disconnected: Callable
    ):
        """根据请求参数或默认配置，双向控制 Google Search 开关。"""
        self.logger.info(f"[{self.req_id}] 检查并调整 Google Search 开关...")

        should_enable_search = self._should_enable_google_search(request_params)

        toggle_selector = GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR

        try:
            toggle_locator = self.page.locator(toggle_selector)
            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "Google Search 开关 - 元素可见后"
            )

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            is_currently_checked = is_checked_str == "true"
            self.logger.info(
                f"[{self.req_id}] Google Search 开关当前状态: '{is_checked_str}'。期望状态: {should_enable_search}"
            )

            if should_enable_search != is_currently_checked:
                action = "打开" if should_enable_search else "关闭"
                self.logger.info(
                    f"[{self.req_id}] Google Search 开关状态与期望不符。正在点击以{action}..."
                )
                try:
                    await toggle_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(
                    check_client_disconnected, f"Google Search 开关 - 点击{action}后"
                )
                await asyncio.sleep(0.5)  # 等待UI更新
                new_state = await toggle_locator.get_attribute("aria-checked")
                if (new_state == "true") == should_enable_search:
                    self.logger.info(f"[{self.req_id}] ✅ Google Search 开关已成功{action}。")
                else:
                    self.logger.warning(
                        f"[{self.req_id}] ⚠️ Google Search 开关{action}失败。当前状态: '{new_state}'"
                    )
            else:
                self.logger.info(f"[{self.req_id}] Google Search 开关已处于期望状态，无需操作。")

        except Exception as e:
            self.logger.error(
                f"[{self.req_id}] ❌ 操作 'Google Search toggle' 开关时发生错误: {e}"
            )
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _ensure_tools_panel_expanded(self, check_client_disconnected: Callable):
        """确保包含高级工具（URL上下文、思考预算等）的面板是展开的。"""
        self.logger.info(f"[{self.req_id}] 检查并确保工具面板已展开...")
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
                self.logger.info(f"[{self.req_id}] 工具面板未展开，正在点击以展开...")
                await collapse_tools_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, "展开工具面板后")
                # 等待展开动画完成
                await expect_async(grandparent_locator).to_have_class(
                    re.compile(r".*expanded.*"), timeout=5000
                )
                self.logger.info(f"[{self.req_id}] ✅ 工具面板已成功展开。")
            else:
                self.logger.info(f"[{self.req_id}] 工具面板已处于展开状态。")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 展开工具面板时发生错误: {e}")
            # 即使出错，也继续尝试执行后续操作，但记录错误
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _open_url_content(self, check_client_disconnected: Callable):
        """仅负责打开 URL Context 开关，前提是面板已展开。"""
        try:
            self.logger.info(f"[{self.req_id}] 检查并启用 URL Context 开关...")
            use_url_content_selector = self.page.locator(USE_URL_CONTEXT_SELECTOR)
            await expect_async(use_url_content_selector).to_be_visible(timeout=5000)

            is_checked = await use_url_content_selector.get_attribute("aria-checked")
            if "false" == is_checked:
                self.logger.info(f"[{self.req_id}] URL Context 开关未开启，正在点击以开启...")
                await use_url_content_selector.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, "点击URLCONTEXT后")
                self.logger.info(f"[{self.req_id}] ✅ URL Context 开关已点击。")
            else:
                self.logger.info(f"[{self.req_id}] URL Context 开关已处于开启状态。")
        except Exception as e:
            self.logger.error(
                f"[{self.req_id}] ❌ 操作 USE_URL_CONTEXT_SELECTOR 时发生错误:{e}。"
            )
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _control_thinking_mode_toggle(
        self, should_be_enabled: bool, check_client_disconnected: Callable
    ) -> bool:
        """
        控制主思考开关（总开关），决定是否启用思考模式。

        参数:
            should_be_enabled: 期望的开关状态（True=开启, False=关闭）
            check_client_disconnected: 客户端断开检测函数

        返回:
            bool: 是否成功设置到期望状态（如果开关不存在或被禁用，返回False）
        """
        legacy_toggle_selector = ENABLE_THINKING_MODE_TOGGLE_SELECTOR
        new_dropdown_selector = THINKING_LEVEL_DROPDOWN_SELECTOR

        self.logger.info(
            f"[{self.req_id}] 控制主思考开关，期望状态: {'开启' if should_be_enabled else '关闭'}..."
        )

        try:
            # 1. 优先检查新版 UI (Gemini 3.0+ Dropdown)
            # 使用极短超时 (500ms) 避免在旧版 UI 上造成延迟
            new_dropdown_locator = self.page.locator(new_dropdown_selector)
            if await new_dropdown_locator.is_visible(timeout=500):
                self.logger.info(
                    f"[{self.req_id}] 检测到 Gemini 3.0+ UI (Thinking Level Dropdown)。"
                )
                # 存在 Dropdown 即意味着处于新版 UI，此时不要尝试去点击旧版 Toggle
                return True

            # 2. 检查旧版 UI (Toggle)
            toggle_locator = self.page.locator(legacy_toggle_selector)

            # 等待元素可见（5秒超时）
            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            try:
                await toggle_locator.scroll_into_view_if_needed()
            except Exception:
                pass
            await self._check_disconnect(check_client_disconnected, "主思考开关 - 元素可见后")

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            current_state_is_enabled = is_checked_str == "true"
            self.logger.info(
                f"[{self.req_id}] 主思考开关当前状态: {is_checked_str} (是否开启: {current_state_is_enabled})"
            )

            if current_state_is_enabled != should_be_enabled:
                action = "开启" if should_be_enabled else "关闭"
                self.logger.info(f"[{self.req_id}] 主思考开关需要切换，正在点击以{action}思考模式...")

                try:
                    await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                except Exception:
                    try:
                        root = self.page.locator(
                            'mat-slide-toggle[data-test-toggle="enable-thinking"]'
                        )
                        label = root.locator("label.mdc-label")
                        await expect_async(label).to_be_visible(timeout=2000)
                        await label.click(timeout=CLICK_TIMEOUT_MS)
                    except Exception:
                        raise
                await self._check_disconnect(
                    check_client_disconnected, f"主思考开关 - 点击{action}后"
                )

                # 验证新状态
                new_state_str = await toggle_locator.get_attribute("aria-checked")
                new_state_is_enabled = new_state_str == "true"

                if new_state_is_enabled == should_be_enabled:
                    self.logger.info(
                        f"[{self.req_id}] ✅ 主思考开关已成功{action}。新状态: {new_state_str}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"[{self.req_id}] ⚠️ 主思考开关{action}后验证失败。期望: {should_be_enabled}, 实际: {new_state_str}"
                    )
                    return False
            else:
                self.logger.info(f"[{self.req_id}] 主思考开关已处于期望状态，无需操作。")
                return True

        except TimeoutError:
            self.logger.warning(
                f"[{self.req_id}] ⚠️ 主思考开关元素未找到或不可见（当前模型可能不支持思考模式）"
            )
            return False
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 操作主思考开关时发生错误: {e}")
            await save_error_snapshot(f"thinking_mode_toggle_error_{self.req_id}")
            if isinstance(e, ClientDisconnectedError):
                raise
            return False

    async def _control_thinking_budget_toggle(
        self, should_be_checked: bool, check_client_disconnected: Callable
    ):
        """
        根据 should_be_checked 的值，控制 "Thinking Budget" 滑块开关的状态。
        （手动预算开关，控制是否限制思考预算）
        """
        toggle_selector = SET_THINKING_BUDGET_TOGGLE_SELECTOR
        self.logger.info(
            f"[{self.req_id}] 控制 'Thinking Budget' 开关，期望状态: {'选中' if should_be_checked else '未选中'}..."
        )

        try:
            toggle_locator = self.page.locator(toggle_selector)
            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            try:
                await toggle_locator.scroll_into_view_if_needed()
            except Exception:
                pass
            await self._check_disconnect(check_client_disconnected, "思考预算开关 - 元素可见后")

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            current_state_is_checked = is_checked_str == "true"
            self.logger.info(
                f"[{self.req_id}] 思考预算开关当前 'aria-checked' 状态: {is_checked_str} (当前是否选中: {current_state_is_checked})"
            )

            if current_state_is_checked != should_be_checked:
                action = "启用" if should_be_checked else "禁用"
                self.logger.info(f"[{self.req_id}] 思考预算开关当前状态与期望不符，正在点击以{action}...")
                try:
                    await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                except Exception:
                    try:
                        root = self.page.locator(
                            'mat-slide-toggle[data-test-toggle="manual-budget"]'
                        )
                        label = root.locator("label.mdc-label")
                        await expect_async(label).to_be_visible(timeout=2000)
                        await label.click(timeout=CLICK_TIMEOUT_MS)
                    except Exception:
                        raise
                await self._check_disconnect(
                    check_client_disconnected, f"思考预算开关 - 点击{action}后"
                )

                await asyncio.sleep(0.5)
                new_state_str = await toggle_locator.get_attribute("aria-checked")
                new_state_is_checked = new_state_str == "true"

                if new_state_is_checked == should_be_checked:
                    self.logger.info(
                        f"[{self.req_id}] ✅ 'Thinking Budget' 开关已成功{action}。新状态: {new_state_str}"
                    )
                else:
                    self.logger.warning(
                        f"[{self.req_id}] ⚠️ 'Thinking Budget' 开关{action}后验证失败。期望状态: '{should_be_checked}', 实际状态: '{new_state_str}'"
                    )
            else:
                self.logger.info(f"[{self.req_id}] 'Thinking Budget' 开关已处于期望状态，无需操作。")

        except Exception as e:
            self.logger.error(
                f"[{self.req_id}] ❌ 操作 'Thinking Budget toggle' 开关时发生错误: {e}"
            )
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _adjust_temperature(
        self,
        temperature: float,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """调整温度参数。"""
        async with params_cache_lock:
            self.logger.info(f"[{self.req_id}] 检查并调整温度设置...")
            clamped_temp = max(0.0, min(2.0, temperature))
            if clamped_temp != temperature:
                self.logger.warning(
                    f"[{self.req_id}] 请求的温度 {temperature} 超出范围 [0, 2]，已调整为 {clamped_temp}"
                )

            cached_temp = page_params_cache.get("temperature")
            if cached_temp is not None and abs(cached_temp - clamped_temp) < 0.001:
                self.logger.info(
                    f"[{self.req_id}] 温度 ({clamped_temp}) 与缓存值 ({cached_temp}) 一致。跳过页面交互。"
                )
                return

            self.logger.info(
                f"[{self.req_id}] 请求温度 ({clamped_temp}) 与缓存值 ({cached_temp}) 不一致或缓存中无值。需要与页面交互。"
            )
            temp_input_locator = self.page.locator(TEMPERATURE_INPUT_SELECTOR)

            try:
                await expect_async(temp_input_locator).to_be_visible(timeout=5000)
                await self._check_disconnect(check_client_disconnected, "温度调整 - 输入框可见后")

                current_temp_str = await temp_input_locator.input_value(timeout=3000)
                await self._check_disconnect(
                    check_client_disconnected, "温度调整 - 读取输入框值后"
                )

                current_temp_float = float(current_temp_str)
                self.logger.info(
                    f"[{self.req_id}] 页面当前温度: {current_temp_float}, 请求调整后温度: {clamped_temp}"
                )

                if abs(current_temp_float - clamped_temp) < 0.001:
                    self.logger.info(
                        f"[{self.req_id}] 页面当前温度 ({current_temp_float}) 与请求温度 ({clamped_temp}) 一致。更新缓存并跳过写入。"
                    )
                    page_params_cache["temperature"] = current_temp_float
                else:
                    self.logger.info(
                        f"[{self.req_id}] 页面温度 ({current_temp_float}) 与请求温度 ({clamped_temp}) 不同，正在更新..."
                    )
                    await temp_input_locator.fill(str(clamped_temp), timeout=5000)
                    await self._check_disconnect(
                        check_client_disconnected, "温度调整 - 填充输入框后"
                    )

                    await asyncio.sleep(0.1)
                    new_temp_str = await temp_input_locator.input_value(timeout=3000)
                    new_temp_float = float(new_temp_str)

                    if abs(new_temp_float - clamped_temp) < 0.001:
                        self.logger.info(
                            f"[{self.req_id}] ✅ 温度已成功更新为: {new_temp_float}。更新缓存。"
                        )
                        page_params_cache["temperature"] = new_temp_float
                    else:
                        self.logger.warning(
                            f"[{self.req_id}] ⚠️ 温度更新后验证失败。页面显示: {new_temp_float}, 期望: {clamped_temp}。清除缓存中的温度。"
                        )
                        page_params_cache.pop("temperature", None)
                        await save_error_snapshot(
                            f"temperature_verify_fail_{self.req_id}"
                        )

            except ValueError as ve:
                self.logger.error(f"[{self.req_id}] 转换温度值为浮点数时出错. 错误: {ve}。清除缓存中的温度。")
                page_params_cache.pop("temperature", None)
                await save_error_snapshot(f"temperature_value_error_{self.req_id}")
            except Exception as pw_err:
                self.logger.error(f"[{self.req_id}] ❌ 操作温度输入框时发生错误: {pw_err}。清除缓存中的温度。")
                page_params_cache.pop("temperature", None)
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
            self.logger.info(f"[{self.req_id}] 检查并调整最大输出 Token 设置...")
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
                                f"[{self.req_id}] 模型 {model_id_to_use} supported_max_output_tokens 无效: {supported_tokens}"
                            )
                    except (ValueError, TypeError):
                        self.logger.warning(
                            f"[{self.req_id}] 模型 {model_id_to_use} supported_max_output_tokens 解析失败"
                        )

            clamped_max_tokens = max(
                min_val_for_tokens, min(max_val_for_tokens_from_model, max_tokens)
            )
            if clamped_max_tokens != max_tokens:
                self.logger.warning(
                    f"[{self.req_id}] 请求的最大输出 Tokens {max_tokens} 超出模型范围，已调整为 {clamped_max_tokens}"
                )

            cached_max_tokens = page_params_cache.get("max_output_tokens")
            if (
                cached_max_tokens is not None
                and cached_max_tokens == clamped_max_tokens
            ):
                self.logger.info(
                    f"[{self.req_id}] 最大输出 Tokens ({clamped_max_tokens}) 与缓存值一致。跳过页面交互。"
                )
                return

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

                if current_max_tokens_int == clamped_max_tokens:
                    self.logger.info(
                        f"[{self.req_id}] 页面当前最大输出 Tokens ({current_max_tokens_int}) 与请求值 ({clamped_max_tokens}) 一致。更新缓存并跳过写入。"
                    )
                    page_params_cache["max_output_tokens"] = current_max_tokens_int
                else:
                    self.logger.info(
                        f"[{self.req_id}] 页面最大输出 Tokens ({current_max_tokens_int}) 与请求值 ({clamped_max_tokens}) 不同，正在更新..."
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
                        self.logger.info(
                            f"[{self.req_id}] ✅ 最大输出 Tokens 已成功更新为: {new_max_tokens_int}"
                        )
                        page_params_cache["max_output_tokens"] = new_max_tokens_int
                    else:
                        self.logger.warning(
                            f"[{self.req_id}] ⚠️ 最大输出 Tokens 更新后验证失败。页面显示: {new_max_tokens_int}, 期望: {clamped_max_tokens}。清除缓存。"
                        )
                        page_params_cache.pop("max_output_tokens", None)
                        await save_error_snapshot(
                            f"max_tokens_verify_fail_{self.req_id}"
                        )

            except (ValueError, TypeError) as ve:
                self.logger.error(f"[{self.req_id}] 转换最大输出 Tokens 值时出错: {ve}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                await save_error_snapshot(f"max_tokens_value_error_{self.req_id}")
            except Exception as e:
                self.logger.error(f"[{self.req_id}] ❌ 调整最大输出 Tokens 时出错: {e}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                await save_error_snapshot(f"max_tokens_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _adjust_stop_sequences(
        self,
        stop_sequences,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """调整停止序列参数。"""
        async with params_cache_lock:
            self.logger.info(f"[{self.req_id}] 检查并设置停止序列...")

            # 处理不同类型的stop_sequences输入
            normalized_requested_stops = set()
            if stop_sequences is not None:
                if isinstance(stop_sequences, str):
                    # 单个字符串
                    if stop_sequences.strip():
                        normalized_requested_stops.add(stop_sequences.strip())
                elif isinstance(stop_sequences, list):
                    # 字符串列表
                    for s in stop_sequences:
                        if isinstance(s, str) and s.strip():
                            normalized_requested_stops.add(s.strip())

            cached_stops_set = page_params_cache.get("stop_sequences")

            if (
                cached_stops_set is not None
                and cached_stops_set == normalized_requested_stops
            ):
                self.logger.info(f"[{self.req_id}] 请求的停止序列与缓存值一致。跳过页面交互。")
                return

            stop_input_locator = self.page.locator(STOP_SEQUENCE_INPUT_SELECTOR)
            remove_chip_buttons_locator = self.page.locator(
                MAT_CHIP_REMOVE_BUTTON_SELECTOR
            )

            try:
                # 清空已有的停止序列
                initial_chip_count = await remove_chip_buttons_locator.count()
                removed_count = 0
                max_removals = initial_chip_count + 5

                while (
                    await remove_chip_buttons_locator.count() > 0
                    and removed_count < max_removals
                ):
                    await self._check_disconnect(
                        check_client_disconnected, "停止序列清除 - 循环开始"
                    )
                    try:
                        await remove_chip_buttons_locator.first.click(timeout=2000)
                        removed_count += 1
                        await asyncio.sleep(0.15)
                    except Exception:
                        break

                # 添加新的停止序列
                if normalized_requested_stops:
                    await expect_async(stop_input_locator).to_be_visible(timeout=5000)
                    for seq in normalized_requested_stops:
                        await stop_input_locator.fill(seq, timeout=3000)
                        await stop_input_locator.press("Enter", timeout=3000)
                        await asyncio.sleep(0.2)

                page_params_cache["stop_sequences"] = normalized_requested_stops
                self.logger.info(f"[{self.req_id}] ✅ 停止序列已成功设置。缓存已更新。")

            except Exception as e:
                self.logger.error(f"[{self.req_id}] ❌ 设置停止序列时出错: {e}")
                page_params_cache.pop("stop_sequences", None)
                await save_error_snapshot(f"stop_sequence_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _adjust_top_p(self, top_p: float, check_client_disconnected: Callable):
        """调整Top P参数。"""
        self.logger.info(f"[{self.req_id}] 检查并调整 Top P 设置...")
        clamped_top_p = max(0.0, min(1.0, top_p))

        if abs(clamped_top_p - top_p) > 1e-9:
            self.logger.warning(
                f"[{self.req_id}] 请求的 Top P {top_p} 超出范围 [0, 1]，已调整为 {clamped_top_p}"
            )

        top_p_input_locator = self.page.locator(TOP_P_INPUT_SELECTOR)
        try:
            await expect_async(top_p_input_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "Top P 调整 - 输入框可见后")

            current_top_p_str = await top_p_input_locator.input_value(timeout=3000)
            current_top_p_float = float(current_top_p_str)

            if abs(current_top_p_float - clamped_top_p) > 1e-9:
                self.logger.info(
                    f"[{self.req_id}] 页面 Top P ({current_top_p_float}) 与请求值 ({clamped_top_p}) 不同，正在更新..."
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
                    self.logger.info(
                        f"[{self.req_id}] ✅ Top P 已成功更新为: {new_top_p_float}"
                    )
                else:
                    self.logger.warning(
                        f"[{self.req_id}] ⚠️ Top P 更新后验证失败。页面显示: {new_top_p_float}, 期望: {clamped_top_p}"
                    )
                    await save_error_snapshot(f"top_p_verify_fail_{self.req_id}")
            else:
                self.logger.info(
                    f"[{self.req_id}] 页面 Top P ({current_top_p_float}) 与请求值 ({clamped_top_p}) 一致，无需更改"
                )

        except (ValueError, TypeError) as ve:
            self.logger.error(f"[{self.req_id}] 转换 Top P 值时出错: {ve}")
            await save_error_snapshot(f"top_p_value_error_{self.req_id}")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 调整 Top P 时出错: {e}")
            await save_error_snapshot(f"top_p_error_{self.req_id}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def clear_chat_history(self, check_client_disconnected: Callable):
        """清空聊天记录。"""
        self.logger.info(f"[{self.req_id}] 开始清空聊天记录...")
        await self._check_disconnect(check_client_disconnected, "Start Clear Chat")

        try:
            # 一般是使用流式代理时遇到,流式输出已结束,但页面上AI仍回复个不停,此时会锁住清空按钮,但页面仍是/new_chat,而跳过后续清空操作
            # 导致后续请求无法发出而卡住,故先检查并点击发送按钮(此时是停止功能)
            submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            try:
                self.logger.info(f"[{self.req_id}] 尝试检查发送按钮状态...")
                # 使用较短的超时时间，避免长时间阻塞
                await expect_async(submit_button_locator).to_be_enabled(timeout=1000)
                self.logger.info(f"[{self.req_id}] 发送按钮可用，尝试点击并等待1秒...")
                await submit_button_locator.click(timeout=CLICK_TIMEOUT_MS)
                
                # 尝试等待它变成禁用（表示点击生效），但也允许它不变成禁用
                try:
                    await expect_async(submit_button_locator).to_be_disabled(
                        timeout=1200
                    )
                except Exception:
                    pass
                self.logger.info(f"[{self.req_id}] 发送按钮点击完成（尝试停止生成）。")
            except Exception:
                # 如果发送按钮不可用、超时或发生Playwright相关错误，这是符合预期的，直接忽略
                pass

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
                self.logger.info(f'[{self.req_id}] "清空聊天"按钮可用，继续清空流程。')
            except Exception as e_enable:
                is_new_chat_url = "/prompts/new_chat" in self.page.url.rstrip("/")
                if is_new_chat_url:
                    self.logger.info(
                        f'[{self.req_id}] "清空聊天"按钮不可用 (预期，因为在 new_chat 页面)。跳过清空操作。'
                    )
                else:
                    self.logger.warning(
                        f'[{self.req_id}] 等待"清空聊天"按钮可用失败: {e_enable}。清空操作可能无法执行。'
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
                self.logger.info(f"[{self.req_id}] 聊天已清空，重新启用 '临时聊天' 模式...")
                await enable_temporary_chat_mode(self.page)

        except ClientDisconnectedError:
            self.logger.info(f"[{self.req_id}] Client disconnected during chat history cleanup. Session reset.")
        except Exception as e_clear:
            self.logger.error(f"[{self.req_id}] 清空聊天过程中发生错误: {e_clear}")
            if not (
                isinstance(e_clear, ClientDisconnectedError)
                or (hasattr(e_clear, "name") and "Disconnect" in e_clear.name)
            ):
                await save_error_snapshot(f"clear_chat_error_{self.req_id}")
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
                self.logger.info(f'[{self.req_id}] 清空聊天确认遮罩层已可见。直接点击"继续"。')
        except TimeoutError:
            self.logger.info(f"[{self.req_id}] 清空聊天确认遮罩层初始不可见 (检查超时或未找到)。")
            overlay_initially_visible = False
        except Exception as e_vis_check:
            self.logger.warning(f"[{self.req_id}] 检查遮罩层可见性时发生错误: {e_vis_check}。假定不可见。")
            overlay_initially_visible = False

        await self._check_disconnect(check_client_disconnected, "清空聊天 - 初始遮罩层检查后")

        if overlay_initially_visible:
            self.logger.info(
                f'[{self.req_id}] 点击"继续"按钮 (遮罩层已存在): {CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR}'
            )
            await confirm_button_locator.click(timeout=CLICK_TIMEOUT_MS)
        else:
            self.logger.info(
                f'[{self.req_id}] 点击"清空聊天"按钮: {CLEAR_CHAT_BUTTON_SELECTOR}'
            )
            # 若存在透明遮罩层拦截指针事件，先尝试清理
            try:
                await self._dismiss_backdrops()
            except Exception:
                pass
            try:
                try:
                    await clear_chat_button_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                await clear_chat_button_locator.click(timeout=CLICK_TIMEOUT_MS)
            except Exception as first_click_err:
                self.logger.warning(
                    f"[{self.req_id}] 清空按钮第一次点击失败，尝试清理遮罩并强制点击: {first_click_err}"
                )
                try:
                    await self._dismiss_backdrops()
                except Exception:
                    pass
                try:
                    await clear_chat_button_locator.click(
                        timeout=CLICK_TIMEOUT_MS, force=True
                    )
                except Exception as force_click_err:
                    self.logger.error(f"[{self.req_id}] 清空按钮强制点击仍失败: {force_click_err}")
                    raise
            await self._check_disconnect(check_client_disconnected, '清空聊天 - 点击"清空聊天"后')

            try:
                self.logger.info(f"[{self.req_id}] 等待清空聊天确认遮罩层出现: {OVERLAY_SELECTOR}")
                await expect_async(overlay_locator).to_be_visible(
                    timeout=WAIT_FOR_ELEMENT_TIMEOUT_MS
                )
                self.logger.info(f"[{self.req_id}] 清空聊天确认遮罩层已出现。")
            except TimeoutError:
                error_msg = f"等待清空聊天确认遮罩层超时 (点击清空按钮后)。请求 ID: {self.req_id}"
                self.logger.error(error_msg)
                await save_error_snapshot(f"clear_chat_overlay_timeout_{self.req_id}")
                raise Exception(error_msg)

            await self._check_disconnect(check_client_disconnected, "清空聊天 - 遮罩层出现后")
            self.logger.info(
                f'[{self.req_id}] 点击"继续"按钮 (在对话框中): {CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR}'
            )
            try:
                await confirm_button_locator.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                await confirm_button_locator.click(timeout=CLICK_TIMEOUT_MS)
            except Exception as confirm_err:
                self.logger.warning(
                    f'[{self.req_id}] 首次点击"继续"失败，尝试 force 点击: {confirm_err}'
                )
                try:
                    await confirm_button_locator.click(
                        timeout=CLICK_TIMEOUT_MS, force=True
                    )
                except Exception as confirm_force_err:
                    self.logger.error(
                        f'[{self.req_id}] "继续"按钮 force 点击仍失败: {confirm_force_err}'
                    )
                    raise

        await self._check_disconnect(check_client_disconnected, '清空聊天 - 点击"继续"后')

        # 等待对话框消失
        max_retries_disappear = 3
        for attempt_disappear in range(max_retries_disappear):
            try:
                self.logger.info(
                    f"[{self.req_id}] 等待清空聊天确认按钮/对话框消失 (尝试 {attempt_disappear + 1}/{max_retries_disappear})..."
                )
                await expect_async(confirm_button_locator).to_be_hidden(
                    timeout=CLEAR_CHAT_VERIFY_TIMEOUT_MS
                )
                await expect_async(overlay_locator).to_be_hidden(timeout=1000)
                self.logger.info(f"[{self.req_id}] ✅ 清空聊天确认对话框已成功消失。")
                break
            except TimeoutError:
                self.logger.warning(
                    f"[{self.req_id}] ⚠️ 等待清空聊天确认对话框消失超时 (尝试 {attempt_disappear + 1}/{max_retries_disappear})。"
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
                self.logger.info(f"[{self.req_id}] 客户端在等待清空确认对话框消失时断开连接。")
                raise
            except Exception as other_err:
                self.logger.warning(f"[{self.req_id}] 等待清空确认对话框消失时发生其他错误: {other_err}")
                if attempt_disappear < max_retries_disappear - 1:
                    continue
                else:
                    raise

            await self._check_disconnect(
                check_client_disconnected, f"清空聊天 - 消失检查尝试 {attempt_disappear + 1} 后"
            )

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
                except Exception:
                    cnt = 0
                if cnt and cnt > 0:
                    self.logger.info(
                        f"[{self.req_id}] 检测到透明遮罩层 ({cnt})，发送 ESC 关闭 (尝试 {i+1}/3)。"
                    )
                    try:
                        await self.page.keyboard.press("Escape")
                        try:
                            await expect_async(backdrop).to_be_hidden(timeout=500)
                        except Exception:
                            pass
                    except Exception:
                        pass
                else:
                    break
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
            self.logger.info(f"[{self.req_id}] ✅ 聊天已成功清空 (验证通过 - 最后响应容器隐藏)。")
        except Exception as verify_err:
            self.logger.warning(
                f"[{self.req_id}] ⚠️ 警告: 清空聊天验证失败 (最后响应容器未隐藏): {verify_err}"
            )

    # 已移除直接设置 <input type=file> 的上传路径，统一采用菜单上传方式

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
                        self.logger.info(f"[{self.req_id}] 上传后对话框: 点击按钮 '{text}'。")
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
                        f"[{self.req_id}] 上传后对话框: 点击版权确认按钮 (aria-label 匹配)。"
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
                        self.logger.info(f"[{self.req_id}] 上传后对话框遮罩层已隐藏。")
                    except Exception:
                        self.logger.warning(f"[{self.req_id}] 上传后对话框遮罩层仍存在，后续提交可能被拦截。")
            except Exception:
                pass
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
                        f"[{self.req_id}] 已检测到已附加文件: inputs={counts.get('inputs')}, chips={counts.get('chips')}, blobs={counts.get('blobs')} (>= {expected_min})"
                    )
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        self.logger.warning(f"[{self.req_id}] 未能在超时内检测到已附加文件 (期望 >= {expected_min})")
        return False

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

            trigger = self.page.locator(
                'button[aria-label="Insert assets such as images, videos, files, or audio"]'
            )
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
                    self.logger.warning(f"[{self.req_id}] 未能显示上传菜单面板。")
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
                    self.logger.warning(f"[{self.req_id}] 未找到 'Upload File' 菜单项。")
                    return False
                btn = upload_btn.first
                await expect_async(btn).to_be_visible(timeout=2000)
                # 优先使用内部隐藏 input[type=file]
                input_loc = btn.locator('input[type="file"]')
                if await input_loc.count() > 0:
                    await input_loc.set_input_files(files_list)
                    self.logger.info(
                        f"[{self.req_id}] ✅ 通过菜单项(Upload File) 隐藏 input 设置文件成功: {len(files_list)} 个"
                    )
                else:
                    # 回退为原生文件选择器
                    async with self.page.expect_file_chooser() as fc_info:
                        await btn.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(files_list)
                    self.logger.info(
                        f"[{self.req_id}] ✅ 通过文件选择器设置文件成功: {len(files_list)} 个"
                    )
            except Exception as e_set:
                self.logger.error(f"[{self.req_id}] 设置文件失败: {e_set}")
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
            self.logger.error(f"[{self.req_id}] 通过上传菜单设置文件失败: {e}")
            return False

    async def _safe_reload_page(self):
        """
        安全地刷新页面。如果刷新超时，则关闭卡死的标签页并在同一上下文中创建一个新标签页。
        这样可以保留浏览器进程和身份验证状态（存储在上下文中）。
        """
        import server
        from .operations import _handle_model_list_response

        try:
            self.logger.info(f"[{self.req_id}] 尝试重新加载页面...")
            # 尝试标准重新加载
            await self.page.reload(timeout=30000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            self.logger.info(f"[{self.req_id}] ✅ 页面重新加载成功。")
        except TimeoutError:
            self.logger.warning(f"[{self.req_id}] ⚠️ 页面重新加载超时。正在启动优化的标签页恢复（软终止）...")
            
            try:
                # 获取当前上下文
                context = self.page.context
                
                # 1. 关闭卡死的页面
                try:
                    await self.page.close()
                    self.logger.info(f"[{self.req_id}] 卡死的标签页已关闭。")
                except Exception as close_err:
                    self.logger.warning(f"[{self.req_id}] 关闭卡死标签页时出错 (可能已关闭): {close_err}")

                # 2. 在同一上下文中创建新页面
                new_page = await context.new_page()
                self.logger.info(f"[{self.req_id}] 新标签页已创建。")

                # 3. 更新 PageController 的页面引用
                self.page = new_page
                
                # 4. 更新全局 server 状态中的页面引用
                server.page_instance = new_page
                
                # 5. 重新附加必要的事件监听器
                self.logger.info(f"[{self.req_id}] 正在重新附加模型列表响应监听器...")
                new_page.on("response", _handle_model_list_response)

                # 6. 导航到 AI Studio
                target_url = f"https://{AI_STUDIO_URL_PATTERN}prompts/new_chat"
                self.logger.info(f"[{self.req_id}] 正在导航到: {target_url}")
                await new_page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                
                self.logger.info(f"[{self.req_id}] ✅ 标签页恢复成功！已在同一上下文中加载新页面。")

            except Exception as recovery_err:
                self.logger.error(f"[{self.req_id}] ❌ 标签页恢复失败: {recovery_err}")
                raise recovery_err

    async def submit_prompt(self, prompt: str, image_list: List, check_client_disconnected: Callable):
        """提交提示到页面。包含重试和自动刷新机制，以及多种提交方式的回退。"""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"[{self.req_id}] 填充并提交提示 (尝试 {attempt + 1}/{max_retries})...")
                
                prompt_textarea_locator = self.page.locator(PROMPT_TEXTAREA_SELECTOR)
                autosize_wrapper_locator = self.page.locator('ms-prompt-input-wrapper ms-autosize-textarea')
                submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)

                # 等待输入框可见 (Timeout 10s)
                await expect_async(prompt_textarea_locator).to_be_visible(timeout=10000)
                await self._check_disconnect(check_client_disconnected, "After Input Visible")

                # 使用 JavaScript 填充文本
                await prompt_textarea_locator.evaluate(
                    '''
                    (element, text) => {
                        element.value = text;
                        element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                        element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                    }
                    ''',
                    prompt
                )
                await autosize_wrapper_locator.evaluate('(element, text) => { element.setAttribute("data-value", text); }', prompt)
                await self._check_disconnect(check_client_disconnected, "After Input Fill")

                # 上传（仅使用菜单 + 隐藏 input 设置文件；处理可能的授权弹窗）
                try:
                    self.logger.info(f"[{self.req_id}] 待上传附件数量: {len(image_list)}")
                except Exception:
                    pass
                if len(image_list) > 0:
                    ok = await self._open_upload_menu_and_choose_file(image_list)
                    if not ok:
                        self.logger.error(f"[{self.req_id}] 在上传文件时发生错误: 通过菜单方式未能设置文件")

                # 等待发送按钮启用 (Timeout reduced to 10s to detect hang early)
                wait_timeout_ms_submit_enabled = 10000
                try:
                    await self._check_disconnect(check_client_disconnected, "填充提示后等待发送按钮启用 - 前置检查")
                    await expect_async(submit_button_locator).to_be_enabled(timeout=wait_timeout_ms_submit_enabled)
                    self.logger.info(f"[{self.req_id}] ✅ 发送按钮已启用。")
                except Exception as e_pw_enabled:
                    self.logger.warning(f"[{self.req_id}] ⚠️ 等待发送按钮启用超时 (可能是页面卡顿): {e_pw_enabled}")
                    raise # Trigger retry logic

                await self._check_disconnect(check_client_disconnected, "After Submit Button Enabled")
                await asyncio.sleep(0.3)

                # 优先点击按钮提交，其次回车提交，最后组合键提交
                button_clicked = False
                try:
                    self.logger.info(f"[{self.req_id}] 尝试点击提交按钮...")
                    # 提交前再处理一次潜在对话框，避免按钮点击被拦截
                    await self._handle_post_upload_dialog()
                    await submit_button_locator.click(timeout=5000)
                    self.logger.info(f"[{self.req_id}] ✅ 提交按钮点击完成。")
                    button_clicked = True
                    
                    # Immediate Check: Call check_quota_limit() immediately after clicking.
                    await check_quota_limit(self.page, self.req_id)

                except Exception as click_err:
                    self.logger.error(f"[{self.req_id}] ❌ 提交按钮点击失败: {click_err}")
                    # Don't snapshot here, retry mechanism handles it or next methods try

                # 如果按钮点击失败，或者虽然点击了但没有触发提交（这里简化逻辑，如果点击代码跑通则认为点击成功，
                # 后续通过响应检测来判定是否真正提交。如果点击报错，则 button_clicked 为 False，进入备用方案）
                
                if not button_clicked:
                    self.logger.info(f"[{self.req_id}] 按钮提交失败，尝试回车键提交...")
                    submitted_successfully = await self._try_enter_submit(prompt_textarea_locator, check_client_disconnected)
                    if not submitted_successfully:
                        self.logger.info(f"[{self.req_id}] 回车提交失败，尝试组合键提交...")
                        combo_ok = await self._try_combo_submit(prompt_textarea_locator, check_client_disconnected)
                        if not combo_ok:
                            self.logger.error(f"[{self.req_id}] ❌ 组合键提交也失败。")
                            raise Exception("Submit failed: Button, Enter, and Combo key all failed")

                await self._check_disconnect(check_client_disconnected, "After Submit")
                
                # If we got here, success!
                return

            except Exception as e_input_submit:
                self.logger.warning(f"[{self.req_id}] 输入/提交过程发生错误 (尝试 {attempt + 1}/{max_retries}): {e_input_submit}")
                
                if isinstance(e_input_submit, ClientDisconnectedError):
                    raise # Don't retry if client disconnected

                if isinstance(e_input_submit, QuotaExceededError):
                    raise # Don't retry if quota exceeded
                
                if attempt < max_retries - 1:
                    self.logger.info(f"[{self.req_id}] ⚠️ 遇到错误，尝试刷新页面并重试...")
                    try:
                        await save_error_snapshot(f"submit_retry_before_reload_{self.req_id}_{attempt}")
                        # 使用新的安全刷新方法
                        await self._safe_reload_page()
                        await asyncio.sleep(2) # Give it a bit more time
                        self.logger.info(f"[{self.req_id}] ✅ 页面刷新/恢复完成，准备重试。")
                    except Exception as reload_err:
                        self.logger.error(f"[{self.req_id}] ❌ 页面刷新失败: {reload_err}")
                        raise e_input_submit # If reload fails, raise original or reload error
                else:
                    self.logger.error(f"[{self.req_id}] ❌ 所有重试尝试均失败。")
                    await save_error_snapshot(f"input_submit_error_final_{self.req_id}")
                    raise e_input_submit

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
                self.logger.warning(f"[{self.req_id}] 读取文件失败，跳过拖放: {path} - {e}")

        if not payloads:
            raise Exception("无可用文件用于拖放")

        candidates = [
            target_locator,
            self.page.locator("ms-prompt-input-wrapper ms-autosize-textarea textarea"),
            self.page.locator("ms-prompt-input-wrapper ms-autosize-textarea"),
            self.page.locator("ms-prompt-input-wrapper"),
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
                    f"[{self.req_id}] 拖放事件已在候选目标 {idx+1}/{len(candidates)} 上触发。"
                )
                return
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
            self.logger.info(f"[{self.req_id}] 拖放事件已在 document.body 上触发（兜底）。")
            return
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
            is_mac_determined = False

            if host_os_from_launcher == "Darwin":
                is_mac_determined = True
            elif host_os_from_launcher in ["Windows", "Linux"]:
                is_mac_determined = False
            else:
                # 使用浏览器检测
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
                # 如果无法获取原始内容，仍然尝试提交
                pass

            # 尝试回车键提交
            self.logger.info(f"[{self.req_id}] 尝试回车键提交")
            try:
                await self.page.keyboard.press("Enter")
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
                    self.logger.info(f"[{self.req_id}] 验证方法1: 输入框已清空，回车键提交成功")
                    submission_success = True

                # 方法2: 检查提交按钮状态
                if not submission_success:
                    submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                    try:
                        is_disabled = await submit_button_locator.is_disabled(
                            timeout=2000
                        )
                        if is_disabled:
                            self.logger.info(f"[{self.req_id}] 验证方法2: 提交按钮已禁用，回车键提交成功")
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
                            if await last_container.is_visible(timeout=1000):
                                self.logger.info(
                                    f"[{self.req_id}] 验证方法3: 检测到响应容器，回车键提交成功"
                                )
                                submission_success = True
                    except Exception:
                        pass
            except Exception as verify_err:
                self.logger.warning(f"[{self.req_id}] 回车键提交验证过程出错: {verify_err}")
                # 出错时假定提交成功，让后续流程继续
                submission_success = True

            if submission_success:
                self.logger.info(f"[{self.req_id}] ✅ 回车键提交成功")
                return True
            else:
                self.logger.warning(f"[{self.req_id}] ⚠️ 回车键提交验证失败")
                return False
        except Exception as shortcut_err:
            self.logger.warning(f"[{self.req_id}] 回车键提交失败: {shortcut_err}")
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

            self.logger.info(
                f"[{self.req_id}] 尝试组合键提交: {shortcut_modifier}+{shortcut_key}"
            )
            try:
                await self.page.keyboard.press(f"{shortcut_modifier}+{shortcut_key}")
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
                    self.logger.info(f"[{self.req_id}] 验证方法1: 输入框已清空，组合键提交成功")
                    submission_success = True
                if not submission_success:
                    submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
                    try:
                        is_disabled = await submit_button_locator.is_disabled(
                            timeout=2000
                        )
                        if is_disabled:
                            self.logger.info(f"[{self.req_id}] 验证方法2: 提交按钮已禁用，组合键提交成功")
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
                            if await last_container.is_visible(timeout=1000):
                                self.logger.info(
                                    f"[{self.req_id}] 验证方法3: 检测到响应容器，组合键提交成功"
                                )
                                submission_success = True
                    except Exception:
                        pass
            except Exception as verify_err:
                self.logger.warning(f"[{self.req_id}] 组合键提交验证过程出错: {verify_err}")
                submission_success = True

            if submission_success:
                self.logger.info(f"[{self.req_id}] ✅ 组合键提交成功")
                return True
            else:
                self.logger.warning(f"[{self.req_id}] ⚠️ 组合键提交验证失败")
                return False
        except Exception as combo_err:
            self.logger.warning(f"[{self.req_id}] 组合键提交失败: {combo_err}")
            return False

    async def get_response(self, check_client_disconnected: Callable, prompt_length: int, timeout: Optional[float] = None) -> str:
        """获取响应内容。"""
        self.logger.info(f"[{self.req_id}] 等待并获取响应...")

        try:
            # 等待响应容器出现
            response_container_locator = self.page.locator(
                RESPONSE_CONTAINER_SELECTOR
            ).last
            response_element_locator = response_container_locator.locator(
                RESPONSE_TEXT_SELECTOR
            )

            self.logger.info(f"[{self.req_id}] 等待响应元素附加到DOM...")
            await expect_async(response_element_locator).to_be_attached(timeout=90000)
            await self._check_disconnect(check_client_disconnected, "获取响应 - 响应元素已附加")

            # 等待响应完成
            submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            edit_button_locator = self.page.locator(EDIT_MESSAGE_BUTTON_SELECTOR)
            input_field_locator = self.page.locator(PROMPT_TEXTAREA_SELECTOR)

            self.logger.info(f"[{self.req_id}] 等待响应完成...")
            completion_detected = await _wait_for_response_completion(
                self.page,
                input_field_locator,
                submit_button_locator,
                edit_button_locator,
                self.req_id,
                check_client_disconnected,
                None,
                prompt_length=prompt_length,
                timeout=timeout
            )

            if not completion_detected:
                self.logger.warning(f"[{self.req_id}] 响应完成检测失败，尝试获取当前内容")
            else:
                self.logger.info(f"[{self.req_id}] ✅ 响应完成检测成功")

            # 获取最终响应内容
            final_content = await _get_final_response_content(
                self.page, self.req_id, check_client_disconnected
            )

            if not final_content or not final_content.strip():
                self.logger.warning(f"[{self.req_id}] ⚠️ 获取到的响应内容为空")
                await save_error_snapshot(f"empty_response_{self.req_id}")
                # 不抛出异常，返回空内容让上层处理
                return ""

            self.logger.info(f"[{self.req_id}] ✅ 成功获取响应内容 ({len(final_content)} chars)")
            return final_content

        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 获取响应时出错: {e}")
            if not isinstance(e, ClientDisconnectedError):
                await save_error_snapshot(f"get_response_error_{self.req_id}")
            raise