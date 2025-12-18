# --- browser_utils/operations_modules/parsers.py ---
import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from config import (
    DEBUG_LOGS_ENABLED,
    MODELS_ENDPOINT_URL_CONTAINS,
)

logger = logging.getLogger("AIStudioProxyServer")


def _parse_userscript_models(script_content: str):
    """从油猴脚本中解析模型列表 - 使用JSON解析方式"""
    try:
        # 查找脚本版本号
        version_pattern = r'const\s+SCRIPT_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]'
        version_match = re.search(version_pattern, script_content)
        script_version = version_match.group(1) if version_match else "v1.6"

        # 查找 MODELS_TO_INJECT 数组的内容
        models_array_pattern = r"const\s+MODELS_TO_INJECT\s*=\s*(\[.*?\]);"
        models_match = re.search(models_array_pattern, script_content, re.DOTALL)

        if not models_match:
            logger.warning("未找到 MODELS_TO_INJECT 数组")
            return []

        models_js_code = models_match.group(1)

        # 将JavaScript数组转换为JSON格式
        # 1. 替换模板字符串中的变量
        models_js_code = models_js_code.replace("${SCRIPT_VERSION}", script_version)

        # 2. 移除JavaScript注释
        models_js_code = re.sub(r"//.*?$", "", models_js_code, flags=re.MULTILINE)

        # 3. 将JavaScript对象转换为JSON格式
        # 移除尾随逗号
        models_js_code = re.sub(r",\s*([}\]])", r"\1", models_js_code)

        # 替换单引号为双引号
        models_js_code = re.sub(r"(\w+):\s*'([^']*)'", r'"\1": "\2"', models_js_code)
        # 替换反引号为双引号
        models_js_code = re.sub(r"(\w+):\s*`([^`]*)`", r'"\1": "\2"', models_js_code)
        # 确保属性名用双引号
        models_js_code = re.sub(r"(\w+):", r'"\1":', models_js_code)

        # 4. 解析JSON
        import json

        models_data = json.loads(models_js_code)

        models = []
        for model_obj in models_data:
            if isinstance(model_obj, dict) and "name" in model_obj:
                models.append(
                    {
                        "name": model_obj.get("name", ""),
                        "displayName": model_obj.get("displayName", ""),
                        "description": model_obj.get("description", ""),
                    }
                )

        logger.info(f"成功解析 {len(models)} 个模型从油猴脚本")
        return models

    except Exception as e:
        logger.error(f"解析油猴脚本模型列表失败: {e}", exc_info=True)
        return []


def _get_injected_models():
    """从油猴脚本中获取注入的模型列表，转换为API格式"""
    try:
        # 直接读取环境变量，避免复杂的导入
        enable_injection = os.environ.get(
            "ENABLE_SCRIPT_INJECTION", "true"
        ).lower() in ("true", "1", "yes")

        if not enable_injection:
            return []

        # 获取脚本文件路径
        script_path = os.environ.get("USERSCRIPT_PATH", "browser_utils/more_models.js")

        # 检查脚本文件是否存在
        if not os.path.exists(script_path):
            # 脚本文件不存在，静默返回空列表
            return []

        # 读取油猴脚本内容
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()

        # 从脚本中解析模型列表
        models = _parse_userscript_models(script_content)

        if not models:
            return []

        # 转换为API格式
        injected_models = []
        for model in models:
            model_name = model.get("name", "")
            if not model_name:
                continue  # 跳过没有名称的模型

            if model_name.startswith("models/"):
                simple_id = model_name[7:]  # 移除 'models/' 前缀
            else:
                simple_id = model_name

            display_name = model.get(
                "displayName", model.get("display_name", simple_id)
            )
            description = model.get("description", f"Injected model: {simple_id}")

            # 注意：不再清理显示名称，保留原始的emoji和版本信息

            model_entry = {
                "id": simple_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "ai_studio_injected",
                "display_name": display_name,
                "description": description,
                "raw_model_path": model_name,
                "default_temperature": 1.0,
                "default_max_output_tokens": 65536,
                "supported_max_output_tokens": 65536,
                "default_top_p": 0.95,
                "injected": True,  # 标记为注入的模型
            }
            injected_models.append(model_entry)

        return injected_models

    except Exception:
        # 静默处理错误，不输出日志，返回空列表
        return []


