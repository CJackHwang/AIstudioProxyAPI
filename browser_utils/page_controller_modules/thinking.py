import asyncio
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional

from playwright.async_api import TimeoutError
from playwright.async_api import expect as expect_async

from browser_utils.operations import save_error_snapshot
from browser_utils.thinking_normalizer import (
    format_directive_log,
    normalize_reasoning_effort,
)
from config import (
    CLICK_TIMEOUT_MS,
    DEFAULT_THINKING_LEVEL_FLASH,
    DEFAULT_THINKING_LEVEL_PRO,
    ENABLE_THINKING_MODE_TOGGLE_SELECTOR,
    SET_THINKING_BUDGET_TOGGLE_SELECTOR,
    THINKING_BUDGET_INPUT_SELECTOR,
    THINKING_BUDGET_TOGGLE_OLD_ROOT_SELECTOR,
    THINKING_BUDGET_TOGGLE_PARENT_SELECTOR,
    THINKING_LEVEL_OPTION_HIGH_SELECTOR,
    THINKING_LEVEL_OPTION_LOW_SELECTOR,
    THINKING_LEVEL_OPTION_MEDIUM_SELECTOR,
    THINKING_LEVEL_OPTION_MINIMAL_SELECTOR,
    THINKING_LEVEL_SELECT_SELECTOR,
    THINKING_MODE_TOGGLE_OLD_ROOT_SELECTOR,
    THINKING_MODE_TOGGLE_PARENT_SELECTOR,
)
from models import ClientDisconnectedError

from .base import BaseController


class ThinkingCategory(Enum):
    """Model thinking capability categories."""

    NON_THINKING = auto()  # No thinking UI at all (gemini-2.0-*, gemini-1.5-*)
    THINKING_FLASH = auto()  # Toggleable thinking mode + budget (gemini-2.5-flash*)
    THINKING_PRO = auto()  # Always-on thinking, budget toggle/slider (gemini-2.5-pro*)
    THINKING_LEVEL = auto()  # 2-level dropdown only (gemini-3-pro*)
    THINKING_LEVEL_FLASH = auto()  # 4-level dropdown (gemini-3-flash*)


