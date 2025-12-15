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

    logger.info("--- (新) 处理初始模型状态, localStorage 和 isAdvancedOpen ---")
    needs_reload_and_storage_update = False
    reason_for_reload = ""

    try:
        initial_prefs_str = await page.evaluate(
            "() => localStorage.getItem('aiStudioUserPreference')"
        )
        if not initial_prefs_str:
            needs_reload_and_storage_update = True
            reason_for_reload = "localStorage.aiStudioUserPreference 未找到。"
            logger.info(f"判定需要刷新和存储更新: {reason_for_reload}")
        else:
            logger.info("localStorage 中找到 'aiStudioUserPreference'。正在解析...")
            try:
                pref_obj = json.loads(initial_prefs_str)
                prompt_model_path = pref_obj.get("promptModel")
                pref_obj.get("isAdvancedOpen")
                is_prompt_model_valid = (
                    isinstance(prompt_model_path, str) and prompt_model_path.strip()
                )

                if not is_prompt_model_valid:
                    needs_reload_and_storage_update = True
                    reason_for_reload = "localStorage.promptModel 无效或未设置。"
                    logger.info(f"判定需要刷新和存储更新: {reason_for_reload}")
                else:
                    # 使用新的UI状态验证功能
                    ui_state = await _verify_ui_state_settings(page, "initial")
                    if ui_state["needsUpdate"]:
                        needs_reload_and_storage_update = True
                        reason_for_reload = f"UI状态需要更新: isAdvancedOpen={ui_state['isAdvancedOpen']}, areToolsOpen={ui_state['areToolsOpen']} (期望: True)"
                        logger.info(f"判定需要刷新和存储更新: {reason_for_reload}")
                    else:
                        state.current_ai_studio_model_id = prompt_model_path.split("/")[
                            -1
                        ]
                        logger.info(
                            f"   localStorage 有效且UI状态正确。初始模型 ID 从 localStorage 设置为: {state.current_ai_studio_model_id}"
                        )
            except json.JSONDecodeError:
                needs_reload_and_storage_update = True
                reason_for_reload = (
                    "解析 localStorage.aiStudioUserPreference JSON 失败。"
                )
                logger.error(f"判定需要刷新和存储更新: {reason_for_reload}")

        if needs_reload_and_storage_update:
            logger.info(f"执行刷新和存储更新流程，原因: {reason_for_reload}")
            logger.info(
                "   步骤 1: 调用 _set_model_from_page_display(set_storage=True) 更新 localStorage 和全局模型 ID..."
            )
            await _set_model_from_page_display(page, set_storage=True)

            current_page_url = page.url
            logger.info(
                f"   步骤 2: 重新加载页面 ({current_page_url}) 以应用 isAdvancedOpen=true..."
            )
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(
                        f"   尝试重新加载页面 (第 {attempt + 1}/{max_retries} 次): {current_page_url}"
                    )
                    await page.goto(
                        current_page_url, wait_until="domcontentloaded", timeout=40000
                    )
                    await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                        timeout=30000
                    )
                    logger.info(f"页面已成功重新加载到: {page.url}")

                    # 页面重新加载后验证UI状态
                    logger.info("页面重新加载完成，验证UI状态设置...")
                    reload_ui_state_success = await _verify_and_apply_ui_state(
                        page, "reload"
                    )
                    if reload_ui_state_success:
                        logger.info("重新加载后UI状态验证成功")
                    else:
                        logger.warning("重新加载后UI状态验证失败")

                    break  # 成功则跳出循环
                except asyncio.CancelledError:
                    raise
                except Exception as reload_err:
                    logger.warning(
                        f"   页面重新加载尝试 {attempt + 1}/{max_retries} 失败: {reload_err}"
                    )
                    if attempt < max_retries - 1:
                        logger.info("将在5秒后重试...")
                        await asyncio.sleep(5)
                    else:
                        logger.error(
                            f"   页面重新加载在 {max_retries} 次尝试后最终失败: {reload_err}. 后续模型状态可能不准确。",
                            exc_info=True,
                        )
                        from browser_utils.operations import save_error_snapshot

                        await save_error_snapshot(
                            f"initial_storage_reload_fail_attempt_{attempt + 1}"
                        )

            logger.info(
                "   步骤 3: 重新加载后，再次调用 _set_model_from_page_display(set_storage=False) 以同步全局模型 ID..."
            )
            await _set_model_from_page_display(page, set_storage=False)
            logger.info(
                f"   刷新和存储更新流程完成。最终全局模型 ID: {state.current_ai_studio_model_id}"
            )
        else:
            logger.info(
                "   localStorage 状态良好 (isAdvancedOpen=true, promptModel有效)，无需刷新页面。"
            )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(
            f"(新) 处理初始模型状态和 localStorage 时发生严重错误: {e}",
            exc_info=True,
        )
        try:
            logger.warning(
                "   由于发生错误，尝试回退仅从页面显示设置全局模型 ID (不写入localStorage)..."
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
        logger.info("尝试从页面显示元素读取当前模型名称...")
        model_name_locator = page.locator(MODEL_NAME_SELECTOR)
        displayed_model_name_from_page_raw = await model_name_locator.first.inner_text(
            timeout=7000
        )
        displayed_model_name = displayed_model_name_from_page_raw.strip()
        logger.info(
            f"   页面当前显示模型名称 (原始: '{displayed_model_name_from_page_raw}', 清理后: '{displayed_model_name}')"
        )

        found_model_id_from_display = None
        if model_list_fetch_event and not model_list_fetch_event.is_set():
            logger.info("等待模型列表数据 (最多5秒) 以便转换显示名称...")
            try:
                await asyncio.wait_for(model_list_fetch_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("等待模型列表超时，可能无法准确转换显示名称为ID。")

        found_model_id_from_display = displayed_model_name
        logger.info(f"页面显示的直接是模型ID: '{found_model_id_from_display}'")

        new_model_value = found_model_id_from_display
        if state.current_ai_studio_model_id != new_model_value:
            state.current_ai_studio_model_id = new_model_value
            logger.info(
                f"   全局 current_ai_studio_model_id 已更新为: {state.current_ai_studio_model_id}"
            )
        else:
            logger.info(
                f"   全局 current_ai_studio_model_id ('{state.current_ai_studio_model_id}') 与从页面获取的值一致，未更改。"
            )

        if set_storage:
            logger.info(
                "   准备为页面状态设置 localStorage (确保 isAdvancedOpen=true)..."
            )
            existing_prefs_for_update_str = await page.evaluate(
                "() => localStorage.getItem('aiStudioUserPreference')"
            )
            prefs_to_set = {}
            if existing_prefs_for_update_str:
                try:
                    prefs_to_set = json.loads(existing_prefs_for_update_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "   解析现有 localStorage.aiStudioUserPreference 失败，将创建新的偏好设置。"
                    )

            # 使用新的强制设置功能
            logger.info("应用强制UI状态设置...")
            ui_state_success = await _verify_and_apply_ui_state(page, "set_model")
            if not ui_state_success:
                logger.warning("UI状态设置失败，使用传统方法")
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            else:
                # 确保prefs_to_set也包含正确的设置
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            logger.info("强制 isAdvancedOpen: true, areToolsOpen: true")

            if found_model_id_from_display:
                new_prompt_model_path = f"models/{found_model_id_from_display}"
                prefs_to_set["promptModel"] = new_prompt_model_path
                logger.info(
                    f"     设置 promptModel 为: {new_prompt_model_path} (基于找到的ID)"
                )
            elif "promptModel" not in prefs_to_set:
                logger.warning(
                    f"     无法从页面显示 '{displayed_model_name}' 找到模型ID，且 localStorage 中无现有 promptModel。promptModel 将不会被主动设置以避免潜在问题。"
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
            logger.info(
                f"   localStorage.aiStudioUserPreference 已更新。isAdvancedOpen: {prefs_to_set.get('isAdvancedOpen')}, areToolsOpen: {prefs_to_set.get('areToolsOpen')} (期望: True), promptModel: '{prefs_to_set.get('promptModel', '未设置/保留原样')}'。"
            )
    except asyncio.CancelledError:
        raise
    except Exception as e_set_disp:
        logger.error(f"尝试从页面显示设置模型时出错: {e_set_disp}", exc_info=True)
