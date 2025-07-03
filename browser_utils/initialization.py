# --- browser_utils/initialization.py ---
# 浏览器初始化相关功能模块

import asyncio
import os
import time
import json
import logging
from typing import Optional, Any, Dict, Tuple

from playwright.async_api import Page as AsyncPage, Browser as AsyncBrowser, BrowserContext as AsyncBrowserContext, Error as PlaywrightAsyncError, expect as expect_async

# 导入配置和模型
from config import *
from models import ClientDisconnectedError
from .resource_manager import get_resource_manager, BrowserResourceManager

logger = logging.getLogger("AIStudioProxyServer")


async def _setup_network_interception_and_scripts(context: AsyncBrowserContext):
    """设置网络拦截和脚本注入"""
    try:
        from config.settings import ENABLE_SCRIPT_INJECTION

        if not ENABLE_SCRIPT_INJECTION:
            logger.info("脚本注入功能已禁用")
            return

        # 设置网络拦截
        await _setup_model_list_interception(context)

        # 可选：仍然注入脚本作为备用方案
        await _add_init_scripts_to_context(context)

    except Exception as e:
        logger.error(f"设置网络拦截和脚本注入时发生错误: {e}")


async def _setup_model_list_interception(context: AsyncBrowserContext):
    """设置模型列表网络拦截"""
    try:
        async def handle_model_list_route(route):
            """处理模型列表请求的路由"""
            request = route.request

            # 检查是否是模型列表请求
            if 'alkalimakersuite' in request.url and 'ListModels' in request.url:
                logger.info(f"🔍 拦截到模型列表请求: {request.url}")

                # 继续原始请求
                response = await route.fetch()

                # 获取原始响应
                original_body = await response.body()

                # 修改响应
                modified_body = await _modify_model_list_response(original_body, request.url)

                # 返回修改后的响应
                await route.fulfill(
                    response=response,
                    body=modified_body
                )
            else:
                # 对于其他请求，直接继续
                await route.continue_()

        # 注册路由拦截器
        await context.route("**/*", handle_model_list_route)
        logger.info("✅ 已设置模型列表网络拦截")

    except Exception as e:
        logger.error(f"设置模型列表网络拦截时发生错误: {e}")


async def _modify_model_list_response(original_body: bytes, url: str) -> bytes:
    """修改模型列表响应"""
    try:
        # 解码响应体
        original_text = original_body.decode('utf-8')

        # 处理反劫持前缀
        ANTI_HIJACK_PREFIX = ")]}'\n"
        has_prefix = False
        if original_text.startswith(ANTI_HIJACK_PREFIX):
            original_text = original_text[len(ANTI_HIJACK_PREFIX):]
            has_prefix = True

        # 解析JSON
        import json
        json_data = json.loads(original_text)

        # 注入模型
        modified_data = await _inject_models_to_response(json_data, url)

        # 序列化回JSON
        modified_text = json.dumps(modified_data, separators=(',', ':'))

        # 重新添加前缀
        if has_prefix:
            modified_text = ANTI_HIJACK_PREFIX + modified_text

        logger.info("✅ 成功修改模型列表响应")
        return modified_text.encode('utf-8')

    except Exception as e:
        logger.error(f"修改模型列表响应时发生错误: {e}")
        return original_body


async def _inject_models_to_response(json_data: dict, url: str) -> dict:
    """向响应中注入模型"""
    try:
        from .operations import _get_injected_models

        # 获取要注入的模型
        injected_models = _get_injected_models()
        if not injected_models:
            logger.info("没有要注入的模型")
            return json_data

        # 查找模型数组
        models_array = _find_model_list_array(json_data)
        if not models_array:
            logger.warning("未找到模型数组结构")
            return json_data

        # 找到模板模型
        template_model = _find_template_model(models_array)
        if not template_model:
            logger.warning("未找到模板模型")
            return json_data

        # 注入模型
        for model in reversed(injected_models):  # 反向以保持顺序
            model_name = model['raw_model_path']

            # 检查模型是否已存在
            if not any(m[0] == model_name for m in models_array if isinstance(m, list) and len(m) > 0):
                # 创建新模型条目
                new_model = json.loads(json.dumps(template_model))  # 深拷贝
                new_model[0] = model_name  # name
                new_model[3] = model['display_name']  # display name
                new_model[4] = model['description']  # description

                # 添加特殊标记，表示这是通过网络拦截注入的模型
                # 在模型数组的末尾添加一个特殊字段作为标记
                if len(new_model) > 10:  # 确保有足够的位置
                    new_model.append("__NETWORK_INJECTED__")  # 添加网络注入标记
                else:
                    # 如果模型数组长度不够，扩展到足够长度
                    while len(new_model) <= 10:
                        new_model.append(None)
                    new_model.append("__NETWORK_INJECTED__")

                # 添加到开头
                models_array.insert(0, new_model)
                logger.info(f"✅ 网络拦截注入模型: {model['display_name']}")

        return json_data

    except Exception as e:
        logger.error(f"注入模型到响应时发生错误: {e}")
        return json_data


