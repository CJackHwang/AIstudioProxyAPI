# --- browser_utils/model_management.py ---
# 浏览器模型管理相关功能模块

import asyncio
import json
import os
import logging
import time
from typing import Optional, Set

from playwright.async_api import Page as AsyncPage, expect as expect_async, Error as PlaywrightAsyncError

# 导入配置和模型
from config import *
from models import ClientDisconnectedError

logger = logging.getLogger("AIStudioProxyServer")

# ==================== 强制UI状态设置功能 ====================

async def _verify_ui_state_settings(page: AsyncPage, req_id: str = "unknown") -> dict:
    """
    验证UI状态设置是否正确

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        dict: 包含验证结果的字典
    """
    try:
        logger.info(f"[{req_id}] 验证UI状态设置...")

        # 获取当前localStorage设置
        prefs_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")

        if not prefs_str:
            logger.warning(f"[{req_id}] localStorage.aiStudioUserPreference 不存在")
            return {
                'exists': False,
                'isAdvancedOpen': None,
                'areToolsOpen': None,
                'needsUpdate': True,
                'error': 'localStorage不存在'
            }

        try:
            prefs = json.loads(prefs_str)
            is_advanced_open = prefs.get('isAdvancedOpen')
            are_tools_open = prefs.get('areToolsOpen')

            # 检查是否需要更新
            needs_update = (is_advanced_open is not True) or (are_tools_open is not True)

            result = {
                'exists': True,
                'isAdvancedOpen': is_advanced_open,
                'areToolsOpen': are_tools_open,
                'needsUpdate': needs_update,
                'prefs': prefs
            }

            logger.info(f"[{req_id}] UI状态验证结果: isAdvancedOpen={is_advanced_open}, areToolsOpen={are_tools_open} (期望: True), needsUpdate={needs_update}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[{req_id}] 解析localStorage JSON失败: {e}")
            return {
                'exists': False,
                'isAdvancedOpen': None,
                'areToolsOpen': None,
                'needsUpdate': True,
                'error': f'JSON解析失败: {e}'
            }

    except Exception as e:
        logger.error(f"[{req_id}] 验证UI状态设置时发生错误: {e}")
        return {
            'exists': False,
            'isAdvancedOpen': None,
            'areToolsOpen': None,
            'needsUpdate': True,
            'error': f'验证失败: {e}'
        }

async def _force_ui_state_settings(page: AsyncPage, req_id: str = "unknown") -> bool:
    """
    强制设置UI状态

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        bool: 设置是否成功
    """
    try:
        logger.info(f"[{req_id}] 开始强制设置UI状态...")

        # 首先验证当前状态
        current_state = await _verify_ui_state_settings(page, req_id)

        if not current_state['needsUpdate']:
            logger.info(f"[{req_id}] UI状态已正确设置，无需更新")
            return True

        # 获取现有preferences或创建新的
        prefs = current_state.get('prefs', {})

        # 强制设置关键配置
        prefs['isAdvancedOpen'] = True
        prefs['areToolsOpen'] = True

        # 保存到localStorage
        prefs_str = json.dumps(prefs)
        await page.evaluate("(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)", prefs_str)

        logger.info(f"[{req_id}] 已强制设置: isAdvancedOpen=true, areToolsOpen=true")

        # 验证设置是否成功
        verify_state = await _verify_ui_state_settings(page, req_id)
        if not verify_state['needsUpdate']:
            logger.info(f"[{req_id}] ✅ UI状态设置验证成功")
            return True
        else:
            logger.warning(f"[{req_id}] ⚠️ UI状态设置验证失败，可能需要重试")
            return False

    except Exception as e:
        logger.error(f"[{req_id}] 强制设置UI状态时发生错误: {e}")
        return False

