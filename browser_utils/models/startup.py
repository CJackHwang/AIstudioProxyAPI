"""
Model State Initialization and Synchronization
"""

import asyncio
import json
import logging

from playwright.async_api import Page as AsyncPage
from playwright.async_api import expect as expect_async

from config import INPUT_SELECTOR, MODEL_NAME_SELECTOR

from .ui_state import _verify_and_apply_ui_state, _verify_ui_state_settings

logger = logging.getLogger("AIStudioProxyServer")


async def _handle_initial_model_state_and_storage(page: AsyncPage):
    """处理初始模型状态和存储"""
    from api_utils.server_state import state

    getattr(state, "current_ai_studio_model_id", None)
    getattr(state, "parsed_model_list", [])
    getattr(state, "model_list_fetch_event", None)

    logger.debug("[Init] 处理初始模型状态和 localStorage...")
    needs_reload_and_storage_update = False
    reason_for_reload = ""

    try:
        initial_prefs_str = await page.evaluate(
            "() => localStorage.getItem('aiStudioUserPreference')"
        )
        if not initial_prefs_str:
            needs_reload_and_storage_update = True
            reason_for_reload = "localStorage 未找到"
        else:
            try:
                pref_obj = json.loads(initial_prefs_str)
                prompt_model_path = pref_obj.get("promptModel")
                pref_obj.get("isAdvancedOpen")
                is_prompt_model_valid = (
                    isinstance(prompt_model_path, str) and prompt_model_path.strip()
                )

                if not is_prompt_model_valid:
                    needs_reload_and_storage_update = True
                    reason_for_reload = "promptModel 无效"
                else:
                    # 使用新的UI状态验证功能
                    ui_state = await _verify_ui_state_settings(page, "initial")
                    if ui_state["needsUpdate"]:
                        needs_reload_and_storage_update = True
                        reason_for_reload = "UI状态不匹配"
                    else:
                        state.current_ai_studio_model_id = prompt_model_path.split("/")[
                            -1
                        ]
                        logger.debug(
                            f"localStorage 有效且UI状态正确。初始模型 ID 从 localStorage 设置为: {state.current_ai_studio_model_id}"
                        )
            except json.JSONDecodeError:
                needs_reload_and_storage_update = True
                reason_for_reload = (
                    "解析 localStorage.aiStudioUserPreference JSON 失败。"
                )
                logger.error(f"判定需要刷新和存储更新: {reason_for_reload}")

        if needs_reload_and_storage_update:
            logger.debug(f"[State] 需要刷新: {reason_for_reload}")
            await _set_model_from_page_display(page, set_storage=True)

            current_page_url = page.url
            logger.info("[UI操作] 正在重新加载页面以应用设置...")
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.debug(
                        f"尝试重新加载页面 (第 {attempt + 1}/{max_retries} 次): {current_page_url}"
                    )
                    await page.goto(
                        current_page_url, wait_until="domcontentloaded", timeout=40000
                    )
                    await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                        timeout=30000
                    )
                    logger.debug(f"页面已成功重新加载到: {page.url}")

                    # 页面重新加载后验证UI状态
                    logger.debug("[State] 验证 UI 状态...")
                    reload_ui_state_success = await _verify_and_apply_ui_state(
                        page, "reload"
                    )
                    if reload_ui_state_success:
                        logger.info("[UI检查] 页面重载后验证通过")
                    else:
                        logger.warning("重新加载后UI状态验证失败")

                    break  # 成功则跳出循环
                except asyncio.CancelledError:
                    raise
                except Exception as reload_err:
                    logger.warning(
                        f"页面重新加载尝试 {attempt + 1}/{max_retries} 失败: {reload_err}"
                    )
                    if attempt < max_retries - 1:
                        logger.debug("[Init] 5秒后重试...")
                        await asyncio.sleep(5)
                    else:
                        logger.error(
                            f"页面重新加载在 {max_retries} 次尝试后最终失败: {reload_err}. 后续模型状态可能不准确。",
                            exc_info=True,
                        )
                        from browser_utils.operations import save_error_snapshot

                        await save_error_snapshot(
                            f"initial_storage_reload_fail_attempt_{attempt + 1}"
                        )

            logger.debug("[State] 重载后同步模型 ID")
            await _set_model_from_page_display(page, set_storage=False)
            logger.debug(f"[State] 完成，当前模型: {state.current_ai_studio_model_id}")
        else:
            logger.debug("[State] localStorage 状态正常，无需刷新")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(
            f"(新) 处理初始模型状态和 localStorage 时发生严重错误: {e}",
            exc_info=True,
        )
        try:
            logger.warning(
                "由于发生错误，尝试回退仅从页面显示设置全局模型 ID (不写入localStorage)..."
            )
            await _set_model_from_page_display(page, set_storage=False)
        except asyncio.CancelledError:
            raise
        except Exception as fallback_err:
            logger.error(f"回退设置模型ID也失败: {fallback_err}")