def _find_model_list_array(obj):
    """递归查找模型列表数组"""
    if not obj:
        return None

    # 检查是否是模型数组
    if isinstance(obj, list) and len(obj) > 0:
        if all(isinstance(item, list) and len(item) > 0 and
               isinstance(item[0], str) and item[0].startswith('models/')
               for item in obj):
            return obj

    # 递归搜索
    if isinstance(obj, dict):
        for value in obj.values():
            result = _find_model_list_array(value)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_model_list_array(item)
            if result:
                return result

    return None


def _find_template_model(models_array):
    """查找模板模型"""
    if not models_array:
        return None

    # 寻找包含 'flash' 或 'pro' 的模型作为模板
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            model_name = model[0] if len(model) > 0 else ""
            if 'flash' in model_name.lower() or 'pro' in model_name.lower():
                return model

    # 如果没找到，返回第一个有效模型
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            return model

    return None


async def _add_init_scripts_to_context(context: AsyncBrowserContext):
    """在浏览器上下文中添加初始化脚本（备用方案）"""
    try:
        from config.settings import USERSCRIPT_PATH

        # 检查脚本文件是否存在
        if not os.path.exists(USERSCRIPT_PATH):
            logger.info(f"脚本文件不存在，跳过脚本注入: {USERSCRIPT_PATH}")
            return

        # 读取脚本内容
        with open(USERSCRIPT_PATH, 'r', encoding='utf-8') as f:
            script_content = f.read()

        # 清理UserScript头部
        cleaned_script = _clean_userscript_headers(script_content)

        # 添加到上下文的初始化脚本
        await context.add_init_script(cleaned_script)
        logger.info(f"✅ 已将脚本添加到浏览器上下文初始化脚本: {os.path.basename(USERSCRIPT_PATH)}")

    except Exception as e:
        logger.error(f"添加初始化脚本到上下文时发生错误: {e}")


def _clean_userscript_headers(script_content: str) -> str:
    """清理UserScript头部信息"""
    lines = script_content.split('\n')
    cleaned_lines = []
    in_userscript_block = False

    for line in lines:
        if line.strip().startswith('// ==UserScript=='):
            in_userscript_block = True
            continue
        elif line.strip().startswith('// ==/UserScript=='):
            in_userscript_block = False
            continue
        elif in_userscript_block:
            continue
        else:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


async def _initialize_page_logic(browser: AsyncBrowser):
    """初始化页面逻辑，连接到现有浏览器"""
    logger.info("--- 初始化页面逻辑 (连接到现有浏览器) ---")

    # 使用资源管理器
    resource_manager = get_resource_manager()
    await resource_manager.set_browser(browser)

    try:
        return await _initialize_page_with_resource_manager(resource_manager)
    except Exception as e:
        logger.critical(f"❌ 页面逻辑初始化期间发生严重意外错误: {e}", exc_info=True)
        # 资源管理器会自动清理资源
        raise