class ThinkingController(BaseController):
    """Handles thinking mode and budget logic."""

    async def _handle_thinking_budget(
        self,
        request_params: Dict[str, Any],
        model_id_to_use: Optional[str],
        check_client_disconnected: Callable,
    ):
        """处理思考模式和预算的调整逻辑。

        使用归一化模块将 reasoning_effort 转换为标准指令，然后根据指令控制：
        1. 主思考开关（总开关）
        2. 手动预算开关
        3. 预算值输入框
        """
        reasoning_effort = request_params.get("reasoning_effort")

        # 根据模型类别决定处理逻辑
        category = self._get_thinking_category(model_id_to_use)
        if category == ThinkingCategory.NON_THINKING:
            self.logger.debug("[Thinking] 该模型不支持思考模式，跳过配置")
            return

        directive = normalize_reasoning_effort(reasoning_effort)
        self.logger.debug(f"[Thinking] 指令: {format_directive_log(directive)}")

        uses_level = (
            category
            in (ThinkingCategory.THINKING_LEVEL, ThinkingCategory.THINKING_LEVEL_FLASH)
            and await self._has_thinking_dropdown()
        )

        def _should_enable_from_raw(rv: Any) -> bool:
            try:
                if isinstance(rv, str):
                    rs = rv.strip().lower()
                    if rs in ["high", "medium", "low", "minimal", "-1"]:
                        return True
                    if rs == "none":
                        return False
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

        # 特殊逻辑：对于使用等级的模型（Gemini 3 Pro），如果未指定 reasoning_effort，
        # 我们默认认为应该开启（或者至少应该检查并应用默认等级）
        if reasoning_effort is None and uses_level:
            desired_enabled = True

        has_main_toggle = category == ThinkingCategory.THINKING_FLASH
        if has_main_toggle:
            self.logger.info(
                f"开始设置主思考开关到: {'开启' if desired_enabled else '关闭'}"
            )
            await self._control_thinking_mode_toggle(
                should_be_enabled=desired_enabled,
                check_client_disconnected=check_client_disconnected,
            )
        else:
            self.logger.info("该模型无主思考开关，跳过开关设置。")

        if not desired_enabled:
            # 跳过无预算开关的模型 (gemini-3-pro-preview 系列使用思考等级而非预算)
            if category in (
                ThinkingCategory.THINKING_LEVEL,
                ThinkingCategory.THINKING_LEVEL_FLASH,
            ):
                return
            # Flash/Flash Lite 模型：关闭主思考开关后，预算开关会被隐藏，无需再操作
            # 这避免了尝试操作不可见元素导致的 5 秒超时
            if has_main_toggle:
                self.logger.info(
                    "Flash 模型已关闭主思考开关，跳过预算开关操作（预算开关已隐藏）"
                )
                return
            # 若关闭思考，则确保预算开关关闭（兼容旧UI）- 仅适用于非 Flash 模型（如 gemini-2.5-pro）
            await self._control_thinking_budget_toggle(
                should_be_checked=False,
                check_client_disconnected=check_client_disconnected,
            )
            return

        # 2) 已开启思考：根据模型类型设置等级或预算
        if uses_level:
            rv = reasoning_effort
            level_to_set = None
            is_flash_4_level = category == ThinkingCategory.THINKING_LEVEL_FLASH

            if isinstance(rv, str):
                rs = rv.strip().lower()
                # 直接匹配字符串等级
                if is_flash_4_level:
                    # Gemini 3 Flash: 4 levels (minimal, low, medium, high)
                    if rs in ["minimal", "low", "medium", "high"]:
                        level_to_set = rs
                    elif rs in ["none", "-1"]:
                        level_to_set = "high"
                    else:
                        try:
                            v = int(rs)
                            if v >= 16000:
                                level_to_set = "high"
                            elif v >= 8000:
                                level_to_set = "medium"
                            elif v >= 1024:
                                level_to_set = "low"
                            else:
                                level_to_set = "minimal"
                        except Exception:
                            level_to_set = None
                else:
                    # Gemini 3 Pro: 2 levels (low, high)
                    if rs == "low" or rs == "minimal":
                        level_to_set = "low"
                    elif rs in ["high", "medium", "none", "-1"]:
                        level_to_set = "high"
                    else:
                        try:
                            v = int(rs)
                            level_to_set = "high" if v >= 8000 else "low"
                        except Exception:
                            level_to_set = None
            elif isinstance(rv, int):
                if is_flash_4_level:
                    # Gemini 3 Flash: 4 levels
                    if rv >= 16000 or rv == -1:
                        level_to_set = "high"
                    elif rv >= 8000:
                        level_to_set = "medium"
                    elif rv >= 1024:
                        level_to_set = "low"
                    else:
                        level_to_set = "minimal"
                else:
                    # Gemini 3 Pro: 2 levels
                    level_to_set = "high" if rv >= 8000 or rv == -1 else "low"

            if level_to_set is None and rv is None:
                # Use model-specific default
                level_to_set = (
                    DEFAULT_THINKING_LEVEL_FLASH
                    if is_flash_4_level
                    else DEFAULT_THINKING_LEVEL_PRO
                )
                # Ensure Pro only gets valid levels (high/low)
                if not is_flash_4_level and level_to_set not in ["high", "low"]:
                    level_to_set = (
                        "high" if level_to_set in ["high", "medium"] else "low"
                    )

            if level_to_set is None:
                self.logger.info("无法解析等级，保持当前等级。")
            else:
                await self._set_thinking_level(level_to_set, check_client_disconnected)
            return

        # 降级路径：当 desired_enabled 和 directive 冲突时，信任 directive 并尝试关闭
        # 场景：raw value 说开启（如 "high"），但 directive 说关闭（如无效配置）
        if desired_enabled and not directive.thinking_enabled:
            self.logger.info("尝试关闭主思考开关...")
            success = await self._control_thinking_mode_toggle(
                should_be_enabled=False,
                check_client_disconnected=check_client_disconnected,
            )

            if not success:
                self.logger.warning("主思考开关不可用，使用降级方案：设置预算为 0")
                await self._control_thinking_budget_toggle(
                    should_be_checked=True,
                    check_client_disconnected=check_client_disconnected,
                )
                await self._set_thinking_budget_value(0, check_client_disconnected)
            return

        # 场景2和3: 开启思考模式
        # 仅在模型无主思考开关时才需要在此设置（有主思考开关的模型已在前面设置）
        if not has_main_toggle:
            self.logger.info("开启主思考开关...")
            await self._control_thinking_mode_toggle(
                should_be_enabled=True,
                check_client_disconnected=check_client_disconnected,
            )

        # 场景2: 开启思考，不限制预算
        if not directive.budget_enabled:
            self.logger.info("关闭手动预算限制...")
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
            self.logger.info(f"开启手动预算限制并设置预算值: {value_to_set} tokens")
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
            except asyncio.CancelledError:
                raise
            except Exception:
                return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    def _get_thinking_category(self, model_id: Optional[str]) -> ThinkingCategory:
        """Return thinking category based on model ID.

        Categories:
        - NON_THINKING: No thinking UI (gemini-2.0-*, gemini-1.5-*)
        - THINKING_FLASH: Toggleable thinking mode + budget (gemini-2.5-flash*, gemini-flash-latest)
        - THINKING_PRO: Always-on thinking, budget configurable (gemini-2.5-pro*)
        - THINKING_LEVEL: 2-level dropdown (gemini-3-pro*)
        - THINKING_LEVEL_FLASH: 4-level dropdown (gemini-3-flash*)
        """
        if not model_id:
            return ThinkingCategory.NON_THINKING

        mid = model_id.lower()

        if "gemini-3" in mid and "flash" in mid:
            return ThinkingCategory.THINKING_LEVEL_FLASH

        if "gemini-3" in mid and "pro" in mid:
            return ThinkingCategory.THINKING_LEVEL

        if "gemini-2.5-pro" in mid:
            return ThinkingCategory.THINKING_PRO

        if "gemini-2.5-flash" in mid:
            return ThinkingCategory.THINKING_FLASH

        # gemini-flash-latest and gemini-flash-lite-latest behave like 2.5 flash
        if mid == "gemini-flash-latest" or mid == "gemini-flash-lite-latest":
            return ThinkingCategory.THINKING_FLASH

        return ThinkingCategory.NON_THINKING

    async def _set_thinking_level(
        self, level: str, check_client_disconnected: Callable
    ):
        """Set thinking level in the dropdown.

        Supports: high, medium, low, minimal
        (Gemini 3 Pro only supports high/low, Flash supports all 4)
        """
        level_lower = level.lower()
        if level_lower == "high":
            target_option_selector = THINKING_LEVEL_OPTION_HIGH_SELECTOR
        elif level_lower == "medium":
            target_option_selector = THINKING_LEVEL_OPTION_MEDIUM_SELECTOR
        elif level_lower == "low":
            target_option_selector = THINKING_LEVEL_OPTION_LOW_SELECTOR
        elif level_lower == "minimal":
            target_option_selector = THINKING_LEVEL_OPTION_MINIMAL_SELECTOR
        else:
            # Fallback to high for unknown levels
            target_option_selector = THINKING_LEVEL_OPTION_HIGH_SELECTOR
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
            except asyncio.CancelledError:
                raise
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
                self.logger.info(f"已设置 Thinking Level 为 {level}")
            else:
                self.logger.warning(
                    f"Thinking Level 验证失败，页面值: {value_text}, 期望: {level}"
                )
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"设置 Thinking Level 时出错: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _set_thinking_budget_value(
        self, token_budget: int, check_client_disconnected: Callable
    ):
        """设置思考预算的具体数值。

        参数:
            token_budget: 预算token数量（由归一化模块计算得出）
            check_client_disconnected: 客户端断连检查回调
        """
        self.logger.info(f"设置思考预算值: {token_budget} tokens")

        budget_input_locator = self.page.locator(THINKING_BUDGET_INPUT_SELECTOR)

        try:
            await expect_async(budget_input_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "思考预算调整 - 输入框可见后"
            )

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
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            self.logger.info(f"设置思考预算为: {adjusted_budget}")
            await budget_input_locator.fill(str(adjusted_budget), timeout=5000)
            await self._check_disconnect(
                check_client_disconnected, "思考预算调整 - 填充输入框后"
            )

            # 验证
            try:
                await expect_async(budget_input_locator).to_have_value(
                    str(adjusted_budget), timeout=3000
                )
                self.logger.info(f"思考预算已成功更新为: {adjusted_budget}")
            except Exception:
                new_value_str = await budget_input_locator.input_value(timeout=3000)
                try:
                    new_value_int = int(new_value_str)
                except Exception:
                    new_value_int = -1
                if new_value_int == adjusted_budget:
                    self.logger.info(f"思考预算已成功更新为: {new_value_str}")
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
                            f"页面最大预算为 {page_max_val}，请求的预算 {adjusted_budget} 已调整为 {page_max_val}"
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
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass
                        await budget_input_locator.fill(str(page_max_val), timeout=5000)
                        try:
                            await expect_async(budget_input_locator).to_have_value(
                                str(page_max_val), timeout=2000
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass
                    else:
                        self.logger.warning(
                            f"思考预算更新后验证失败。页面显示: {new_value_str}, 期望: {adjusted_budget}"
                        )

        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"调整思考预算时出错: {e}")
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
        toggle_selector = ENABLE_THINKING_MODE_TOGGLE_SELECTOR
        self.logger.info(
            f"控制主思考开关，期望状态: {'开启' if should_be_enabled else '关闭'}..."
        )

        try:
            toggle_locator = self.page.locator(toggle_selector)

            # First check if element exists at all (for non-thinking models like gemini-2.0-flash)
            element_count = await toggle_locator.count()
            if element_count == 0:
                if not should_be_enabled:
                    # Trying to disable on a model without thinking toggle - just skip
                    self.logger.info(
                        "主思考开关不存在（当前模型不支持思考模式），无需关闭。"
                    )
                    return True
                else:
                    # User wants to enable but toggle doesn't exist
                    self.logger.warning(
                        "主思考开关不存在（当前模型可能不支持思考模式），无法开启。"
                    )
                    return False

            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            try:
                await toggle_locator.scroll_into_view_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await self._check_disconnect(
                check_client_disconnected, "主思考开关 - 元素可见后"
            )

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            current_state_is_enabled = is_checked_str == "true"
            self.logger.info(
                f"主思考开关当前状态: {is_checked_str} (是否开启: {current_state_is_enabled})"
            )

            if current_state_is_enabled != should_be_enabled:
                action = "开启" if should_be_enabled else "关闭"
                self.logger.info(f"主思考开关需要切换，正在点击以{action}思考模式...")

                try:
                    await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    try:
                        # 新版UI: 尝试直接点击带 aria-label 的开关父容器
                        alt_toggle = self.page.locator(
                            THINKING_MODE_TOGGLE_PARENT_SELECTOR
                        )
                        if await alt_toggle.count() > 0:
                            await alt_toggle.click(timeout=CLICK_TIMEOUT_MS)
                        else:
                            # 旧版UI回退: data-test-toggle
                            root = self.page.locator(
                                THINKING_MODE_TOGGLE_OLD_ROOT_SELECTOR
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
                        f"主思考开关已成功{action}。新状态: {new_state_str}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"主思考开关{action}后验证失败。期望: {should_be_enabled}, 实际: {new_state_str}"
                    )
                    return False
            else:
                self.logger.info("主思考开关已处于期望状态，无需操作。")
                return True

        except TimeoutError:
            self.logger.warning(
                "主思考开关元素未找到或不可见（当前模型可能不支持思考模式）"
            )
            return False
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"操作主思考开关时发生错误: {e}")
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
            f"控制 'Thinking Budget' 开关，期望状态: {'选中' if should_be_checked else '未选中'}..."
        )

        try:
            toggle_locator = self.page.locator(toggle_selector)

            # First check if element exists at all (for non-thinking models)
            element_count = await toggle_locator.count()
            if element_count == 0:
                if not should_be_checked:
                    # Trying to disable on a model without budget toggle - just skip
                    self.logger.info("思考预算开关不存在（当前模型不支持），无需禁用。")
                    return
                else:
                    # User wants to enable but toggle doesn't exist
                    self.logger.warning(
                        "思考预算开关不存在（当前模型可能不支持），无法启用。"
                    )
                    return

            await expect_async(toggle_locator).to_be_visible(timeout=5000)
            try:
                await toggle_locator.scroll_into_view_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await self._check_disconnect(
                check_client_disconnected, "思考预算开关 - 元素可见后"
            )

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            current_state_is_checked = is_checked_str == "true"
            self.logger.info(
                f"思考预算开关当前 'aria-checked' 状态: {is_checked_str} (当前是否选中: {current_state_is_checked})"
            )

            if current_state_is_checked != should_be_checked:
                action = "启用" if should_be_checked else "禁用"
                self.logger.info(
                    f"思考预算开关当前状态与期望不符，正在点击以{action}..."
                )
                try:
                    await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    try:
                        # 新版UI: 尝试直接点击带 aria-label 的开关父容器
                        alt_toggle = self.page.locator(
                            THINKING_BUDGET_TOGGLE_PARENT_SELECTOR
                        )
                        if await alt_toggle.count() > 0:
                            await alt_toggle.click(timeout=CLICK_TIMEOUT_MS)
                        else:
                            # 旧版UI回退: data-test-toggle
                            root = self.page.locator(
                                THINKING_BUDGET_TOGGLE_OLD_ROOT_SELECTOR
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
                        f"'Thinking Budget' 开关已成功{action}。新状态: {new_state_str}"
                    )
                else:
                    self.logger.warning(
                        f"'Thinking Budget' 开关{action}后验证失败。期望状态: '{should_be_checked}', 实际状态: '{new_state_str}'"
                    )
            else:
                self.logger.info("'Thinking Budget' 开关已处于期望状态，无需操作。")

        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            self.logger.error(f"操作 'Thinking Budget toggle' 开关时发生错误: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
