# --- browser_utils/initialization.py ---
# 浏览器初始化相关功能模块

import asyncio
import os
import time
import json
import logging
from typing import Optional, Any, Dict, Tuple

from playwright.async_api import Page as AsyncPage, Browser as AsyncBrowser, BrowserContext as AsyncBrowserContext, Error as PlaywrightAsyncError, expect as expect_async

from playwright.async_api import Route # 导入 Route 类型
import copy
import re

# 导入配置和模型
from config import *
from models import ClientDisconnectedError

logger = logging.getLogger("AIStudioProxyServer")




async def intercept_and_modify_response(route: Route):
    """
    拦截请求并修改其响应。
    此函数在请求被发起时触发。
    """
    request = route.request
    logger.info(f"   🚀 拦截到请求: {request.method} {request.url}")
    # --- 定义所有变量到函数内部 ---
    # 确定模型数据在列表中的索引 (根据您提供的原始响应数据进行精确调整)
    # 原始响应数据: [[['models/gemini-2.5-pro-preview-06-05', None, '2.5-preview-06-05', 'Gemini 2.5 Pro Preview', ..., ['generateContent', 'countTokens', ...]], ...]]
    # 观察数据，模型名称在内部列表的第 0 个位置
    # 显示名称在内部列表的第 3 个位置
    # 描述在内部列表的第 4 个位置
    # 支持的方法列表在内部列表的第 7 个位置
    NAME_IDX = 0
    DISPLAY_NAME_IDX = 3 # 从日志看，这是显示名称的位置
    DESC_IDX = 4         # 从日志看，这是描述的位置
    METHODS_IDX = 7      # 从日志看，这是支持方法列表的位置
    MODELS_TO_INJECT = [
        {
            "name": "models/kingfall-ab-test",
            "displayName": "👑 Kingfall (Custom)",
            "description": "Custom injected model."
        },
        {
            "name": "models/gemini-2.5-pro-preview-03-25",
            "displayName": "✨ Gemini 2.5 Pro 03-25 (Custom)",
            "description": "Custom injected model."
        },
        {
            "name": "models/goldmane-ab-test",
            "displayName": "🦁 Goldmane (Custom)",
            "description": "Custom injected model."
        },
        {
            "name": "models/claybrook-ab-test",
            "displayName": "💧 Claybrook (Custom)",
            "description": "Custom injected model."
        },
        {
            "name": "models/frostwind-ab-test",
            "displayName": "❄️ Frostwind (Custom)",
            "description": "Custom injected model."
        },
        {
            "name": "models/calmriver-ab-test",
            "displayName": "🌊 Calmriver (Custom)",
            "description": "Custom injected model."
        },
        # 可以在此按格式继续添加更多模型
    ]
    # --- 变量定义结束 ---
    # 检查 URL 是否匹配您指定的目标：'MakerSuiteService/ListModels'
    if re.search(r'MakerSuiteService/ListModels', request.url):
        logger.info("   ✨ 匹配到 MakerSuiteService/ListModels 请求，正在尝试修改响应...")
        
        try:
            # 1. 获取原始响应
            response = await route.fetch()
            
            # 原始响应体通常是字节流，需要解码为字符串，然后解析为 JSON
            # 注意：某些 gRPC 请求的响应可能不是标准的 JSON，而是包含前缀的 JSON
            # 比如：`)]}'\n` 这种前缀，需要先处理掉
            response_body_str = await response.text()
            if response_body_str.startswith(")]}'\n"):
                response_body_str = response_body_str[5:] # 移除 gRPC 前缀
                logger.info("   Detected and removed gRPC prefix from response body.")
            
            original_json = json.loads(response_body_str)
            logger.info(f"   原始响应数据: {original_json}")
            # 根据您提供的日志，原始 JSON 数据是一个列表的列表，
            # 实际的模型数组是这个最外层列表的第一个元素。
            if isinstance(original_json, list) and len(original_json) > 0 and isinstance(original_json[0], list):
                modified_json_container = copy.deepcopy(original_json) # 深拷贝整个结构
                models_array = modified_json_container[0] # 实际操作的模型列表是第一个元素
            else:
                logger.error("Unexpected JSON structure: models array not found at the expected position (original_json[0]). Aborting modification.")
                await route.continue_() # 如果结构不符合预期，则继续原始请求
                return # 提前退出函数
            # 确保 models_array 确实是一个列表
            if not isinstance(models_array, list):
                logger.error("Extracted models_array is not a list. Aborting modification.")
                await route.continue_()
                return
            modification_made = False
            # 寻找模板模型 (Python 版)
            template_model = None
            
            # 定义所有需要用到的索引
            required_indices = {NAME_IDX, DISPLAY_NAME_IDX, DESC_IDX, METHODS_IDX}
            # 确保有索引可供计算最大值，如果 required_indices 为空，max() 会报错
            max_required_index = max(required_indices) if required_indices else 0 
            # 优先寻找包含 'flash' 或 'pro' 且所有必要索引都存在且类型正确的模型作为模板
            for m in models_array:
                # 1. 检查是否是列表
                if not isinstance(m, list):
                    continue
                
                # 2. 检查列表长度是否足够包含所有所需的索引
                if len(m) <= max_required_index:
                    # 仅在调试级别记录，避免过多日志
                    logger.debug(f"   Skipping model (length insufficient): {m[NAME_IDX] if len(m) > NAME_IDX else 'Unknown Name'}")
                    continue
                
                # 3. 检查 NAME_IDX 和 METHODS_IDX 处的类型
                if not isinstance(m[NAME_IDX], str) or not isinstance(m[METHODS_IDX], list):
                    logger.debug(f"   Skipping model (type mismatch at NAME_IDX or METHODS_IDX): {m[NAME_IDX]}")
                    continue
                # 4. 检查 DISPLAY_NAME_IDX 和 DESC_IDX 处的类型 (它们可以是字符串或 None)
                if not isinstance(m[DISPLAY_NAME_IDX], (str, type(None))) or \
                   not isinstance(m[DESC_IDX], (str, type(None))):
                    logger.debug(f"   Skipping model (type mismatch at DISPLAY_NAME_IDX or DESC_IDX): {m[NAME_IDX]}")
                    continue
                # 优先条件：名称中包含 'flash' 或 'pro'
                if 'flash' in m[NAME_IDX] or 'pro' in m[NAME_IDX]:
                    template_model = m
                    logger.info(f"   Found preferred template model: {m[NAME_IDX]}")
                    break # 找到首选模板后立即退出循环
            # 如果没有找到首选模板，则找第一个满足基本条件（列表、长度足够、Name和Methods类型正确）的模型作为模板
            if not template_model:
                for m in models_array:
                    if not isinstance(m, list):
                        continue
                    if len(m) <= max_required_index:
                        continue
                    if not isinstance(m[NAME_IDX], str) or not isinstance(m[METHODS_IDX], list):
                        continue
                    if not isinstance(m[DISPLAY_NAME_IDX], (str, type(None))) or \
                       not isinstance(m[DESC_IDX], (str, type(None))):
                        continue
                    
                    template_model = m
                    logger.info(f"   Found fallback template model: {m[NAME_IDX]}")
                    break
            template_name = template_model[NAME_IDX] if template_model and len(template_model) > NAME_IDX else 'unknown'
            if template_model:
                logger.info(f"   Using template: {template_name}")
                # 打印模板模型的关键信息，以便进一步调试
                logger.info(f"   Template model details: Name='{template_model[NAME_IDX]}', DisplayName='{template_model[DISPLAY_NAME_IDX]}', Desc='{template_model[DESC_IDX]}', Methods='{template_model[METHODS_IDX]}'")
            else:
                logger.warning('Could not find a suitable template model array. Cannot inject new models, but can update existing ones.')
            # 逆序遍历 MODELS_TO_INJECT，以便 unshift 后顺序正确
            for model_to_inject in reversed(MODELS_TO_INJECT):
                model_exists = False
                for model in models_array:
                    if isinstance(model, list) and len(model) > NAME_IDX and model[NAME_IDX] == model_to_inject["name"]:
                        model_exists = True
                        break
                if not model_exists:
                    if not template_model:
                        logger.warning(f"Cannot inject {model_to_inject['name']}: No template found.")
                        continue
                    new_model = copy.deepcopy(template_model) # 深拷贝模板
                    # 使用索引修改新模型的属性
                    # 确保索引在列表范围内，避免 IndexError
                    if len(new_model) > NAME_IDX:
                        new_model[NAME_IDX] = model_to_inject["name"]
                    else:
                        # 如果列表不够长，先扩展
                        while len(new_model) <= NAME_IDX:
                            new_model.append(None)
                        new_model[NAME_IDX] = model_to_inject["name"]
                    if len(new_model) > DISPLAY_NAME_IDX:
                        new_model[DISPLAY_NAME_IDX] = model_to_inject["displayName"]
                    else:
                        while len(new_model) <= DISPLAY_NAME_IDX:
                            new_model.append(None)
                        new_model[DISPLAY_NAME_IDX] = model_to_inject["displayName"]
                    if len(new_model) > DESC_IDX:
                        new_model[DESC_IDX] = f"{model_to_inject['description']} (Structure based on {template_name})"
                    else:
                        while len(new_model) <= DESC_IDX:
                            new_model.append(None)
                        new_model[DESC_IDX] = f"{model_to_inject['description']} (Structure based on {template_name})"
                    
                    # 确保 METHODS_IDX 处的元素是列表，并包含必要方法
                    if len(new_model) > METHODS_IDX:
                        if not isinstance(new_model[METHODS_IDX], list) or not new_model[METHODS_IDX]:
                            new_model[METHODS_IDX] = ["generateContent", "countTokens","createCachedContent","batchGenerateContent"]
                    else:
                        # 如果 METHODS_IDX 超出当前列表长度，需要扩展列表
                        while len(new_model) <= METHODS_IDX:
                            new_model.append(None) # 用 None 填充，直到足够长
                        new_model[METHODS_IDX] = ["generateContent", "countTokens","createCachedContent","batchGenerateContent"]
                    models_array.insert(0, new_model) # 添加到列表开头
                    modification_made = True
                    logger.info(f"Successfully INJECTED: {model_to_inject['displayName']}")
                else:
                    # 模型已存在，检查并更新 displayName
                    existing_model = next((model for model in models_array if isinstance(model, list) and len(model) > NAME_IDX and model[NAME_IDX] == model_to_inject["name"]), None)
                    if existing_model and len(existing_model) > DISPLAY_NAME_IDX:
                        current_display_name = existing_model[DISPLAY_NAME_IDX]
                        target_display_name = model_to_inject["displayName"]
                        # 检查是否需要更新 displayName
                        if current_display_name != target_display_name:
                            existing_model[DISPLAY_NAME_IDX] = target_display_name
                            modification_made = True
                            logger.info(f"Updated displayName for existing model {model_to_inject['name']} to: {target_display_name}")
            # 如果有修改，才重新构建响应体并 fulfill
            if modification_made:
                # 将整个 modified_json_container (包含修改后的 models_array) 转换为 JSON 字符串
                body_content = json.dumps(modified_json_container, ensure_ascii=False)
                
                # 使用原始响应的状态码和头信息
                await route.fulfill(
                    status=response.status,
                    headers=response.headers,
                    content_type="application/json",
                    body=body_content.encode('utf-8') # 响应体必须是字节
                )
                logger.info("   ✅ 响应已成功修改并发送。")
            else:
                logger.info("   ℹ️ 模型列表未发生修改，继续原始响应。")
                await route.continue_() # 没有修改则继续原始请求
        except json.JSONDecodeError as jde:
            logger.error(f"   ❌ JSON 解析错误，响应体可能不符合预期 JSON 格式: {jde}. 原始响应文本: {response_body_str[:500]}...", exc_info=True)
            await route.abort() # 解析失败则中止请求
        except Exception as e:
            logger.error(f"   ❌ 拦截请求并修改响应时发生错误: {e}", exc_info=True)
            await route.abort() # 发生其他错误时中止请求
    else:
        # 对于不匹配的请求，继续正常处理
        await route.continue_()



        