async def _force_ui_state_with_retry(page: AsyncPage, req_id: str = "unknown", max_retries: int = 3, retry_delay: float = 1.0) -> bool:
    """
    带重试机制的UI状态强制设置

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）

    Returns:
        bool: 设置是否最终成功
    """
    for attempt in range(1, max_retries + 1):
        logger.info(f"[{req_id}] 尝试强制设置UI状态 (第 {attempt}/{max_retries} 次)")

        success = await _force_ui_state_settings(page, req_id)
        if success:
            logger.info(f"[{req_id}] ✅ UI状态设置在第 {attempt} 次尝试中成功")
            return True

        if attempt < max_retries:
            logger.warning(f"[{req_id}] ⚠️ 第 {attempt} 次尝试失败，{retry_delay}秒后重试...")
            await asyncio.sleep(retry_delay)
        else:
            logger.error(f"[{req_id}] ❌ UI状态设置在 {max_retries} 次尝试后仍然失败")

    return False

async def _verify_and_apply_ui_state(page: AsyncPage, req_id: str = "unknown") -> bool:
    """
    验证并应用UI状态设置的完整流程

    Args:
        page: Playwright页面对象
        req_id: 请求ID用于日志

    Returns:
        bool: 操作是否成功
    """
    try:
        logger.info(f"[{req_id}] 开始验证并应用UI状态设置...")

        # 首先验证当前状态
        state = await _verify_ui_state_settings(page, req_id)

        logger.info(f"[{req_id}] 当前UI状态: exists={state['exists']}, isAdvancedOpen={state['isAdvancedOpen']}, areToolsOpen={state['areToolsOpen']}, needsUpdate={state['needsUpdate']}")

        if state['needsUpdate']:
            logger.info(f"[{req_id}] 检测到UI状态需要更新，正在应用强制设置...")
            return await _force_ui_state_with_retry(page, req_id)
        else:
            logger.info(f"[{req_id}] UI状态已正确设置，无需更新")
            return True

    except Exception as e:
        logger.error(f"[{req_id}] 验证并应用UI状态设置时发生错误: {e}")
        return False