async def _set_model_from_page_display(page: AsyncPage, set_storage: bool = False):
    """从页面显示设置模型"""
    from api_utils.server_state import state

    getattr(state, "current_ai_studio_model_id", None)
    getattr(state, "parsed_model_list", [])
    model_list_fetch_event = getattr(state, "model_list_fetch_event", None)

    try:
        logger.debug("[Model] 从页面显示读取当前模型...")
        model_name_locator = page.locator(MODEL_NAME_SELECTOR)
        displayed_model_name_from_page_raw = await model_name_locator.first.inner_text(
            timeout=7000
        )
        displayed_model_name = displayed_model_name_from_page_raw.strip()
        logger.debug(f"[Model] 页面显示: '{displayed_model_name}'")

        found_model_id_from_display = None
        if model_list_fetch_event and not model_list_fetch_event.is_set():
            logger.debug("[Model] 等待模型列表数据 (最多 5 秒)...")
            try:
                await asyncio.wait_for(model_list_fetch_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("等待模型列表超时，可能无法准确转换显示名称为ID。")

        found_model_id_from_display = displayed_model_name

        new_model_value = found_model_id_from_display
        if state.current_ai_studio_model_id != new_model_value:
            state.current_ai_studio_model_id = new_model_value
            logger.debug(f"[Model] 全局 ID 已更新: {new_model_value}")
        # No log needed if unchanged

        if set_storage:
            logger.debug("[State] 准备更新 localStorage")
            existing_prefs_for_update_str = await page.evaluate(
                "() => localStorage.getItem('aiStudioUserPreference')"
            )
            prefs_to_set = {}
            if existing_prefs_for_update_str:
                try:
                    prefs_to_set = json.loads(existing_prefs_for_update_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "解析现有 localStorage.aiStudioUserPreference 失败，将创建新的偏好设置。"
                    )

            # 使用新的强制设置功能
            logger.debug("[State] 应用强制 UI 状态设置...")
            ui_state_success = await _verify_and_apply_ui_state(page, "set_model")
            if not ui_state_success:
                logger.warning("UI状态设置失败，使用传统方法")
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            else:
                # 确保prefs_to_set也包含正确的设置
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            logger.debug("[State] 已设置: isAdvancedOpen=true, areToolsOpen=true")

            if found_model_id_from_display:
                new_prompt_model_path = f"models/{found_model_id_from_display}"
                prefs_to_set["promptModel"] = new_prompt_model_path
            elif "promptModel" not in prefs_to_set:
                logger.warning(
                    f"无法从页面显示 '{displayed_model_name}' 找到模型ID，且 localStorage 中无现有 promptModel。promptModel 将不会被主动设置以避免潜在问题。"
                )

            default_keys_if_missing = {
                "bidiModel": "models/gemini-1.0-pro-001",
                "isSafetySettingsOpen": False,
                "hasShownSearchGroundingTos": False,
                "autosaveEnabled": True,
                "theme": "system",
                "bidiOutputFormat": 3,
                "isSystemInstructionsOpen": False,
                "warmWelcomeDisplayed": True,
                "getCodeLanguage": "Node.js",
                "getCodeHistoryToggle": False,
                "fileCopyrightAcknowledged": True,
            }
            for key, val_default in default_keys_if_missing.items():
                if key not in prefs_to_set:
                    prefs_to_set[key] = val_default

            await page.evaluate(
                "(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)",
                json.dumps(prefs_to_set),
            )
            logger.debug(
                f"[State] localStorage 已更新 (model: {prefs_to_set.get('promptModel', 'N/A')})"
            )
    except asyncio.CancelledError:
        raise
    except Exception as e_set_disp:
        logger.error(f"尝试从页面显示设置模型时出错: {e_set_disp}", exc_info=True)