async def _initialize_page_logic(browser: AsyncBrowser):
    """初始化页面逻辑，连接到现有浏览器"""
    logger.info("--- 初始化页面逻辑 (连接到现有浏览器) ---")
    temp_context: Optional[AsyncBrowserContext] = None
    storage_state_path_to_use: Optional[str] = None
    launch_mode = os.environ.get('LAUNCH_MODE', 'debug')
    logger.info(f"   检测到启动模式: {launch_mode}")
    loop = asyncio.get_running_loop()
    
    if launch_mode == 'headless' or launch_mode == 'virtual_headless':
        auth_filename = os.environ.get('ACTIVE_AUTH_JSON_PATH')
        if auth_filename:
            constructed_path = auth_filename
            if os.path.exists(constructed_path):
                storage_state_path_to_use = constructed_path
                logger.info(f"   无头模式将使用的认证文件: {constructed_path}")
            else:
                logger.error(f"{launch_mode} 模式认证文件无效或不存在: '{constructed_path}'")
                raise RuntimeError(f"{launch_mode} 模式认证文件无效: '{constructed_path}'")
        else:
            logger.error(f"{launch_mode} 模式需要 ACTIVE_AUTH_JSON_PATH 环境变量，但未设置或为空。")
            raise RuntimeError(f"{launch_mode} 模式需要 ACTIVE_AUTH_JSON_PATH。")
    elif launch_mode == 'debug':
        logger.info(f"   调试模式: 尝试从环境变量 ACTIVE_AUTH_JSON_PATH 加载认证文件...")
        auth_filepath_from_env = os.environ.get('ACTIVE_AUTH_JSON_PATH')
        if auth_filepath_from_env and os.path.exists(auth_filepath_from_env):
            storage_state_path_to_use = auth_filepath_from_env
            logger.info(f"   调试模式将使用的认证文件 (来自环境变量): {storage_state_path_to_use}")
        elif auth_filepath_from_env:
            logger.warning(f"   调试模式下环境变量 ACTIVE_AUTH_JSON_PATH 指向的文件不存在: '{auth_filepath_from_env}'。不加载认证文件。")
        else:
            logger.info("   调试模式下未通过环境变量提供认证文件。将使用浏览器当前状态。")
    elif launch_mode == "direct_debug_no_browser":
        logger.info("   direct_debug_no_browser 模式：不加载 storage_state，不进行浏览器操作。")
    else:
        logger.warning(f"   ⚠️ 警告: 未知的启动模式 '{launch_mode}'。不加载 storage_state。")
    
    try:
        logger.info("创建新的浏览器上下文...")
        context_options: Dict[str, Any] = {'viewport': {'width': 460, 'height': 800}}
        if storage_state_path_to_use:
            context_options['storage_state'] = storage_state_path_to_use
            logger.info(f"   (使用 storage_state='{os.path.basename(storage_state_path_to_use)}')")
        else:
            logger.info("   (不使用 storage_state)")
        
        # 代理设置需要从server模块中获取
        import server
        if server.PLAYWRIGHT_PROXY_SETTINGS:
            context_options['proxy'] = server.PLAYWRIGHT_PROXY_SETTINGS
            logger.info(f"   (浏览器上下文将使用代理: {server.PLAYWRIGHT_PROXY_SETTINGS['server']})")
        else:
            logger.info("   (浏览器上下文不使用显式代理配置)")
        
        context_options['ignore_https_errors'] = True
        logger.info("   (浏览器上下文将忽略 HTTPS 错误)")
        
        temp_context = await browser.new_context(**context_options)

          # 🎯 第三步：在这里设置请求路由拦截 🎯
        # 拦截 URL 模式：匹配包含 'MakerSuiteService/ListModels' 的任何 URL
        URL_TO_INTERCEPT_PATTERN = re.compile(r'MakerSuiteService/ListModels')
        # 导入 intercept_and_modify_response 函数 (如果它在同一文件，则不需要显式导入)
        # 如果 intercept_and_modify_response 在其他模块，需要在此处导入
        # from .your_module_name import intercept_and_modify_response 
        await temp_context.route(URL_TO_INTERCEPT_PATTERN, intercept_and_modify_response)
        logger.info(f"   已设置请求拦截器，用于修改匹配 '{URL_TO_INTERCEPT_PATTERN.pattern}' 的响应。")


        found_page: Optional[AsyncPage] = None
        pages = temp_context.pages
        target_url_base = f"https://{AI_STUDIO_URL_PATTERN}"
        target_full_url = f"{target_url_base}prompts/new_chat"
        login_url_pattern = 'accounts.google.com'
        current_url = ""
        
        # 导入_handle_model_list_response - 需要延迟导入避免循环引用
        from .operations import _handle_model_list_response
        
        for p_iter in pages:
            try:
                page_url_to_check = p_iter.url
                if not p_iter.is_closed() and target_url_base in page_url_to_check and "/prompts/" in page_url_to_check:
                    found_page = p_iter
                    current_url = page_url_to_check
                    logger.info(f"   找到已打开的 AI Studio 页面: {current_url}")
                    if found_page:
                        logger.info(f"   为已存在的页面 {found_page.url} 添加模型列表响应监听器。")
                        found_page.on("response", _handle_model_list_response)
                    break
            except PlaywrightAsyncError as pw_err_url:
                logger.warning(f"   检查页面 URL 时出现 Playwright 错误: {pw_err_url}")
            except AttributeError as attr_err_url:
                logger.warning(f"   检查页面 URL 时出现属性错误: {attr_err_url}")
            except Exception as e_url_check:
                logger.warning(f"   检查页面 URL 时出现其他未预期错误: {e_url_check} (类型: {type(e_url_check).__name__})")
        
        if not found_page:
            logger.info(f"-> 未找到合适的现有页面，正在打开新页面并导航到 {target_full_url}...")
            found_page = await temp_context.new_page()
            if found_page:
                logger.info(f"   为新创建的页面添加模型列表响应监听器 (导航前)。")
                found_page.on("response", _handle_model_list_response)
            try:
                await found_page.goto(target_full_url, wait_until="domcontentloaded", timeout=90000)
                current_url = found_page.url
                logger.info(f"-> 新页面导航尝试完成。当前 URL: {current_url}")
            except Exception as new_page_nav_err:
                # 导入save_error_snapshot函数
                from .operations import save_error_snapshot
                await save_error_snapshot("init_new_page_nav_fail")
                error_str = str(new_page_nav_err)
                if "NS_ERROR_NET_INTERRUPT" in error_str:
                    logger.error("\n" + "="*30 + " 网络导航错误提示 " + "="*30)
                    logger.error(f"❌ 导航到 '{target_full_url}' 失败，出现网络中断错误 (NS_ERROR_NET_INTERRUPT)。")
                    logger.error("   这通常表示浏览器在尝试加载页面时连接被意外断开。")
                    logger.error("   可能的原因及排查建议:")
                    logger.error("     1. 网络连接: 请检查你的本地网络连接是否稳定，并尝试在普通浏览器中访问目标网址。")
                    logger.error("     2. AI Studio 服务: 确认 aistudio.google.com 服务本身是否可用。")
                    logger.error("     3. 防火墙/代理/VPN: 检查本地防火墙、杀毒软件、代理或 VPN 设置。")
                    logger.error("     4. Camoufox 服务: 确认 launch_camoufox.py 脚本是否正常运行。")
                    logger.error("     5. 系统资源问题: 确保系统有足够的内存和 CPU 资源。")
                    logger.error("="*74 + "\n")
                raise RuntimeError(f"导航新页面失败: {new_page_nav_err}") from new_page_nav_err
        
        if login_url_pattern in current_url:
            if launch_mode == 'headless':
                logger.error("无头模式下检测到重定向至登录页面，认证可能已失效。请更新认证文件。")
                raise RuntimeError("无头模式认证失败，需要更新认证文件。")
            else:
                print(f"\n{'='*20} 需要操作 {'='*20}", flush=True)
                login_prompt = "   检测到可能需要登录。如果浏览器显示登录页面，请在浏览器窗口中完成 Google 登录，然后在此处按 Enter 键继续..."
                print(USER_INPUT_START_MARKER_SERVER, flush=True)
                await loop.run_in_executor(None, input, login_prompt)
                print(USER_INPUT_END_MARKER_SERVER, flush=True)
                logger.info("   用户已操作，正在检查登录状态...")
                try:
                    await found_page.wait_for_url(f"**/{AI_STUDIO_URL_PATTERN}**", timeout=180000)
                    current_url = found_page.url
                    if login_url_pattern in current_url:
                        logger.error("手动登录尝试后，页面似乎仍停留在登录页面。")
                        raise RuntimeError("手动登录尝试后仍在登录页面。")
                    logger.info("   ✅ 登录成功！请不要操作浏览器窗口，等待后续提示。")

                    # 等待模型列表响应，确认登录成功
                    await _wait_for_model_list_and_handle_auth_save(temp_context, launch_mode, loop)
                except Exception as wait_login_err:
                    from .operations import save_error_snapshot
                    await save_error_snapshot("init_login_wait_fail")
                    logger.error(f"登录提示后未能检测到 AI Studio URL 或保存状态时出错: {wait_login_err}", exc_info=True)
                    raise RuntimeError(f"登录提示后未能检测到 AI Studio URL: {wait_login_err}") from wait_login_err
        elif target_url_base not in current_url or "/prompts/" not in current_url:
            from .operations import save_error_snapshot
            await save_error_snapshot("init_unexpected_page")
            logger.error(f"初始导航后页面 URL 意外: {current_url}。期望包含 '{target_url_base}' 和 '/prompts/'。")
            raise RuntimeError(f"初始导航后出现意外页面: {current_url}。")
        
        logger.info(f"-> 确认当前位于 AI Studio 对话页面: {current_url}")
        await found_page.bring_to_front()
        
        try:
            input_wrapper_locator = found_page.locator('ms-prompt-input-wrapper')
            await expect_async(input_wrapper_locator).to_be_visible(timeout=35000)
            await expect_async(found_page.locator(INPUT_SELECTOR)).to_be_visible(timeout=10000)
            logger.info("-> ✅ 核心输入区域可见。")
            
            model_name_locator = found_page.locator('mat-select[data-test-ms-model-selector] div.model-option-content span.gmat-body-medium')
            try:
                model_name_on_page = await model_name_locator.first.inner_text(timeout=5000)
                logger.info(f"-> 🤖 页面检测到的当前模型: {model_name_on_page}")
            except PlaywrightAsyncError as e:
                logger.error(f"获取模型名称时出错 (model_name_locator): {e}")
                raise
            
            result_page_instance = found_page
            result_page_ready = True
            logger.info(f"✅ 页面逻辑初始化成功。")
            return result_page_instance, result_page_ready
        except Exception as input_visible_err:
            from .operations import save_error_snapshot
            await save_error_snapshot("init_fail_input_timeout")
            logger.error(f"页面初始化失败：核心输入区域未在预期时间内变为可见。最后的 URL 是 {found_page.url}", exc_info=True)
            raise RuntimeError(f"页面初始化失败：核心输入区域未在预期时间内变为可见。最后的 URL 是 {found_page.url}") from input_visible_err
    except Exception as e_init_page:
        logger.critical(f"❌ 页面逻辑初始化期间发生严重意外错误: {e_init_page}", exc_info=True)
        if temp_context:
            try:
                logger.info(f"   尝试关闭临时的浏览器上下文 due to initialization error.")
                await temp_context.close()
                logger.info("   ✅ 临时浏览器上下文已关闭。")
            except Exception as close_err:
                 logger.warning(f"   ⚠️ 关闭临时浏览器上下文时出错: {close_err}")
        from .operations import save_error_snapshot
        await save_error_snapshot("init_unexpected_error")
        raise RuntimeError(f"页面初始化意外错误: {e_init_page}") from e_init_page