async def switch_ai_studio_model(page: AsyncPage, model_id: str, req_id: str) -> bool:
    """切换AI Studio模型"""
    logger.info(f"[{req_id}] 开始切换模型到: {model_id}")
    original_prefs_str: Optional[str] = None
    original_prompt_model: Optional[str] = None
    new_chat_url = f"https://{AI_STUDIO_URL_PATTERN}prompts/new_chat"
    
    try:
        original_prefs_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")
        if original_prefs_str:
            try:
                original_prefs_obj = json.loads(original_prefs_str)
                original_prompt_model = original_prefs_obj.get("promptModel")
                logger.info(f"[{req_id}] 切换前 localStorage.promptModel 为: {original_prompt_model or '未设置'}")
            except json.JSONDecodeError:
                logger.warning(f"[{req_id}] 无法解析原始的 aiStudioUserPreference JSON 字符串。")
                original_prefs_str = None
        
        current_prefs_for_modification = json.loads(original_prefs_str) if original_prefs_str else {}
        full_model_path = f"models/{model_id}"
        
        if current_prefs_for_modification.get("promptModel") == full_model_path:
            logger.info(f"[{req_id}] 模型已经设置为 {model_id} (localStorage 中已是目标值)，无需切换")
            if page.url != new_chat_url:
                 logger.info(f"[{req_id}] 当前 URL 不是 new_chat ({page.url})，导航到 {new_chat_url}")
                 await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=30000)
                 await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=30000)
            return True
        
        logger.info(f"[{req_id}] 从 {current_prefs_for_modification.get('promptModel', '未知')} 更新 localStorage.promptModel 为 {full_model_path}")
        current_prefs_for_modification["promptModel"] = full_model_path
        await page.evaluate("(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)", json.dumps(current_prefs_for_modification))
        
        # 使用新的强制设置功能
        logger.info(f"[{req_id}] 应用强制UI状态设置...")
        ui_state_success = await _verify_and_apply_ui_state(page, req_id)
        if not ui_state_success:
            logger.warning(f"[{req_id}] UI状态设置失败，但继续执行模型切换流程")

        # 为了保持兼容性，也更新当前的prefs对象
        current_prefs_for_modification["isAdvancedOpen"] = True
        current_prefs_for_modification["areToolsOpen"] = True
        await page.evaluate("(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)", json.dumps(current_prefs_for_modification))

        logger.info(f"[{req_id}] localStorage 已更新，导航到 '{new_chat_url}' 应用新模型...")
        await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=30000)

        input_field = page.locator(INPUT_SELECTOR)
        await expect_async(input_field).to_be_visible(timeout=30000)
        logger.info(f"[{req_id}] 页面已导航到新聊天并加载完成，输入框可见")

        # 页面加载后再次验证UI状态设置
        logger.info(f"[{req_id}] 页面加载完成，验证UI状态设置...")
        final_ui_state_success = await _verify_and_apply_ui_state(page, req_id)
        if final_ui_state_success:
            logger.info(f"[{req_id}] ✅ UI状态最终验证成功")
        else:
            logger.warning(f"[{req_id}] ⚠️ UI状态最终验证失败，但继续执行模型切换流程")
        
        final_prefs_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")
        final_prompt_model_in_storage: Optional[str] = None
        if final_prefs_str:
            try:
                final_prefs_obj = json.loads(final_prefs_str)
                final_prompt_model_in_storage = final_prefs_obj.get("promptModel")
            except json.JSONDecodeError:
                logger.warning(f"[{req_id}] 无法解析刷新后的 aiStudioUserPreference JSON 字符串。")
        
        if final_prompt_model_in_storage == full_model_path:
            logger.info(f"[{req_id}] ✅ AI Studio localStorage 中模型已成功设置为: {full_model_path}")
            
            page_display_match = False
            expected_display_name_for_target_id = None
            actual_displayed_model_name_on_page = "无法读取"
            
            # 获取parsed_model_list
            import server
            parsed_model_list = getattr(server, 'parsed_model_list', [])
            
            if parsed_model_list:
                for m_obj in parsed_model_list:
                    if m_obj.get("id") == model_id:
                        expected_display_name_for_target_id = m_obj.get("display_name")
                        break
            
            if not expected_display_name_for_target_id:
                logger.warning(f"[{req_id}] 无法在parsed_model_list中找到目标ID '{model_id}' 的显示名称，跳过页面显示名称验证。这可能不准确。")
                page_display_match = True
            else:
                try:
                    model_name_locator = page.locator('mat-select[data-test-ms-model-selector] div.model-option-content span.gmat-body-medium')
                    actual_displayed_model_name_on_page_raw = await model_name_locator.first.inner_text(timeout=5000)
                    actual_displayed_model_name_on_page = actual_displayed_model_name_on_page_raw.strip()
                    normalized_actual_display = actual_displayed_model_name_on_page.lower()
                    normalized_expected_display = expected_display_name_for_target_id.strip().lower()
                    
                    if normalized_actual_display == normalized_expected_display:
                        page_display_match = True
                        logger.info(f"[{req_id}] ✅ 页面显示模型 ('{actual_displayed_model_name_on_page}') 与期望 ('{expected_display_name_for_target_id}') 一致。")
                    else:
                        logger.error(f"[{req_id}] ❌ 页面显示模型 ('{actual_displayed_model_name_on_page}') 与期望 ('{expected_display_name_for_target_id}') 不一致。(Raw page: '{actual_displayed_model_name_on_page_raw}')")
                except Exception as e_disp:
                    logger.warning(f"[{req_id}] 读取页面显示的当前模型名称时出错: {e_disp}。将无法验证页面显示。")
            
            if page_display_match:
                return True
            else:
                logger.error(f"[{req_id}] ❌ 模型切换失败，因为页面显示的模型与期望不符 (即使localStorage可能已更改)。")
        else:
            logger.error(f"[{req_id}] ❌ AI Studio 未接受模型更改 (localStorage)。期望='{full_model_path}', 实际='{final_prompt_model_in_storage or '未设置或无效'}'.")
        
        logger.info(f"[{req_id}] 模型切换失败。尝试恢复到页面当前实际显示的模型的状态...")
        current_displayed_name_for_revert_raw = "无法读取"
        current_displayed_name_for_revert_stripped = "无法读取"
        
        try:
            model_name_locator_revert = page.locator('mat-select[data-test-ms-model-selector] div.model-option-content span.gmat-body-medium')
            current_displayed_name_for_revert_raw = await model_name_locator_revert.first.inner_text(timeout=5000)
            current_displayed_name_for_revert_stripped = current_displayed_name_for_revert_raw.strip()
            logger.info(f"[{req_id}] 恢复：页面当前显示的模型名称 (原始: '{current_displayed_name_for_revert_raw}', 清理后: '{current_displayed_name_for_revert_stripped}')")
        except Exception as e_read_disp_revert:
            logger.warning(f"[{req_id}] 恢复：读取页面当前显示模型名称失败: {e_read_disp_revert}。将尝试回退到原始localStorage。")
            if original_prefs_str:
                logger.info(f"[{req_id}] 恢复：由于无法读取当前页面显示，尝试将 localStorage 恢复到原始状态: '{original_prompt_model or '未设置'}'")
                await page.evaluate("(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)", original_prefs_str)
                logger.info(f"[{req_id}] 恢复：导航到 '{new_chat_url}' 以应用恢复的原始 localStorage 设置...")
                await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=20000)
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=20000)
                logger.info(f"[{req_id}] 恢复：页面已导航到新聊天并加载，已尝试应用原始 localStorage。")
            else:
                logger.warning(f"[{req_id}] 恢复：无有效的原始 localStorage 状态可恢复，也无法读取当前页面显示。")
            return False
        
        model_id_to_revert_to = None
        if parsed_model_list and current_displayed_name_for_revert_stripped != "无法读取":
            normalized_current_display_for_revert = current_displayed_name_for_revert_stripped.lower()
            for m_obj in parsed_model_list:
                parsed_list_display_name = m_obj.get("display_name", "").strip().lower()
                if parsed_list_display_name == normalized_current_display_for_revert:
                    model_id_to_revert_to = m_obj.get("id")
                    logger.info(f"[{req_id}] 恢复：页面显示名称 '{current_displayed_name_for_revert_stripped}' 对应模型ID: {model_id_to_revert_to}")
                    break
            
            if not model_id_to_revert_to:
                logger.warning(f"[{req_id}] 恢复：无法在 parsed_model_list 中找到与页面显示名称 '{current_displayed_name_for_revert_stripped}' 匹配的模型ID。")
        else:
            if current_displayed_name_for_revert_stripped == "无法读取":
                 logger.warning(f"[{req_id}] 恢复：因无法读取页面显示名称，故不能从 parsed_model_list 转换ID。")
            else:
                 logger.warning(f"[{req_id}] 恢复：parsed_model_list 为空，无法从显示名称 '{current_displayed_name_for_revert_stripped}' 转换模型ID。")
        
        if model_id_to_revert_to:
            base_prefs_for_final_revert = {}
            try:
                current_ls_content_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")
                if current_ls_content_str:
                    base_prefs_for_final_revert = json.loads(current_ls_content_str)
                elif original_prefs_str:
                    base_prefs_for_final_revert = json.loads(original_prefs_str)
            except json.JSONDecodeError:
                logger.warning(f"[{req_id}] 恢复：解析现有 localStorage 以构建恢复偏好失败。")
            
            path_to_revert_to = f"models/{model_id_to_revert_to}"
            base_prefs_for_final_revert["promptModel"] = path_to_revert_to
            # 使用新的强制设置功能
            logger.info(f"[{req_id}] 恢复：应用强制UI状态设置...")
            ui_state_success = await _verify_and_apply_ui_state(page, req_id)
            if not ui_state_success:
                logger.warning(f"[{req_id}] 恢复：UI状态设置失败，但继续执行恢复流程")

            # 为了保持兼容性，也更新当前的prefs对象
            base_prefs_for_final_revert["isAdvancedOpen"] = True
            base_prefs_for_final_revert["areToolsOpen"] = True
            logger.info(f"[{req_id}] 恢复：准备将 localStorage.promptModel 设置回页面实际显示的模型的路径: '{path_to_revert_to}'，并强制设置配置选项")
            await page.evaluate("(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)", json.dumps(base_prefs_for_final_revert))
            logger.info(f"[{req_id}] 恢复：导航到 '{new_chat_url}' 以应用恢复到 '{model_id_to_revert_to}' 的 localStorage 设置...")
            await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=30000)
            await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=30000)

            # 恢复后再次验证UI状态
            logger.info(f"[{req_id}] 恢复：页面加载完成，验证UI状态设置...")
            final_ui_state_success = await _verify_and_apply_ui_state(page, req_id)
            if final_ui_state_success:
                logger.info(f"[{req_id}] ✅ 恢复：UI状态最终验证成功")
            else:
                logger.warning(f"[{req_id}] ⚠️ 恢复：UI状态最终验证失败")

            logger.info(f"[{req_id}] 恢复：页面已导航到新聊天并加载。localStorage 应已设置为反映模型 '{model_id_to_revert_to}'。")
        else:
            logger.error(f"[{req_id}] 恢复：无法将模型恢复到页面显示的状态，因为未能从显示名称 '{current_displayed_name_for_revert_stripped}' 确定有效模型ID。")
            if original_prefs_str:
                logger.warning(f"[{req_id}] 恢复：作为最终后备，尝试恢复到原始 localStorage: '{original_prompt_model or '未设置'}'")
                await page.evaluate("(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)", original_prefs_str)
                logger.info(f"[{req_id}] 恢复：导航到 '{new_chat_url}' 以应用最终后备的原始 localStorage。")
                await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=20000)
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=20000)
                logger.info(f"[{req_id}] 恢复：页面已导航到新聊天并加载，已应用最终后备的原始 localStorage。")
            else:
                logger.warning(f"[{req_id}] 恢复：无有效的原始 localStorage 状态可作为最终后备。")
        
        return False
        
    except Exception as e:
        logger.exception(f"[{req_id}] ❌ 切换模型过程中发生严重错误")
        # 导入save_error_snapshot函数
        from .operations import save_error_snapshot
        await save_error_snapshot(f"model_switch_error_{req_id}")
        try:
            if original_prefs_str:
                logger.info(f"[{req_id}] 发生异常，尝试恢复 localStorage 至: {original_prompt_model or '未设置'}")
                await page.evaluate("(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)", original_prefs_str)
                logger.info(f"[{req_id}] 异常恢复：导航到 '{new_chat_url}' 以应用恢复的 localStorage。")
                await page.goto(new_chat_url, wait_until="domcontentloaded", timeout=15000)
                await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=15000)
        except Exception as recovery_err:
            logger.error(f"[{req_id}] 异常后恢复 localStorage 失败: {recovery_err}")
        return False