async def _handle_model_list_response(response: Any):
    """处理模型列表响应"""
    # 需要访问全局变量
    from api_utils.server_state import state

    getattr(state, "global_model_list_raw_json", None)
    getattr(state, "parsed_model_list", [])
    model_list_fetch_event = getattr(state, "model_list_fetch_event", None)
    excluded_model_ids = getattr(state, "excluded_model_ids", set())

    if MODELS_ENDPOINT_URL_CONTAINS in response.url and response.ok:
        # 检查是否在登录流程中
        launch_mode = os.environ.get("LAUNCH_MODE", "debug")
        is_in_login_flow = launch_mode in ["debug"] and not getattr(
            state, "is_page_ready", False
        )

        if is_in_login_flow:
            # 在登录流程中，静默处理，不输出干扰信息
            pass  # 静默处理，避免干扰用户输入
        else:
            logger.debug(f"[Network] 捕获模型列表响应 ({response.status} OK)")
        try:
            data = await response.json()
            models_array_container = None
            if isinstance(data, list) and data:
                if (
                    isinstance(data[0], list)
                    and data[0]
                    and isinstance(data[0][0], list)
                ):
                    # [Parse] log moved to count change check
                    models_array_container = data[0]
                elif (
                    isinstance(data[0], list)
                    and data[0]
                    and isinstance(data[0][0], str)
                ):
                    # [Parse] log moved to count change check
                    models_array_container = data
                elif isinstance(data[0], dict):
                    # [Parse] log moved to count change check
                    models_array_container = data
                else:
                    logger.warning(
                        f"未知的列表嵌套结构。data[0] 类型: {type(data[0]) if data else 'N/A'}。data[0] 预览: {str(data[0])[:200] if data else 'N/A'}"
                    )
            elif isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    models_array_container = data["data"]
                elif "models" in data and isinstance(data["models"], list):
                    models_array_container = data["models"]
                else:
                    for key, value in data.items():
                        if (
                            isinstance(value, list)
                            and len(value) > 0
                            and isinstance(value[0], (dict, list))
                        ):
                            models_array_container = value
                            logger.info(
                                f"模型列表数据在 '{key}' 键下通过启发式搜索找到。"
                            )
                            break
                    if models_array_container is None:
                        logger.warning("在字典响应中未能自动定位模型列表数组。")
                        if (
                            model_list_fetch_event
                            and not model_list_fetch_event.is_set()
                        ):
                            model_list_fetch_event.set()
                        return
            else:
                logger.warning(
                    f"接收到的模型列表数据既不是列表也不是字典: {type(data)}"
                )
                if model_list_fetch_event and not model_list_fetch_event.is_set():
                    model_list_fetch_event.set()
                return

            if models_array_container is not None:
                new_parsed_list = []
                excluded_during_parse: list[str] = []  # 收集被排除的模型ID
                for entry_in_container in models_array_container:
                    model_fields_list = None
                    if isinstance(entry_in_container, dict):
                        potential_id = entry_in_container.get(
                            "id",
                            entry_in_container.get(
                                "model_id", entry_in_container.get("modelId")
                            ),
                        )
                        if potential_id:
                            model_fields_list = entry_in_container
                        else:
                            model_fields_list = list(entry_in_container.values())
                    elif isinstance(entry_in_container, list):
                        model_fields_list = entry_in_container
                    else:
                        logger.debug(
                            f"Skipping entry of unknown type: {type(entry_in_container)}"
                        )
                        continue

                    if not model_fields_list:
                        logger.debug(
                            "Skipping entry because model_fields_list is empty or None."
                        )
                        continue

                    model_id_path_str = None
                    display_name_candidate = ""
                    description_candidate = "N/A"
                    default_max_output_tokens_val = None
                    default_top_p_val = None
                    default_temperature_val = 1.0
                    supported_max_output_tokens_val = None
                    current_model_id_for_log = "UnknownModelYet"

                    try:
                        if isinstance(model_fields_list, list):
                            if not (
                                len(model_fields_list) > 0
                                and isinstance(model_fields_list[0], (str, int, float))
                            ):
                                logger.debug(
                                    f"Skipping list-based model_fields due to invalid first element: {str(model_fields_list)[:100]}"
                                )
                                continue
                            model_id_path_str = str(model_fields_list[0])
                            current_model_id_for_log = (
                                model_id_path_str.split("/")[-1]
                                if model_id_path_str and "/" in model_id_path_str
                                else model_id_path_str
                            )
                            display_name_candidate = (
                                str(model_fields_list[3])
                                if len(model_fields_list) > 3
                                else ""
                            )
                            description_candidate = (
                                str(model_fields_list[4])
                                if len(model_fields_list) > 4
                                else "N/A"
                            )

                            if (
                                len(model_fields_list) > 6
                                and model_fields_list[6] is not None
                            ):
                                try:
                                    val_int = int(model_fields_list[6])
                                    default_max_output_tokens_val = val_int
                                    supported_max_output_tokens_val = val_int
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"模型 {current_model_id_for_log}: 无法将列表索引6的值 '{model_fields_list[6]}' 解析为 max_output_tokens。"
                                    )

                            if (
                                len(model_fields_list) > 9
                                and model_fields_list[9] is not None
                            ):
                                try:
                                    raw_top_p = float(model_fields_list[9])
                                    if not (0.0 <= raw_top_p <= 1.0):
                                        logger.warning(
                                            f"模型 {current_model_id_for_log}: 原始 top_p值 {raw_top_p} (来自列表索引9) 超出 [0,1] 范围，将裁剪。"
                                        )
                                        default_top_p_val = max(
                                            0.0, min(1.0, raw_top_p)
                                        )
                                    else:
                                        default_top_p_val = raw_top_p
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"模型 {current_model_id_for_log}: 无法将列表索引9的值 '{model_fields_list[9]}' 解析为 top_p。"
                                    )

                        elif isinstance(model_fields_list, dict):
                            model_id_path_str = str(
                                model_fields_list.get(
                                    "id",
                                    model_fields_list.get(
                                        "model_id", model_fields_list.get("modelId")
                                    ),
                                )
                            )
                            current_model_id_for_log = (
                                model_id_path_str.split("/")[-1]
                                if model_id_path_str and "/" in model_id_path_str
                                else model_id_path_str
                            )
                            display_name_candidate = str(
                                model_fields_list.get(
                                    "displayName",
                                    model_fields_list.get(
                                        "display_name",
                                        model_fields_list.get("name", ""),
                                    ),
                                )
                            )
                            description_candidate = str(
                                model_fields_list.get("description", "N/A")
                            )

                            mot_parsed = model_fields_list.get(
                                "maxOutputTokens",
                                model_fields_list.get(
                                    "defaultMaxOutputTokens",
                                    model_fields_list.get("outputTokenLimit"),
                                ),
                            )
                            if mot_parsed is not None:
                                try:
                                    val_int = int(mot_parsed)
                                    default_max_output_tokens_val = val_int
                                    supported_max_output_tokens_val = val_int
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"模型 {current_model_id_for_log}: 无法将字典值 '{mot_parsed}' 解析为 max_output_tokens。"
                                    )

                            top_p_parsed = model_fields_list.get(
                                "topP", model_fields_list.get("defaultTopP")
                            )
                            if top_p_parsed is not None:
                                try:
                                    raw_top_p = float(top_p_parsed)
                                    if not (0.0 <= raw_top_p <= 1.0):
                                        logger.warning(
                                            f"模型 {current_model_id_for_log}: 原始 top_p值 {raw_top_p} (来自字典) 超出 [0,1] 范围，将裁剪。"
                                        )
                                        default_top_p_val = max(
                                            0.0, min(1.0, raw_top_p)
                                        )
                                    else:
                                        default_top_p_val = raw_top_p
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"模型 {current_model_id_for_log}: 无法将字典值 '{top_p_parsed}' 解析为 top_p。"
                                    )

                            temp_parsed = model_fields_list.get(
                                "temperature",
                                model_fields_list.get("defaultTemperature"),
                            )
                            if temp_parsed is not None:
                                try:
                                    default_temperature_val = float(temp_parsed)
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"模型 {current_model_id_for_log}: 无法将字典值 '{temp_parsed}' 解析为 temperature。"
                                    )
                        else:
                            logger.debug(
                                f"Skipping entry because model_fields_list is not list or dict: {type(model_fields_list)}"
                            )
                            continue
                    except Exception as e_parse_fields:
                        logger.error(
                            f"解析模型字段时出错 for entry {str(entry_in_container)[:100]}: {e_parse_fields}"
                        )
                        continue

                    if model_id_path_str and model_id_path_str.lower() != "none":
                        simple_model_id_str = (
                            model_id_path_str.split("/")[-1]
                            if "/" in model_id_path_str
                            else model_id_path_str
                        )
                        if simple_model_id_str in excluded_model_ids:
                            excluded_during_parse.append(simple_model_id_str)
                            continue

                        final_display_name_str = (
                            display_name_candidate
                            if display_name_candidate
                            else simple_model_id_str.replace("-", " ").title()
                        )
                        model_entry_dict = {
                            "id": simple_model_id_str,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "ai_studio",
                            "display_name": final_display_name_str,
                            "description": description_candidate,
                            "raw_model_path": model_id_path_str,
                            "default_temperature": default_temperature_val,
                            "default_max_output_tokens": default_max_output_tokens_val,
                            "supported_max_output_tokens": supported_max_output_tokens_val,
                            "default_top_p": default_top_p_val,
                        }
                        new_parsed_list.append(model_entry_dict)
                    else:
                        logger.debug(
                            f"Skipping entry due to invalid model_id_path: {model_id_path_str} from entry {str(entry_in_container)[:100]}"
                        )

                # Excluded model log moved to count change check
                excluded_count = (
                    len(excluded_during_parse) if excluded_during_parse else 0
                )

                if new_parsed_list:
                    # 检查是否已经有通过网络拦截注入的模型
                    has_network_injected_models = False
                    if models_array_container:
                        for entry_in_container in models_array_container:
                            if (
                                isinstance(entry_in_container, list)
                                and len(entry_in_container) > 10
                            ):
                                # 检查是否有网络注入标记
                                if "__NETWORK_INJECTED__" in entry_in_container:
                                    has_network_injected_models = True
                                    break

                    if has_network_injected_models and not is_in_login_flow:
                        logger.info("检测到网络拦截已注入模型")

                    # 注意：不再在后端添加注入模型
                    # 因为如果前端没有通过网络拦截注入，说明前端页面上没有这些模型
                    # 后端返回这些模型也无法实际使用，所以只依赖网络拦截注入

                    state.parsed_model_list = sorted(
                        new_parsed_list, key=lambda m: m.get("display_name", "").lower()
                    )
                    state.global_model_list_raw_json = json.dumps(
                        {"data": state.parsed_model_list, "object": "list"}
                    )
                    if DEBUG_LOGS_ENABLED:
                        # Only print full model list on first load or count change
                        previous_count = getattr(state, "_last_model_count", 0) or 0
                        current_count = len(state.parsed_model_list)
                        if previous_count != current_count or previous_count == 0:
                            # Only show detailed parsing info when list changes
                            if excluded_count > 0 and not is_in_login_flow:
                                logger.debug(f"[Model] 已排除 {excluded_count} 个模型")
                            log_output = f"[Model] 列表更新: {current_count} 个模型\n"
                            for i, item in enumerate(
                                state.parsed_model_list[
                                    : min(3, len(state.parsed_model_list))
                                ]
                            ):
                                log_output += f"  {i + 1}. {item.get('id')} (MaxTok={item.get('default_max_output_tokens')})\n"
                            logger.debug(log_output.rstrip())
                            state._last_model_count = current_count  # type: ignore
                        else:
                            logger.debug(f"[Model] 列表无变化 ({current_count} 个)")
                    else:
                        logger.info(
                            f"[模型] 列表已更新 (共 {len(state.parsed_model_list)} 个模型)"
                        )
                    if model_list_fetch_event and not model_list_fetch_event.is_set():
                        model_list_fetch_event.set()
                elif not state.parsed_model_list:
                    logger.warning("解析后模型列表仍然为空。")
                    if model_list_fetch_event and not model_list_fetch_event.is_set():
                        model_list_fetch_event.set()
            else:
                logger.warning("models_array_container 为 None，无法解析模型列表。")
                if model_list_fetch_event and not model_list_fetch_event.is_set():
                    model_list_fetch_event.set()
        except json.JSONDecodeError as json_err:
            logger.error(
                f"解析模型列表JSON失败: {json_err}. 响应 (前500字): {await response.text()[:500]}"
            )
        except asyncio.CancelledError:
            raise
        except Exception as e_handle_list_resp:
            logger.exception(f"处理模型列表响应时发生未知错误: {e_handle_list_resp}")
        finally:
            if model_list_fetch_event and not model_list_fetch_event.is_set():
                logger.info("处理模型列表响应结束，强制设置 model_list_fetch_event。")
                model_list_fetch_event.set()
