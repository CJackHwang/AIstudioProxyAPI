import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast
from urllib.parse import unquote, urlparse

from api_utils.utils_ext.files import extract_data_url_to_local, save_blob_to_local
from logging_utils import set_request_id
from models import Message


def prepare_combined_prompt(
    messages: List[Message],
    req_id: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
) -> Tuple[str, List[str]]:
    """准备组合提示"""
    logger = logging.getLogger("AIStudioProxyServer")
    set_request_id(req_id)

    # Track summary stats for consolidated logging
    _has_system_prompt = False
    _msg_count = len(messages)
    # 不在此处清空 upload_files；由上层在每次请求开始时按需清理，避免历史附件丢失导致“文件不存在”错误。

    combined_parts: List[str] = []
    system_prompt_content: Optional[str] = None
    processed_system_message_indices: Set[int] = set()
    files_list: List[str] = []  # 收集需要上传的本地文件路径（图片、视频、PDF等）

    # 若声明了可用工具，先在提示前注入工具目录，帮助模型知晓可用函数（内部适配，不影响外部协议）
    if isinstance(tools, list) and len(tools) > 0:
        try:
            tool_lines: List[str] = ["可用工具目录:"]
            for t in tools:
                name: Optional[str] = None
                params_schema: Optional[Dict[str, Any]] = None
                # t is Dict[str, Any] from List[Dict[str, Any]]
                fn_val: Any = t.get("function") if "function" in t else t
                if isinstance(fn_val, dict):
                    # Type narrowed: fn_val is dict
                    typed_fn: Dict[str, Any] = cast(Dict[str, Any], fn_val)
                    name_raw: Any = typed_fn.get("name") or t.get("name")
                    if isinstance(name_raw, str):
                        name = name_raw
                    params_raw: Any = typed_fn.get("parameters")
                    if isinstance(params_raw, dict):
                        params_schema = cast(Dict[str, Any], params_raw)
                else:
                    # fn_val is not dict, get name directly from t
                    name_raw: Any = t.get("name")
                    if isinstance(name_raw, str):
                        name = name_raw
                if name:
                    tool_lines.append(f"- 函数: {name}")
                    if params_schema:
                        try:
                            tool_lines.append(
                                f"  参数模式: {json.dumps(params_schema, ensure_ascii=False)}"
                            )
                        except Exception:
                            pass
            if tool_choice:
                # 明确要求或提示可调用的函数名
                chosen_name: Optional[str] = None
                if isinstance(tool_choice, dict):
                    # Type narrowed to dict by isinstance
                    typed_tool_choice: Dict[str, Any] = tool_choice
                    fn_val: Any = typed_tool_choice.get("function")
                    if isinstance(fn_val, dict):
                        # Type narrowed to dict
                        typed_fn: Dict[str, Any] = cast(Dict[str, Any], fn_val)
                        name_raw: Any = typed_fn.get("name")
                        if isinstance(name_raw, str):
                            chosen_name = name_raw
                elif tool_choice.lower() not in (
                    "auto",
                    "none",
                    "no",
                    "off",
                    "required",
                    "any",
                ):
                    chosen_name = tool_choice
                if chosen_name:
                    tool_lines.append(f"建议优先使用函数: {chosen_name}")
            combined_parts.append("\n".join(tool_lines) + "\n---\n")
        except Exception:
            pass

    # 处理系统消息
    for i, msg in enumerate(messages):
        if msg.role == "system":
            content = msg.content
            if isinstance(content, str) and content.strip():
                system_prompt_content = content.strip()
                processed_system_message_indices.add(i)
                _has_system_prompt = True
                logger.debug(
                    f"Found system prompt at index {i}: {system_prompt_content[:80]}..."
                )
                system_instr_prefix = "系统指令:\n"
                combined_parts.append(f"{system_instr_prefix}{system_prompt_content}")
            else:
                logger.debug(f"Ignoring empty system message at index {i}")
                processed_system_message_indices.add(i)
            break

    role_map_ui = {
        "user": "用户",
        "assistant": "助手",
        "system": "系统",
        "tool": "工具",
    }
    turn_separator = "\n---\n"

    # 处理其他消息
    for i, msg in enumerate(messages):
        if i in processed_system_message_indices:
            continue

        if msg.role == "system":
            logger.debug(f"Skipping subsequent system message at index {i}")
            continue

        if combined_parts:
            combined_parts.append(turn_separator)

        role = msg.role or "unknown"
        role_prefix_ui = f"{role_map_ui.get(role, role.capitalize())}:\n"
        current_turn_parts: List[str] = [role_prefix_ui]

        content = msg.content or ""
        content_str: str = ""

        if isinstance(content, str):
            content_str = content.strip()
        elif isinstance(content, list):
            # 处理多模态内容（更健壮地识别各类附件项）
            text_parts: List[str] = []
            for item in content:
                # 统一获取项类型（可能缺失）
                item_type: Optional[str] = None
                try:
                    # 使用 hasattr/getattr 时需防范 property抛出异常
                    if hasattr(item, "type"):
                        item_type = item.type
                except Exception:
                    item_type = None

                if item_type is None and isinstance(item, dict):
                    typed_item: Dict[str, Any] = cast(Dict[str, Any], item)
                    item_type_raw: Any = typed_item.get("type")
                    if isinstance(item_type_raw, str):
                        item_type = item_type_raw

                if item_type == "text":
                    # 文本项
                    if hasattr(item, "text"):
                        text_parts.append(getattr(item, "text", "") or "")
                    elif isinstance(item, dict):
                        typed_item: Dict[str, Any] = cast(Dict[str, Any], item)
                        text_raw: Any = typed_item.get("text", "")
                        text_parts.append(str(text_raw))
                    continue

                # 图片/文件/媒体 URL 项（类型缺失时也尝试识别）
                if item_type in (
                    "image_url",
                    "file_url",
                    "media_url",
                    "input_image",
                ) or (
                    isinstance(item, dict)
                    and (
                        "image_url" in item
                        or "input_image" in item
                        or "file_url" in item
                        or "media_url" in item
                        or "url" in item
                    )
                ):
                    try:
                        url_value: Optional[str] = None
                        # Pydantic 对象属性
                        if hasattr(item, "image_url") and item.image_url:
                            url_value = item.image_url.url
                            try:
                                detail_val: Optional[str] = getattr(
                                    item.image_url, "detail", None
                                )
                                if detail_val:
                                    text_parts.append(
                                        f"[图像细节: detail={detail_val}]"
                                    )
                            except Exception:
                                pass
                        elif hasattr(item, "input_image") and item.input_image:
                            url_value = item.input_image.url
                            try:
                                detail_val: Optional[str] = getattr(
                                    item.input_image, "detail", None
                                )
                                if detail_val:
                                    text_parts.append(
                                        f"[图像细节: detail={detail_val}]"
                                    )
                            except Exception:
                                pass
                        elif hasattr(item, "file_url") and item.file_url:
                            url_value = item.file_url.url
                        elif hasattr(item, "media_url") and item.media_url:
                            url_value = item.media_url.url
                        elif hasattr(item, "url") and item.url:
                            url_value = item.url
                        # 字典结构 (backwards compatibility)
                        if url_value is None and isinstance(item, dict):
                            typed_item: Dict[str, Any] = cast(Dict[str, Any], item)
                            image_url_raw: Any = typed_item.get("image_url")
                            input_image_raw: Any = typed_item.get("input_image")

                            if isinstance(image_url_raw, dict):
                                typed_img_url: Dict[str, Any] = cast(
                                    Dict[str, Any], image_url_raw
                                )
                                url_raw: Any = typed_img_url.get("url")
                                if isinstance(url_raw, str):
                                    url_value = url_raw
                                detail_raw: Any = typed_img_url.get("detail")
                                if isinstance(detail_raw, str):
                                    text_parts.append(
                                        f"[图像细节: detail={detail_raw}]"
                                    )
                            elif isinstance(image_url_raw, str):
                                url_value = image_url_raw
                            elif isinstance(input_image_raw, dict):
                                typed_input_img: Dict[str, Any] = cast(
                                    Dict[str, Any], input_image_raw
                                )
                                url_raw: Any = typed_input_img.get("url")
                                if isinstance(url_raw, str):
                                    url_value = url_raw
                                detail_raw: Any = typed_input_img.get("detail")
                                if isinstance(detail_raw, str):
                                    text_parts.append(
                                        f"[图像细节: detail={detail_raw}]"
                                    )
                            elif isinstance(input_image_raw, str):
                                url_value = input_image_raw
                            else:
                                # Check other URL fields
                                file_url_raw: Any = typed_item.get("file_url")
                                media_url_raw: Any = typed_item.get("media_url")
                                file_raw: Any = typed_item.get("file")

                                if isinstance(file_url_raw, dict):
                                    typed_file_url: Dict[str, Any] = cast(
                                        Dict[str, Any], file_url_raw
                                    )
                                    url_raw: Any = typed_file_url.get("url")
                                    if isinstance(url_raw, str):
                                        url_value = url_raw
                                elif isinstance(file_url_raw, str):
                                    url_value = file_url_raw
                                elif isinstance(media_url_raw, dict):
                                    typed_media_url: Dict[str, Any] = cast(
                                        Dict[str, Any], media_url_raw
                                    )
                                    url_raw: Any = typed_media_url.get("url")
                                    if isinstance(url_raw, str):
                                        url_value = url_raw
                                elif isinstance(media_url_raw, str):
                                    url_value = media_url_raw
                                elif "url" in typed_item:
                                    url_raw: Any = typed_item.get("url")
                                    if isinstance(url_raw, str):
                                        url_value = url_raw
                                elif isinstance(file_raw, dict):
                                    # 兼容通用 file 字段
                                    typed_file: Dict[str, Any] = cast(
                                        Dict[str, Any], file_raw
                                    )
                                    url_raw: Any = typed_file.get(
                                        "url"
                                    ) or typed_file.get("path")
                                    if isinstance(url_raw, str):
                                        url_value = url_raw

                        url_value = (url_value or "").strip()
                        if not url_value:
                            continue

                        # 归一化到本地文件列表，并记录日志
                        if url_value.startswith("data:"):
                            file_path = extract_data_url_to_local(
                                url_value, req_id=req_id
                            )
                            if file_path:
                                files_list.append(file_path)
                                logger.debug(
                                    f"(准备提示) 已识别并加入 data:URL 附件: {file_path}"
                                )
                        elif url_value.startswith("file:"):
                            parsed = urlparse(url_value)
                            local_path = unquote(parsed.path)
                            if os.path.exists(local_path):
                                files_list.append(local_path)
                                logger.debug(
                                    f"(准备提示) 已识别并加入本地附件(file://): {local_path}"
                                )
                            else:
                                logger.warning(
                                    f"(准备提示) file URL 指向的本地文件不存在: {local_path}"
                                )
                        elif os.path.isabs(url_value) and os.path.exists(url_value):
                            files_list.append(url_value)
                            logger.debug(
                                f"(准备提示) 已识别并加入本地附件(绝对路径): {url_value}"
                            )
                        else:
                            logger.debug(f"(准备提示) 忽略非本地附件 URL: {url_value}")
                    except Exception as e:
                        logger.warning(f"(准备提示) 处理附件 URL 时发生错误: {e}")
                    continue

                # 音/视频输入
                if item_type in ("input_audio", "input_video"):
                    try:
                        inp: Any = None
                        if hasattr(item, "input_audio") and item.input_audio:
                            inp = item.input_audio
                        elif hasattr(item, "input_video") and item.input_video:
                            inp = item.input_video
                        elif isinstance(item, dict):
                            typed_item: Dict[str, Any] = cast(Dict[str, Any], item)
                            inp = typed_item.get("input_audio") or typed_item.get(
                                "input_video"
                            )

                        if inp:
                            url_value: Optional[str] = None
                            data_val: Optional[str] = None
                            mime_val: Optional[str] = None
                            fmt_val: Optional[str] = None
                            if isinstance(inp, dict):
                                typed_inp: Dict[str, Any] = cast(Dict[str, Any], inp)
                                url_raw: Any = typed_inp.get("url")
                                if isinstance(url_raw, str):
                                    url_value = url_raw
                                data_raw: Any = typed_inp.get("data")
                                if isinstance(data_raw, str):
                                    data_val = data_raw
                                mime_raw: Any = typed_inp.get("mime_type")
                                if isinstance(mime_raw, str):
                                    mime_val = mime_raw
                                fmt_raw: Any = typed_inp.get("format")
                                if isinstance(fmt_raw, str):
                                    fmt_val = fmt_raw
                            else:
                                # Pydantic model or object with attributes
                                url_attr: Any = getattr(inp, "url", None)
                                if isinstance(url_attr, str):
                                    url_value = url_attr
                                data_attr: Any = getattr(inp, "data", None)
                                if isinstance(data_attr, str):
                                    data_val = data_attr
                                mime_attr: Any = getattr(inp, "mime_type", None)
                                if isinstance(mime_attr, str):
                                    mime_val = mime_attr
                                fmt_attr: Any = getattr(inp, "format", None)
                                if isinstance(fmt_attr, str):
                                    fmt_val = fmt_attr

                            if url_value:
                                if url_value.startswith("data:"):
                                    saved = extract_data_url_to_local(
                                        url_value, req_id=req_id
                                    )
                                    if saved:
                                        files_list.append(saved)
                                        logger.debug(
                                            f"(准备提示) 已识别并加入音视频 data:URL 附件: {saved}"
                                        )
                                elif url_value.startswith("file:"):
                                    parsed = urlparse(url_value)
                                    local_path = unquote(parsed.path)
                                    if os.path.exists(local_path):
                                        files_list.append(local_path)
                                        logger.debug(
                                            f"(准备提示) 已识别并加入音视频本地附件(file://): {local_path}"
                                        )
                                elif os.path.isabs(url_value) and os.path.exists(
                                    url_value
                                ):
                                    files_list.append(url_value)
                                    logger.debug(
                                        f"(准备提示) 已识别并加入音视频本地附件(绝对路径): {url_value}"
                                    )
                            elif data_val:
                                if isinstance(data_val, str) and data_val.startswith(
                                    "data:"
                                ):
                                    saved = extract_data_url_to_local(
                                        data_val, req_id=req_id
                                    )
                                    if saved:
                                        files_list.append(saved)
                                        logger.debug(
                                            f"(准备提示) 已识别并加入音视频 data:URL 附件: {saved}"
                                        )
                                else:
                                    # 认为是纯 base64 数据
                                    try:
                                        raw = base64.b64decode(data_val)
                                        saved = save_blob_to_local(
                                            raw, mime_val, fmt_val, req_id=req_id
                                        )
                                        if saved:
                                            files_list.append(saved)
                                            logger.debug(
                                                f"(准备提示) 已识别并加入音视频 base64 附件: {saved}"
                                            )
                                    except Exception:
                                        pass
                    except Exception as e:
                        logger.warning(f"(准备提示) 处理音视频输入时出错: {e}")
                    continue

                # 其他未知项：记录而不影响
                logger.warning(
                    f"(准备提示) 警告: 在索引 {i} 的消息中忽略非文本或未知类型的 content item"
                )
            content_str = "\n".join(text_parts).strip()
        elif isinstance(content, dict):
            # 兼容字典形式的内容，可能包含 'attachments'/'images'/'media'/'files'
            typed_content: Dict[str, Any] = cast(Dict[str, Any], content)
            text_parts = []
            attachments_keys = ["attachments", "images", "media", "files"]
            for key in attachments_keys:
                items: Any = typed_content.get(key)
                if isinstance(items, list):
                    for it in items:
                        url_value: Optional[str] = None
                        if isinstance(it, str):
                            url_value = it
                        elif isinstance(it, dict):
                            typed_it: Dict[str, Any] = cast(Dict[str, Any], it)
                            url_raw: Any = typed_it.get("url") or typed_it.get("path")
                            if isinstance(url_raw, str):
                                url_value = url_raw
                            if not url_value:
                                image_url_raw: Any = typed_it.get("image_url")
                                input_image_raw: Any = typed_it.get("input_image")
                                if isinstance(image_url_raw, dict):
                                    typed_img_url: Dict[str, Any] = cast(
                                        Dict[str, Any], image_url_raw
                                    )
                                    url_from_image: Any = typed_img_url.get("url")
                                    if isinstance(url_from_image, str):
                                        url_value = url_from_image
                                elif isinstance(input_image_raw, dict):
                                    typed_input_img: Dict[str, Any] = cast(
                                        Dict[str, Any], input_image_raw
                                    )
                                    url_from_input: Any = typed_input_img.get("url")
                                    if isinstance(url_from_input, str):
                                        url_value = url_from_input
                        if not url_value:
                            continue
                        url_value = url_value.strip()
                        if not url_value:
                            continue
                        if url_value.startswith("data:"):
                            fp = extract_data_url_to_local(url_value)
                            if fp:
                                files_list.append(fp)
                                logger.debug(
                                    f"(准备提示) 已识别并加入字典附件 data:URL: {fp}"
                                )
                        elif url_value.startswith("file:"):
                            parsed = urlparse(url_value)
                            lp = unquote(parsed.path)
                            if os.path.exists(lp):
                                files_list.append(lp)
                                logger.debug(
                                    f"(准备提示) 已识别并加入字典附件 file://: {lp}"
                                )
                        elif os.path.isabs(url_value) and os.path.exists(url_value):
                            files_list.append(url_value)
                            logger.debug(
                                f"(准备提示) 已识别并加入字典附件绝对路径: {url_value}"
                            )
                        else:
                            logger.debug(
                                f"(准备提示) 忽略字典附件的非本地 URL: {url_value}"
                            )
            # 同时将字典中可能的纯文本说明拼入
            text_field: Any = typed_content.get("text")
            if isinstance(text_field, str):
                text_parts.append(text_field)
            content_str = "\n".join(text_parts).strip()
        else:
            logger.warning(
                f"(准备提示) 警告: 角色 {role} 在索引 {i} 的内容类型意外 ({type(content)}) 或为 None。"
            )
            content_str = str(content or "").strip()

        if content_str:
            current_turn_parts.append(content_str)

        # 处理工具调用（不在此处主动执行，只做可视化，避免与对话式循环的客户端执行冲突）
        tool_calls = msg.tool_calls
        if role == "assistant" and tool_calls:
            if content_str:
                current_turn_parts.append("\n")

            tool_call_visualizations = []
            for tool_call in tool_calls:
                if hasattr(tool_call, "type") and tool_call.type == "function":
                    function_call = tool_call.function
                    func_name = function_call.name if function_call else None
                    func_args_str = function_call.arguments if function_call else None

                    try:
                        parsed_args = json.loads(
                            func_args_str if func_args_str else "{}"
                        )
                        formatted_args = json.dumps(
                            parsed_args, indent=2, ensure_ascii=False
                        )
                    except (json.JSONDecodeError, TypeError):
                        formatted_args = (
                            func_args_str if func_args_str is not None else "{}"
                        )

                    tool_call_visualizations.append(
                        f"请求调用函数: {func_name}\n参数:\n{formatted_args}"
                    )

            if tool_call_visualizations:
                current_turn_parts.append("\n".join(tool_call_visualizations))

        # 处理工具结果消息（role = 'tool'）：将其纳入提示，便于模型看到工具返回
        if role == "tool":
            tool_result_lines: List[str] = []
            # 标准 OpenAI 样式：content 为字符串，tool_call_id 关联上一轮调用
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                tool_result_lines.append(f"工具结果 (tool_call_id={tool_call_id}):")
            if isinstance(msg.content, str):
                tool_result_lines.append(msg.content)
            elif isinstance(msg.content, list):
                # 兼容少数客户端把结果装在列表里
                try:
                    merged_parts: List[str] = []
                    for it in msg.content:
                        if isinstance(it, dict):
                            if it.get("type") == "text":
                                text_raw = it.get("text", "")
                                if isinstance(text_raw, str):
                                    merged_parts.append(text_raw)
                                else:
                                    merged_parts.append(str(text_raw))
                            else:
                                merged_parts.append(str(it))
                        else:
                            merged_parts.append(str(it))
                    merged = "\n".join(merged_parts)
                    tool_result_lines.append(merged)
                except Exception:
                    tool_result_lines.append(str(msg.content))
            else:
                tool_result_lines.append(str(msg.content))
            if tool_result_lines:
                if content_str:
                    current_turn_parts.append("\n")
                current_turn_parts.append("\n".join(tool_result_lines))

        if len(current_turn_parts) > 1 or (role == "assistant" and tool_calls):
            combined_parts.append("".join(current_turn_parts))
        elif not combined_parts and not current_turn_parts:
            logger.debug(
                f"(准备提示) 跳过角色 {role} 在索引 {i} 的空消息 (且无工具调用)。"
            )
        elif len(current_turn_parts) == 1 and not combined_parts:
            logger.debug(f"(准备提示) 跳过角色 {role} 在索引 {i} 的空消息 (只有前缀)。")

    final_prompt = "".join(combined_parts)
    if final_prompt:
        final_prompt += "\n"

    # Consolidated English summary (replaces verbose Chinese logs)
    sys_indicator = "Yes" if _has_system_prompt else "No"
    attach_info = f", {len(files_list)} attachments" if files_list else ""
    logger.debug(
        f"[Prompt] 构建消息: {_msg_count} 条 (System: {sys_indicator}), "
        f"共 {len(final_prompt):,} 字符{attach_info}"
    )

    return final_prompt, files_list