def load_excluded_models(filename: str):
    """加载排除的模型列表"""
    import server
    excluded_model_ids = getattr(server, 'excluded_model_ids', set())
    
    excluded_file_path = os.path.join(os.path.dirname(__file__), '..', filename)
    try:
        if os.path.exists(excluded_file_path):
            with open(excluded_file_path, 'r', encoding='utf-8') as f:
                loaded_ids = {line.strip() for line in f if line.strip()}
            if loaded_ids:
                excluded_model_ids.update(loaded_ids)
                server.excluded_model_ids = excluded_model_ids
                logger.info(f"✅ 从 '{filename}' 加载了 {len(loaded_ids)} 个模型到排除列表: {excluded_model_ids}")
            else:
                logger.info(f"'{filename}' 文件为空或不包含有效的模型 ID，排除列表未更改。")
        else:
            logger.info(f"模型排除列表文件 '{filename}' 未找到，排除列表为空。")
    except Exception as e:
        logger.error(f"❌ 从 '{filename}' 加载排除模型列表时出错: {e}", exc_info=True)

async def _handle_initial_model_state_and_storage(page: AsyncPage):
    """处理初始模型状态和存储"""
    import server
    current_ai_studio_model_id = getattr(server, 'current_ai_studio_model_id', None)
    parsed_model_list = getattr(server, 'parsed_model_list', [])
    model_list_fetch_event = getattr(server, 'model_list_fetch_event', None)

    logger.info("--- (新) 处理初始模型状态, localStorage 和 isAdvancedOpen ---")
    needs_reload_and_storage_update = False
    reason_for_reload = ""

    try:
        # 首先检查页面是否仍然有效
        try:
            is_closed = page.is_closed()
            if asyncio.iscoroutine(is_closed):
                is_closed = await is_closed
            if is_closed:
                logger.error("❌ 页面已关闭，无法处理初始模型状态")
                return
        except Exception as page_check_err:
            logger.error(f"❌ 检查页面状态时出错: {page_check_err}")
            return

        # 检查页面是否可以执行JavaScript
        try:
            await page.evaluate("() => true")
        except Exception as js_test_err:
            logger.error(f"❌ 页面无法执行JavaScript，可能已断开连接: {js_test_err}")
            return

        initial_prefs_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")
        if not initial_prefs_str:
            needs_reload_and_storage_update = True
            reason_for_reload = "localStorage.aiStudioUserPreference 未找到。"
            logger.info(f"   判定需要刷新和存储更新: {reason_for_reload}")
        else:
            logger.info("   localStorage 中找到 'aiStudioUserPreference'。正在解析...")
            try:
                pref_obj = json.loads(initial_prefs_str)
                prompt_model_path = pref_obj.get("promptModel")
                is_advanced_open_in_storage = pref_obj.get("isAdvancedOpen")
                is_prompt_model_valid = isinstance(prompt_model_path, str) and prompt_model_path.strip()
                
                if not is_prompt_model_valid:
                    needs_reload_and_storage_update = True
                    reason_for_reload = "localStorage.promptModel 无效或未设置。"
                    logger.info(f"   判定需要刷新和存储更新: {reason_for_reload}")
                else:
                    # 使用新的UI状态验证功能
                    ui_state = await _verify_ui_state_settings(page, "initial")
                    if ui_state['needsUpdate']:
                        needs_reload_and_storage_update = True
                        reason_for_reload = f"UI状态需要更新: isAdvancedOpen={ui_state['isAdvancedOpen']}, areToolsOpen={ui_state['areToolsOpen']} (期望: True)"
                        logger.info(f"   判定需要刷新和存储更新: {reason_for_reload}")
                    else:
                        server.current_ai_studio_model_id = prompt_model_path.split('/')[-1]
                        logger.info(f"   ✅ localStorage 有效且UI状态正确。初始模型 ID 从 localStorage 设置为: {server.current_ai_studio_model_id}")
            except json.JSONDecodeError:
                needs_reload_and_storage_update = True
                reason_for_reload = "解析 localStorage.aiStudioUserPreference JSON 失败。"
                logger.error(f"   判定需要刷新和存储更新: {reason_for_reload}")
        
        if needs_reload_and_storage_update:
            logger.info(f"   执行刷新和存储更新流程，原因: {reason_for_reload}")
            logger.info("   步骤 1: 调用 _set_model_from_page_display(set_storage=True) 更新 localStorage 和全局模型 ID...")
            await _set_model_from_page_display(page, set_storage=True)
            
            current_page_url = page.url
            logger.info(f"   步骤 2: 重新加载页面 ({current_page_url}) 以应用 isAdvancedOpen=true...")
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"   尝试重新加载页面 (第 {attempt + 1}/{max_retries} 次): {current_page_url}")
                    await page.goto(current_page_url, wait_until="domcontentloaded", timeout=40000)
                    await expect_async(page.locator(INPUT_SELECTOR)).to_be_visible(timeout=30000)
                    logger.info(f"   ✅ 页面已成功重新加载到: {page.url}")

                    # 页面重新加载后验证UI状态
                    logger.info(f"   页面重新加载完成，验证UI状态设置...")
                    reload_ui_state_success = await _verify_and_apply_ui_state(page, "reload")
                    if reload_ui_state_success:
                        logger.info(f"   ✅ 重新加载后UI状态验证成功")
                    else:
                        logger.warning(f"   ⚠️ 重新加载后UI状态验证失败")

                    break  # 成功则跳出循环
                except Exception as reload_err:
                    logger.warning(f"   ⚠️ 页面重新加载尝试 {attempt + 1}/{max_retries} 失败: {reload_err}")
                    if attempt < max_retries - 1:
                        logger.info(f"   将在5秒后重试...")
                        await asyncio.sleep(5)
                    else:
                        logger.error(f"   ❌ 页面重新加载在 {max_retries} 次尝试后最终失败: {reload_err}. 后续模型状态可能不准确。", exc_info=True)
                        from .operations import save_error_snapshot
                        await save_error_snapshot(f"initial_storage_reload_fail_attempt_{attempt+1}")
            
            logger.info("   步骤 3: 重新加载后，再次调用 _set_model_from_page_display(set_storage=False) 以同步全局模型 ID...")
            await _set_model_from_page_display(page, set_storage=False)
            logger.info(f"   ✅ 刷新和存储更新流程完成。最终全局模型 ID: {server.current_ai_studio_model_id}")
        else:
            logger.info("   localStorage 状态良好 (isAdvancedOpen=true, promptModel有效)，无需刷新页面。")
    except Exception as e:
        logger.error(f"❌ (新) 处理初始模型状态和 localStorage 时发生严重错误: {e}", exc_info=True)
        try:
            logger.warning("   由于发生错误，尝试回退仅从页面显示设置全局模型 ID (不写入localStorage)...")
            await _set_model_from_page_display(page, set_storage=False)
        except Exception as fallback_err:
            logger.error(f"   回退设置模型ID也失败: {fallback_err}")

