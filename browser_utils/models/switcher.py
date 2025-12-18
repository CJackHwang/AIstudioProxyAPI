"""
Model Switching Logic
"""

import asyncio
import json
import logging
import os
from typing import Optional

from playwright.async_api import Page as AsyncPage
from playwright.async_api import expect as expect_async

from config import AI_STUDIO_URL_PATTERN, INPUT_SELECTOR, MODEL_NAME_SELECTOR

from .ui_state import _verify_and_apply_ui_state

logger = logging.getLogger("AIStudioProxyServer")


async def switch_ai_studio_model(page: AsyncPage, model_id: str, req_id: str) -> bool:
    """切换AI Studio模型"""
    logger.info(f"[模型] 切换: -> {model_id}")
    original_prefs_str: Optional[str] = None
    original_prompt_model: Optional[str] = None
    new_chat_url = f"https://{AI_STUDIO_URL_PATTERN}prompts/new_chat"

    try:
        original_prefs_str = await page.evaluate(
            "() => localStorage.getItem('aiStudioUserPreference')"
        )
        if original_prefs_str:
            try:
                original_prefs_obj = json.loads(original_prefs_str)
                original_prompt_model = original_prefs_obj.get("promptModel")
            except json.JSONDecodeError:
                logger.warning("无法解析原始的 aiStudioUserPreference JSON 字符串。")
                original_prefs_str = None

        current_prefs_for_modification = (
            json.loads(original_prefs_str) if original_prefs_str else {}
        )
        full_model_path = f"models/{model_id}"

        if current_prefs_for_modification.get("promptModel") == full_model_path:
            logger.debug(f"[Model] 已是目标模型 {model_id}")
            if page.url != new_chat_url:
                logger.debug(f"[Model] URL 非 new_chat，导航到 {new_chat_url}")
                await page.goto(
                    new_chat_url, wait_until="domcontentloaded", timeout=30000
                )
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                    timeout=30000
                )
            return True

        logger.debug(
            f"[Model] 更新 localStorage.promptModel: {current_prefs_for_modification.get('promptModel', '未知')} -> {full_model_path}"
        )
        current_prefs_for_modification["promptModel"] = full_model_path
        await page.evaluate(
            "(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)",
            json.dumps(current_prefs_for_modification),
        )

        # 使用新的强制设置功能
        logger.debug("[State] 应用强制 UI 状态设置...")
        ui_state_success = await _verify_and_apply_ui_state(page, req_id)
        if not ui_state_success:
            logger.warning("UI状态设置失败，但继续执行模型切换流程")

        # 为了保持兼容性，也更新当前的prefs对象
        current_prefs_for_modification["isAdvancedOpen"] = True
        current_prefs_for_modification["areToolsOpen"] = True
        await page.evaluate(
            "(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)",
            json.dumps(current_prefs_for_modification),
        )

        logger.debug(f"[Model] 导航到 {new_chat_url}...")
        await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=30000)

        input_field = page.locator(INPUT_SELECTOR)
        await expect_async(input_field).to_be_visible(timeout=30000)
        logger.debug("[Model] 页面导航完成，输入框可见")

        # 页面加载后再次验证UI状态设置
        logger.debug("[State] 验证 UI 状态...")
        final_ui_state_success = await _verify_and_apply_ui_state(page, req_id)
        if final_ui_state_success:
            logger.debug("[State] UI 状态验证成功")
        else:
            logger.warning("UI状态最终验证失败，但继续执行模型切换流程")

        final_prefs_str = await page.evaluate(
            "() => localStorage.getItem('aiStudioUserPreference')"
        )
        final_prompt_model_in_storage: Optional[str] = None
        if final_prefs_str:
            try:
                final_prefs_obj = json.loads(final_prefs_str)
                final_prompt_model_in_storage = final_prefs_obj.get("promptModel")
            except json.JSONDecodeError:
                logger.warning("无法解析刷新后的 aiStudioUserPreference JSON 字符串。")

        if final_prompt_model_in_storage == full_model_path:
            logger.debug(f"[Model] localStorage 已设置: {full_model_path}")

            page_display_match = False

            # 获取parsed_model_list
            from api_utils.server_state import state

            parsed_model_list = getattr(state, "parsed_model_list", [])

            if parsed_model_list:
                for m_obj in parsed_model_list:
                    if m_obj.get("id") == model_id:
                        m_obj.get("display_name")
                        break

            try:
                model_name_locator = page.locator(MODEL_NAME_SELECTOR)
                actual_displayed_model_id_on_page_raw = (
                    await model_name_locator.first.inner_text(timeout=5000)
                )
                actual_displayed_model_id_on_page = (
                    actual_displayed_model_id_on_page_raw.strip()
                )

                target_model_id = model_id

                if actual_displayed_model_id_on_page == target_model_id:
                    page_display_match = True
                    logger.info("[模型] 切换成功")
                else:
                    page_display_match = False
                    logger.error(
                        f"页面显示模型ID ('{actual_displayed_model_id_on_page}') 与期望ID ('{target_model_id}') 不一致。"
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e_disp:
                page_display_match = False  # 读取失败则认为不匹配
                logger.warning(
                    f"读取页面显示的当前模型ID时出错: {e_disp}。将无法验证页面显示。"
                )

            if page_display_match:
                try:
                    logger.debug("[Model] 重新启用临时聊天模式...")
                    incognito_button_locator = page.locator(
                        'button[aria-label="Temporary chat toggle"]'
                    )

                    await incognito_button_locator.wait_for(
                        state="visible", timeout=5000
                    )

                    button_classes = await incognito_button_locator.get_attribute(
                        "class"
                    )

                    if button_classes and "ms-button-active" in button_classes:
                        logger.debug("[Model] 临时聊天模式已激活")
                    else:
                        logger.debug("[Model] 点击开启临时聊天模式...")
                        await incognito_button_locator.click(timeout=3000)
                        await asyncio.sleep(0.5)

                        updated_classes = await incognito_button_locator.get_attribute(
                            "class"
                        )
                        if updated_classes and "ms-button-active" in updated_classes:
                            logger.debug("[Model] 临时聊天模式已启用")
                        else:
                            logger.warning(
                                "点击后 '临时聊天' 模式状态验证失败，可能未成功重新开启。"
                            )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"模型切换后重新启用 '临时聊天' 模式失败: {e}")
                return True
            else:
                logger.error(
                    "模型切换失败，因为页面显示的模型与期望不符 (即使localStorage可能已更改)。"
                )
        else:
            logger.error(
                f"AI Studio 未接受模型更改 (localStorage)。期望='{full_model_path}', 实际='{final_prompt_model_in_storage or '未设置或无效'}'."
            )

        logger.debug("[Recovery] 尝试恢复到页面当前模型...")
        current_displayed_name_for_revert_raw = "无法读取"
        current_displayed_name_for_revert_stripped = "无法读取"

        try:
            model_name_locator_revert = page.locator(MODEL_NAME_SELECTOR)
            current_displayed_name_for_revert_raw = (
                await model_name_locator_revert.first.inner_text(timeout=5000)
            )
            current_displayed_name_for_revert_stripped = (
                current_displayed_name_for_revert_raw.strip()
            )
            logger.debug(
                f"恢复：页面当前显示的模型名称 (原始: '{current_displayed_name_for_revert_raw}', 清理后: '{current_displayed_name_for_revert_stripped}')"
            )
        except asyncio.CancelledError:
            raise
        except Exception as e_read_disp_revert:
            logger.warning(
                f"恢复：读取页面当前显示模型名称失败: {e_read_disp_revert}。将尝试回退到原始localStorage。"
            )
            if original_prefs_str:
                logger.debug(
                    f"恢复：由于无法读取当前页面显示，尝试将 localStorage 恢复到原始状态: '{original_prompt_model or '未设置'}'"
                )
                await page.evaluate(
                    "(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)",
                    original_prefs_str,
                )
                logger.debug(
                    f"恢复：导航到 '{new_chat_url}' 以应用恢复的原始 localStorage 设置..."
                )
                await page.goto(
                    new_chat_url, wait_until="domcontentloaded", timeout=20000
                )
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                    timeout=20000
                )
                logger.debug(
                    "恢复：页面已导航到新聊天并加载，已尝试应用原始 localStorage。"
                )
            else:
                logger.warning(
                    "恢复：无有效的原始 localStorage 状态可恢复，也无法读取当前页面显示。"
                )
            return False

        model_id_to_revert_to = None
        if current_displayed_name_for_revert_stripped != "无法读取":
            model_id_to_revert_to = current_displayed_name_for_revert_stripped
            logger.debug(
                f"恢复：页面当前显示的ID是 '{model_id_to_revert_to}'，将直接用于恢复。"
            )
        else:
            if current_displayed_name_for_revert_stripped == "无法读取":
                logger.warning(
                    "恢复：因无法读取页面显示名称，故不能从 parsed_model_list 转换ID。"
                )
            else:
                logger.warning(
                    f"恢复：parsed_model_list 为空，无法从显示名称 '{current_displayed_name_for_revert_stripped}' 转换模型ID。"
                )

        if model_id_to_revert_to:
            base_prefs_for_final_revert = {}
            try:
                current_ls_content_str = await page.evaluate(
                    "() => localStorage.getItem('aiStudioUserPreference')"
                )
                if current_ls_content_str:
                    base_prefs_for_final_revert = json.loads(current_ls_content_str)
                elif original_prefs_str:
                    base_prefs_for_final_revert = json.loads(original_prefs_str)
            except json.JSONDecodeError:
                logger.warning("恢复：解析现有 localStorage 以构建恢复偏好失败。")

            path_to_revert_to = f"models/{model_id_to_revert_to}"
            base_prefs_for_final_revert["promptModel"] = path_to_revert_to
            # 使用新的强制设置功能
            logger.debug("[Recovery] 应用强制 UI 状态...")
            ui_state_success = await _verify_and_apply_ui_state(page, req_id)
            if not ui_state_success:
                logger.warning("恢复：UI状态设置失败，但继续执行恢复流程")

            # 为了保持兼容性，也更新当前的prefs对象
            base_prefs_for_final_revert["isAdvancedOpen"] = True
            base_prefs_for_final_revert["areToolsOpen"] = True
            logger.debug(
                f"恢复：准备将 localStorage.promptModel 设置回页面实际显示的模型的路径: '{path_to_revert_to}'，并强制设置配置选项"
            )
            await page.evaluate(
                "(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)",
                json.dumps(base_prefs_for_final_revert),
            )
            logger.debug(
                f"恢复：导航到 '{new_chat_url}' 以应用恢复到 '{model_id_to_revert_to}' 的 localStorage 设置..."
            )
            await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=30000)
            await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                timeout=30000
            )

            # 恢复后再次验证UI状态
            logger.debug("[Recovery] 验证 UI 状态...")
            final_ui_state_success = await _verify_and_apply_ui_state(page, req_id)
            if final_ui_state_success:
                logger.debug("[Recovery] UI 状态验证成功")
            else:
                logger.warning("恢复：UI状态最终验证失败")

            logger.debug(
                f"恢复：页面已导航到新聊天并加载。localStorage 应已设置为反映模型 '{model_id_to_revert_to}'。"
            )
        else:
            logger.error(
                f"恢复：无法将模型恢复到页面显示的状态，因为未能从显示名称 '{current_displayed_name_for_revert_stripped}' 确定有效模型ID。"
            )
            if original_prefs_str:
                logger.warning(
                    f"恢复：作为最终后备，尝试恢复到原始 localStorage: '{original_prompt_model or '未设置'}'"
                )
                await page.evaluate(
                    "(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)",
                    original_prefs_str,
                )
                logger.debug(
                    f"恢复：导航到 '{new_chat_url}' 以应用最终后备的原始 localStorage。"
                )
                await page.goto(
                    new_chat_url, wait_until="domcontentloaded", timeout=20000
                )
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                    timeout=20000
                )
                logger.debug(
                    "恢复：页面已导航到新聊天并加载，已应用最终后备的原始 localStorage。"
                )
            else:
                logger.warning("恢复：无有效的原始 localStorage 状态可作为最终后备。")

        return False

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("切换模型过程中发生严重错误")
        # 导入save_error_snapshot函数
        from browser_utils.operations import save_error_snapshot

        await save_error_snapshot(f"model_switch_error_{req_id}")
        try:
            if original_prefs_str:
                logger.debug(
                    f"发生异常，尝试恢复 localStorage 至: {original_prompt_model or '未设置'}"
                )
                await page.evaluate(
                    "(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)",
                    original_prefs_str,
                )
                logger.debug(
                    f"异常恢复：导航到 '{new_chat_url}' 以应用恢复的 localStorage。"
                )
                await page.goto(
                    new_chat_url, wait_until="domcontentloaded", timeout=15000
                )
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(
                    timeout=15000
                )
        except asyncio.CancelledError:
            raise
        except Exception as recovery_err:
            logger.error(f"异常后恢复 localStorage 失败: {recovery_err}")
        return False