async def _close_page_logic():
    """关闭页面逻辑"""
    # 需要访问全局变量
    import server
    logger.info("--- 运行页面逻辑关闭 --- ")
    if server.page_instance and not server.page_instance.is_closed():
        try:
            await server.page_instance.close()
            logger.info("   ✅ 页面已关闭")
        except PlaywrightAsyncError as pw_err:
            logger.warning(f"   ⚠️ 关闭页面时出现Playwright错误: {pw_err}")
        except asyncio.TimeoutError as timeout_err:
            logger.warning(f"   ⚠️ 关闭页面时超时: {timeout_err}")
        except Exception as other_err:
            logger.error(f"   ⚠️ 关闭页面时出现意外错误: {other_err} (类型: {type(other_err).__name__})", exc_info=True)
    server.page_instance = None
    server.is_page_ready = False
    logger.info("页面逻辑状态已重置。")
    return None, False


async def signal_camoufox_shutdown():
    """发送关闭信号到Camoufox服务器"""
    logger.info("   尝试发送关闭信号到 Camoufox 服务器 (此功能可能已由父进程处理)...")
    ws_endpoint = os.environ.get('CAMOUFOX_WS_ENDPOINT')
    if not ws_endpoint:
        logger.warning("   ⚠️ 无法发送关闭信号：未找到 CAMOUFOX_WS_ENDPOINT 环境变量。")
        return

    # 需要访问全局浏览器实例
    import server
    if not server.browser_instance or not server.browser_instance.is_connected():
        logger.warning("   ⚠️ 浏览器实例已断开或未初始化，跳过关闭信号发送。")
        return
    try:
        await asyncio.sleep(0.2)
        logger.info("   ✅ (模拟) 关闭信号已处理。")
    except Exception as e:
        logger.error(f"   ⚠️ 发送关闭信号过程中捕获异常: {e}", exc_info=True)