async def _set_model_from_page_display(page: AsyncPage, set_storage: bool = False):
    """从页面显示设置模型"""
    import server
    current_ai_studio_model_id = getattr(server, 'current_ai_studio_model_id', None)
    parsed_model_list = getattr(server, 'parsed_model_list', [])
    model_list_fetch_event = getattr(server, 'model_list_fetch_event', None)

    try:
        # 首先检查页面是否仍然有效
        try:
            is_closed = page.is_closed()
            if asyncio.iscoroutine(is_closed):
                is_closed = await is_closed
            if is_closed:
                logger.error("   ❌ 页面已关闭，无法从页面显示设置模型")
                return
        except Exception as page_check_err:
            logger.error(f"   ❌ 检查页面状态时出错: {page_check_err}")
            return

        logger.info("   尝试从页面显示元素读取当前模型名称...")
        model_name_locator = page.locator('mat-select[data-test-ms-model-selector] div.model-option-content span.gmat-body-medium')
        displayed_model_name_from_page_raw = await model_name_locator.first.inner_text(timeout=7000)
        displayed_model_name = displayed_model_name_from_page_raw.strip()
        logger.info(f"   页面当前显示模型名称 (原始: '{displayed_model_name_from_page_raw}', 清理后: '{displayed_model_name}')")
        
        found_model_id_from_display = None
        if model_list_fetch_event and not model_list_fetch_event.is_set():
            logger.info("   等待模型列表数据 (最多5秒) 以便转换显示名称...")
            try: 
                await asyncio.wait_for(model_list_fetch_event.wait(), timeout=5.0)
            except asyncio.TimeoutError: 
                logger.warning("   等待模型列表超时，可能无法准确转换显示名称为ID。")
        
        if parsed_model_list:
            for model_obj in parsed_model_list:
                if model_obj.get("display_name") and model_obj.get("display_name").strip() == displayed_model_name:
                    found_model_id_from_display = model_obj.get("id")
                    logger.info(f"   显示名称 '{displayed_model_name}' 对应模型 ID: {found_model_id_from_display}")
                    break
            
            if not found_model_id_from_display:
                 logger.warning(f"   未在已知模型列表中找到与显示名称 '{displayed_model_name}' 匹配的 ID。")
        else:
            logger.warning("   模型列表尚不可用，无法将显示名称转换为ID。")
        
        new_model_value = found_model_id_from_display if found_model_id_from_display else displayed_model_name
        if server.current_ai_studio_model_id != new_model_value:
            server.current_ai_studio_model_id = new_model_value
            logger.info(f"   全局 current_ai_studio_model_id 已更新为: {server.current_ai_studio_model_id}")
        else:
            logger.info(f"   全局 current_ai_studio_model_id ('{server.current_ai_studio_model_id}') 与从页面获取的值一致，未更改。")
        
        if set_storage:
            logger.info(f"   准备为页面状态设置 localStorage (确保 isAdvancedOpen=true)...")
            existing_prefs_for_update_str = await page.evaluate("() => localStorage.getItem('aiStudioUserPreference')")
            prefs_to_set = {}
            if existing_prefs_for_update_str:
                try:
                    prefs_to_set = json.loads(existing_prefs_for_update_str)
                except json.JSONDecodeError:
                    logger.warning("   解析现有 localStorage.aiStudioUserPreference 失败，将创建新的偏好设置。")
            
            # 使用新的强制设置功能
            logger.info(f"     应用强制UI状态设置...")
            ui_state_success = await _verify_and_apply_ui_state(page, "set_model")
            if not ui_state_success:
                logger.warning(f"     UI状态设置失败，使用传统方法")
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            else:
                # 确保prefs_to_set也包含正确的设置
                prefs_to_set["isAdvancedOpen"] = True
                prefs_to_set["areToolsOpen"] = True
            logger.info(f"     强制 isAdvancedOpen: true, areToolsOpen: true")
            
            if found_model_id_from_display:
                new_prompt_model_path = f"models/{found_model_id_from_display}"
                prefs_to_set["promptModel"] = new_prompt_model_path
                logger.info(f"     设置 promptModel 为: {new_prompt_model_path} (基于找到的ID)")
            elif "promptModel" not in prefs_to_set:
                logger.warning(f"     无法从页面显示 '{displayed_model_name}' 找到模型ID，且 localStorage 中无现有 promptModel。promptModel 将不会被主动设置以避免潜在问题。")
            
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
                "fileCopyrightAcknowledged": True
            }
            for key, val_default in default_keys_if_missing.items():
                if key not in prefs_to_set:
                    prefs_to_set[key] = val_default
            
            await page.evaluate("(prefsStr) => localStorage.setItem('aiStudioUserPreference', prefsStr)", json.dumps(prefs_to_set))
            logger.info(f"   ✅ localStorage.aiStudioUserPreference 已更新。isAdvancedOpen: {prefs_to_set.get('isAdvancedOpen')}, areToolsOpen: {prefs_to_set.get('areToolsOpen')} (期望: True), promptModel: '{prefs_to_set.get('promptModel', '未设置/保留原样')}'。")
    except Exception as e_set_disp:
        logger.error(f"   尝试从页面显示设置模型时出错: {e_set_disp}", exc_info=True) 