async def _initialize_page_with_resource_manager(resource_manager: BrowserResourceManager):
    """使用资源管理器初始化页面"""
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

    # 创建持久的浏览器上下文（不使用上下文管理器，因为需要保持页面活跃）
    if not resource_manager.browser:
        raise RuntimeError("浏览器未连接，无法创建上下文")

    # 安全地检查浏览器连接状态
    try:
        is_connected = resource_manager.browser.is_connected()
        if asyncio.iscoroutine(is_connected):
            is_connected = await is_connected
        if not is_connected:
            raise RuntimeError("浏览器未连接，无法创建上下文")
    except Exception as e:
        raise RuntimeError(f"检查浏览器连接状态失败: {e}")

    temp_context = await resource_manager.browser.new_context(**context_options)
    async with resource_manager._lock:
        resource_manager._contexts.add(temp_context)
    logger.info("✅ 浏览器上下文已创建（持久模式）")

    try:
        # 设置网络拦截和脚本注入
        await _setup_network_interception_and_scripts(temp_context)

        # 在上下文中进行页面操作
        return await _initialize_page_in_context(temp_context, loop)
    except Exception as e:
        # 如果初始化失败，清理上下文
        await resource_manager._close_context_safe(temp_context)
        raise


async def _initialize_page_in_context(temp_context: AsyncBrowserContext, loop) -> Tuple[AsyncPage, bool]:
    """在给定的浏览器上下文中初始化页面"""
    found_page: Optional[AsyncPage] = None
    pages = temp_context.pages
    target_url_base = f"https://{AI_STUDIO_URL_PATTERN}"
    target_full_url = f"{target_url_base}prompts/new_chat"
    login_url_pattern = 'accounts.google.com'
    current_url = ""
    launch_mode = os.environ.get('LAUNCH_MODE', 'debug')

    # 导入_handle_model_list_response - 需要延迟导入避免循环引用
    from .operations import _handle_model_list_response

    # 查找现有页面
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

    # 如果没有找到现有页面，创建新页面
    if not found_page:
        logger.info(f"-> 未找到合适的现有页面，正在打开新页面并导航到 {target_full_url}...")
        found_page = await temp_context.new_page()
        if found_page:
            # 将页面注册到资源管理器但不自动关闭
            from .resource_manager import get_resource_manager
            resource_manager = get_resource_manager()
            async with resource_manager._lock:
                resource_manager._pages.add(found_page)
            logger.info("✅ 页面已创建并注册到资源管理器（持久模式）")
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

    # 简化的页面验证逻辑
    if found_page:
        current_url = found_page.url
        logger.info(f"-> 确认当前位于页面: {current_url}")

        # 基本的页面可用性检查
        try:
            await found_page.bring_to_front()
            input_wrapper_locator = found_page.locator('ms-prompt-input-wrapper')
            await expect_async(input_wrapper_locator).to_be_visible(timeout=35000)
            logger.info("-> ✅ 核心输入区域可见。")
            logger.info(f"✅ 页面逻辑初始化成功。")
            return found_page, True
        except Exception as validation_err:
            from .operations import save_error_snapshot
            await save_error_snapshot("init_fail_validation")
            logger.error(f"页面验证失败: {validation_err}", exc_info=True)
            raise RuntimeError(f"页面验证失败: {validation_err}") from validation_err
    else:
        raise RuntimeError("无法创建或找到有效的页面")


async def _close_page_logic():
    """关闭页面逻辑 - 使用资源管理器"""
    logger.info("--- 运行页面逻辑关闭 --- ")

    try:
        # 使用资源管理器关闭所有资源
        resource_manager = get_resource_manager()
        await resource_manager.close_all()
        logger.info("   ✅ 所有浏览器资源已通过资源管理器关闭")

        # 重置全局状态
        import server
        server.page_instance = None
        server.is_page_ready = False
        server.is_browser_connected = False
        logger.info("页面逻辑状态已重置。")

    except Exception as e:
        logger.error(f"   ⚠️ 关闭页面逻辑时出现错误: {e}", exc_info=True)

    return None, False


async def signal_camoufox_shutdown():
    """发送关闭信号到Camoufox服务器并清理资源"""
    logger.info("   尝试发送关闭信号到 Camoufox 服务器...")

    try:
        # 首先清理所有浏览器资源
        resource_manager = get_resource_manager()
        await resource_manager.close_all()
        logger.info("   ✅ 浏览器资源已清理")

        # 模拟关闭信号处理
        await asyncio.sleep(0.2)
        logger.info("   ✅ 关闭信号已处理。")

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