async def _wait_for_model_list_and_handle_auth_save(temp_context, launch_mode, loop):
    """等待模型列表响应并处理认证保存"""
    import server

    # 等待模型列表响应，确认登录成功
    logger.info("   等待模型列表响应以确认登录成功...")
    try:
        # 等待模型列表事件，最多等待30秒
        await asyncio.wait_for(server.model_list_fetch_event.wait(), timeout=30.0)
        logger.info("   ✅ 检测到模型列表响应，登录确认成功！")
    except asyncio.TimeoutError:
        logger.warning("   ⚠️ 等待模型列表响应超时，但继续处理认证保存...")

    # 检查是否启用自动确认
    if AUTO_CONFIRM_LOGIN:
        print("\n" + "="*50, flush=True)
        print("   ✅ 登录成功！检测到模型列表响应。", flush=True)
        print("   🤖 自动确认模式已启用，将自动保存认证状态...", flush=True)

        # 自动保存认证状态
        await _handle_auth_file_save_auto(temp_context)
        print("="*50 + "\n", flush=True)
        return

    # 手动确认模式
    print("\n" + "="*50, flush=True)
    print("   【用户交互】需要您的输入!", flush=True)
    print("   ✅ 登录成功！检测到模型列表响应。", flush=True)

    should_save_auth_choice = ''
    if AUTO_SAVE_AUTH and launch_mode == 'debug':
        logger.info("   自动保存认证模式已启用，将自动保存认证状态...")
        should_save_auth_choice = 'y'
    else:
        save_auth_prompt = "   是否要将当前的浏览器认证状态保存到文件？ (y/N): "
        print(USER_INPUT_START_MARKER_SERVER, flush=True)
        try:
            auth_save_input_future = loop.run_in_executor(None, input, save_auth_prompt)
            should_save_auth_choice = await asyncio.wait_for(auth_save_input_future, timeout=AUTH_SAVE_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"   输入等待超时({AUTH_SAVE_TIMEOUT}秒)。默认不保存认证状态。", flush=True)
            should_save_auth_choice = 'n'
        finally:
            print(USER_INPUT_END_MARKER_SERVER, flush=True)

    if should_save_auth_choice.strip().lower() == 'y':
        await _handle_auth_file_save(temp_context, loop)
    else:
        print("   好的，不保存认证状态。", flush=True)

    print("="*50 + "\n", flush=True)