def load_excluded_models(filename: str):
    """加载排除的模型列表"""
    from api_utils.server_state import state

    excluded_model_ids = getattr(state, "excluded_model_ids", set())

    # Get absolute path relative to browser_utils/models/switcher.py
    # This might need adjustment based on where it originally expected to be.
    # Original: os.path.join(os.path.dirname(__file__), "..", filename)
    # New location: browser_utils/models/switcher.py
    # So we need to go up two levels to get to browser_utils, then .. to get to root/config?
    # Wait, original was in browser_utils/model_management.py
    # So __file__ was browser_utils/model_management.py
    # os.path.dirname(__file__) was browser_utils
    # .. was root
    # So excluded_file_path was root/filename.

    # Now we are in browser_utils/models/switcher.py
    # os.path.dirname(__file__) is browser_utils/models
    # .. is browser_utils
    # .. is root.
    # So we need to go up two levels.

    excluded_file_path = os.path.join(os.path.dirname(__file__), "..", "..", filename)
    try:
        if os.path.exists(excluded_file_path):
            with open(excluded_file_path, "r", encoding="utf-8") as f:
                loaded_ids = {line.strip() for line in f if line.strip()}
            if loaded_ids:
                excluded_model_ids.update(loaded_ids)
                state.excluded_model_ids = excluded_model_ids
                logger.debug(
                    f"从 '{filename}' 加载了 {len(loaded_ids)} 个模型到排除列表"
                )
            else:
                logger.debug(
                    f"'{filename}' 文件为空或不包含有效的模型 ID，排除列表未更改。"
                )
        else:
            logger.debug(f"模型排除列表文件 '{filename}' 未找到，排除列表为空。")
    except Exception as e:
        logger.error(f"从 '{filename}' 加载排除模型列表时出错: {e}", exc_info=True)
