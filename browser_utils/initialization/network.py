# --- browser_utils/initialization/network.py ---
import asyncio
import json
import logging

from playwright.async_api import BrowserContext as AsyncBrowserContext

from .scripts import add_init_scripts_to_context

logger = logging.getLogger("AIStudioProxyServer")


async def setup_network_interception_and_scripts(context: AsyncBrowserContext):
    """设置网络拦截和脚本注入"""
    try:
        from config.settings import ENABLE_SCRIPT_INJECTION

        if not ENABLE_SCRIPT_INJECTION:
            logger.debug("[Network] 脚本注入功能已禁用")
            return

        # 设置网络拦截
        await _setup_model_list_interception(context)

        # 可选：仍然注入脚本作为备用方案
        await add_init_scripts_to_context(context)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"设置网络拦截和脚本注入时发生错误: {e}")


async def _setup_model_list_interception(context: AsyncBrowserContext):
    """设置模型列表网络拦截"""
    try:

        async def handle_model_list_route(route):
            """处理模型列表请求的路由"""
            request = route.request

            # 检查是否是模型列表请求
            if "alkalimakersuite" in request.url and "ListModels" in request.url:
                logger.info(f"拦截到模型列表请求: {request.url}")

                # 继续原始请求
                response = await route.fetch()

                # 获取原始响应
                original_body = await response.body()

                # 修改响应
                modified_body = await _modify_model_list_response(
                    original_body, request.url
                )

                # 返回修改后的响应
                await route.fulfill(response=response, body=modified_body)
            else:
                # 对于其他请求，直接继续
                await route.continue_()

        # 注册路由拦截器
        await context.route("**/*", handle_model_list_route)
        logger.info("已设置模型列表网络拦截")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"设置模型列表网络拦截时发生错误: {e}")


async def _modify_model_list_response(original_body: bytes, url: str) -> bytes:
    """修改模型列表响应"""
    try:
        # 解码响应体
        original_text = original_body.decode("utf-8")

        # 处理反劫持前缀
        ANTI_HIJACK_PREFIX = ")]}'\n"
        has_prefix = False
        if original_text.startswith(ANTI_HIJACK_PREFIX):
            original_text = original_text[len(ANTI_HIJACK_PREFIX) :]
            has_prefix = True

        # 解析JSON
        json_data = json.loads(original_text)

        # 注入模型
        modified_data = await _inject_models_to_response(json_data, url)

        # 序列化回JSON
        modified_text = json.dumps(modified_data, separators=(",", ":"))

        # 重新添加前缀
        if has_prefix:
            modified_text = ANTI_HIJACK_PREFIX + modified_text

        logger.info("成功修改模型列表响应")
        return modified_text.encode("utf-8")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"修改模型列表响应时发生错误: {e}")
        return original_body


async def _inject_models_to_response(json_data: dict, url: str) -> dict:
    """向响应中注入模型"""
    try:
        from browser_utils.operations import _get_injected_models

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
            model_name = model["raw_model_path"]

            # 检查模型是否已存在
            if not any(
                m[0] == model_name
                for m in models_array
                if isinstance(m, list) and len(m) > 0
            ):
                # 创建新模型条目
                new_model = json.loads(json.dumps(template_model))  # 深拷贝
                new_model[0] = model_name  # name
                new_model[3] = model["display_name"]  # display name
                new_model[4] = model["description"]  # description

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
                logger.info(f"网络拦截注入模型: {model['display_name']}")

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
        if all(
            isinstance(item, list)
            and len(item) > 0
            and isinstance(item[0], str)
            and item[0].startswith("models/")
            for item in obj
        ):
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
    """查找模板模型，优先选择 flash，其次 pro，最后任意有效模型"""
    if not models_array:
        return None

    # 第一优先：寻找 flash 模型
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            model_name = model[0] if len(model) > 0 else ""
            if "flash" in model_name.lower():
                return model

    # 第二优先：寻找 pro 模型
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            model_name = model[0] if len(model) > 0 else ""
            if "pro" in model_name.lower():
                return model

    # 最后：返回第一个有效模型
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            return model

    return None