async def _handle_auth_file_save(temp_context, loop):
    """处理认证文件保存（手动模式）"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
    default_auth_filename = f"auth_state_{int(time.time())}.json"

    print(USER_INPUT_START_MARKER_SERVER, flush=True)
    filename_prompt_str = f"   请输入保存的文件名 (默认为: {default_auth_filename}，输入 'cancel' 取消保存): "
    chosen_auth_filename = ''

    try:
        filename_input_future = loop.run_in_executor(None, input, filename_prompt_str)
        chosen_auth_filename = await asyncio.wait_for(filename_input_future, timeout=AUTH_SAVE_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"   输入文件名等待超时({AUTH_SAVE_TIMEOUT}秒)。将使用默认文件名: {default_auth_filename}", flush=True)
        chosen_auth_filename = default_auth_filename
    finally:
        print(USER_INPUT_END_MARKER_SERVER, flush=True)

    # 检查用户是否选择取消
    if chosen_auth_filename.strip().lower() == 'cancel':
        print("   用户选择取消保存认证状态。", flush=True)
        return

    final_auth_filename = chosen_auth_filename.strip() or default_auth_filename
    if not final_auth_filename.endswith(".json"):
        final_auth_filename += ".json"

    auth_save_path = os.path.join(SAVED_AUTH_DIR, final_auth_filename)

    try:
        await temp_context.storage_state(path=auth_save_path)
        print(f"   ✅ 认证状态已成功保存到: {auth_save_path}", flush=True)
    except Exception as save_state_err:
        logger.error(f"   ❌ 保存认证状态失败: {save_state_err}", exc_info=True)
        print(f"   ❌ 保存认证状态失败: {save_state_err}", flush=True)


async def _handle_auth_file_save_auto(temp_context):
    """处理认证文件保存（自动模式）"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)

    # 生成基于时间戳的文件名
    timestamp = int(time.time())
    auto_auth_filename = f"auth_auto_{timestamp}.json"
    auth_save_path = os.path.join(SAVED_AUTH_DIR, auto_auth_filename)

    try:
        await temp_context.storage_state(path=auth_save_path)
        print(f"   ✅ 认证状态已自动保存到: {auth_save_path}", flush=True)
        logger.info(f"   自动保存认证状态成功: {auth_save_path}")
    except Exception as save_state_err:
        logger.error(f"   ❌ 自动保存认证状态失败: {save_state_err}", exc_info=True)
        print(f"   ❌ 自动保存认证状态失败: {save_state_err}", flush=True)