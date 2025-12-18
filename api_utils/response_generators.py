import asyncio
import json
import logging
import random
import time
from asyncio import Event
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, cast

from playwright.async_api import Page as AsyncPage

from config import CHAT_COMPLETION_ID_PREFIX
from logging_utils import set_request_id
from models import ChatCompletionRequest, ClientDisconnectedError

from .common_utils import random_id
from .sse import generate_sse_chunk, generate_sse_stop_chunk
from .utils_ext.stream import use_stream_response
from .utils_ext.tokens import calculate_usage_stats


async def gen_sse_from_aux_stream(
    req_id: str,
    request: ChatCompletionRequest,
    model_name_for_stream: str,
    check_client_disconnected: Callable[[str], bool],
    event_to_set: Event,
    stream_state: Optional[Dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """辅助流队列 -> OpenAI 兼容 SSE 生成器。

    产出增量、tool_calls、最终 usage 与 [DONE]。

    Args:
        stream_state: 可选的状态字典，用于向调用者报告流状态。
                      如果提供，将设置 'has_content' 键表示是否收到内容。
    """
    import logging

    logger = logging.getLogger("AIStudioProxyServer")
    set_request_id(req_id)

    # Stream start logged by use_stream_response

    last_reason_pos = 0
    last_body_pos = 0
    chat_completion_id = f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{int(time.time())}-{random.randint(100, 999)}"
    created_timestamp = int(time.time())

    full_reasoning_content = ""
    full_body_content = ""
    data_receiving = False

    try:
        async for raw_data in use_stream_response(req_id):
            data_receiving = True

            try:
                check_client_disconnected(f"流式生成器循环 ({req_id}): ")
            except ClientDisconnectedError:
                logger.info("客户端断开连接，终止流式生成")
                if data_receiving and not event_to_set.is_set():
                    logger.info("数据接收中客户端断开，立即设置done信号")
                    event_to_set.set()
                break

            data: Any
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"无法解析流数据JSON: {raw_data}")
                    continue
            elif isinstance(raw_data, dict):
                data = cast(Dict[str, Any], raw_data)
            else:
                logger.warning(f"未知的流数据类型: {type(raw_data)}")
                continue

            if not isinstance(data, dict):
                logger.warning(f"数据不是字典类型: {data}")
                continue

            # After isinstance check, data is confirmed to be dict - use cast for type narrowing
            typed_data: Dict[str, Any] = cast(Dict[str, Any], data)

            reason_raw: Any = typed_data.get("reason", "")
            reason: str = reason_raw if isinstance(reason_raw, str) else ""
            body_raw: Any = typed_data.get("body", "")
            body: str = body_raw if isinstance(body_raw, str) else ""
            done_raw: Any = typed_data.get("done", False)
            done: bool = done_raw if isinstance(done_raw, bool) else False
            function_raw: Any = typed_data.get("function", [])
            function: List[Any] = (
                cast(List[Any], function_raw) if isinstance(function_raw, list) else []
            )

            if reason:
                full_reasoning_content = reason
            if body:
                full_body_content = body

            if len(reason) > last_reason_pos:
                output = {
                    "id": chat_completion_id,
                    "object": "chat.completion.chunk",
                    "model": model_name_for_stream,
                    "created": created_timestamp,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "reasoning_content": reason[last_reason_pos:],
                            },
                            "finish_reason": None,
                            "native_finish_reason": None,
                        }
                    ],
                }
                last_reason_pos = len(reason)
                yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"

            if len(body) > last_body_pos:
                finish_reason_val: Optional[str] = None
                if done:
                    finish_reason_val = "stop"

                delta_content: Dict[str, Any] = {
                    "role": "assistant",
                    "content": body[last_body_pos:],
                }
                choice_item: Dict[str, Any] = {
                    "index": 0,
                    "delta": delta_content,
                    "finish_reason": finish_reason_val,
                    "native_finish_reason": finish_reason_val,
                }

                if done and function and len(function) > 0:
                    tool_calls_list: List[Dict[str, Any]] = []
                    for func_idx, function_call_data in enumerate(function):
                        if isinstance(function_call_data, dict):
                            typed_func_data: Dict[str, Any] = cast(
                                Dict[str, Any], function_call_data
                            )
                            tool_calls_list.append(
                                {
                                    "id": f"call_{random_id()}",
                                    "index": func_idx,
                                    "type": "function",
                                    "function": {
                                        "name": typed_func_data.get("name", ""),
                                        "arguments": json.dumps(
                                            typed_func_data.get("params", {})
                                        ),
                                    },
                                }
                            )
                    delta_content["tool_calls"] = tool_calls_list
                    choice_item["finish_reason"] = "tool_calls"
                    choice_item["native_finish_reason"] = "tool_calls"
                    delta_content["content"] = None

                output = {
                    "id": chat_completion_id,
                    "object": "chat.completion.chunk",
                    "model": model_name_for_stream,
                    "created": created_timestamp,
                    "choices": [choice_item],
                }
                last_body_pos = len(body)
                yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
            elif done:
                if function and len(function) > 0:
                    tool_calls_list: List[Dict[str, Any]] = []
                    for func_idx, function_call_data in enumerate(function):
                        if isinstance(function_call_data, dict):
                            typed_func_data: Dict[str, Any] = cast(
                                Dict[str, Any], function_call_data
                            )
                            tool_calls_list.append(
                                {
                                    "id": f"call_{random_id()}",
                                    "index": func_idx,
                                    "type": "function",
                                    "function": {
                                        "name": typed_func_data.get("name", ""),
                                        "arguments": json.dumps(
                                            typed_func_data.get("params", {})
                                        ),
                                    },
                                }
                            )
                    delta_content: Dict[str, Any] = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls_list,
                    }
                    choice_item: Dict[str, Any] = {
                        "index": 0,
                        "delta": delta_content,
                        "finish_reason": "tool_calls",
                        "native_finish_reason": "tool_calls",
                    }
                else:
                    choice_item: Dict[str, Any] = {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }

                output = {
                    "id": chat_completion_id,
                    "object": "chat.completion.chunk",
                    "model": model_name_for_stream,
                    "created": created_timestamp,
                    "choices": [choice_item],
                }
                yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"

    except ClientDisconnectedError:
        logger.info("流式生成器中检测到客户端断开连接")
        if data_receiving and not event_to_set.is_set():
            logger.info("客户端断开异常处理中立即设置done信号")
            event_to_set.set()
    except asyncio.CancelledError:
        logger.info("流式生成器被取消")
        if not event_to_set.is_set():
            event_to_set.set()
        raise
    except Exception as e:
        logger.error(f"流式生成器处理过程中发生错误: {e}", exc_info=True)
        # 设置完成事件以避免调用者永久等待
        if not event_to_set.is_set():
            event_to_set.set()
        # 重新抛出异常，让流式响应正常终止，而不是将错误作为聊天内容返回
        raise
    finally:
        # Stream end - cleanup follows
        try:
            usage_stats = calculate_usage_stats(
                [msg.model_dump() for msg in request.messages],
                full_body_content,
                full_reasoning_content,
            )
            logger.debug(f"[Usage] Token 统计: {usage_stats}")
            final_chunk: Dict[str, Any] = {
                "id": chat_completion_id,
                "object": "chat.completion.chunk",
                "model": model_name_for_stream,
                "created": created_timestamp,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
                "usage": usage_stats,
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as usage_err:
            logger.error(f"计算或发送usage统计时出错: {usage_err}")
        try:
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as done_err:
            logger.error(f"发送 [DONE] 标记时出错: {done_err}")
        if not event_to_set.is_set():
            event_to_set.set()

        # 更新 stream_state 以报告是否收到内容
        if stream_state is not None:
            has_content = bool(full_body_content or full_reasoning_content)
            stream_state["has_content"] = has_content
            logger.debug(f"流状态更新: has_content={has_content}")


async def gen_sse_from_playwright(
    page: AsyncPage,
    logger: logging.Logger,
    req_id: str,
    model_name_for_stream: str,
    request: ChatCompletionRequest,
    check_client_disconnected: Callable[[str], bool],
    completion_event: Event,
) -> AsyncGenerator[str, None]:
    """Playwright 最终响应 -> OpenAI 兼容 SSE 生成器。"""
    # Reuse already-imported helpers from utils to avoid repeated imports
    from browser_utils.page_controller import PageController
    from models import ClientDisconnectedError

    set_request_id(req_id)
    data_receiving = False
    try:
        page_controller = PageController(page, logger, req_id)
        final_content: str = await page_controller.get_response(
            check_client_disconnected
        )
        data_receiving = True
        lines = final_content.split("\n")
        for line_idx, line in enumerate(lines):
            try:
                check_client_disconnected(f"Playwright流式生成器循环 ({req_id}): ")
            except ClientDisconnectedError:
                logger.info("Playwright流式生成器中检测到客户端断开连接")
                if data_receiving and not completion_event.is_set():
                    logger.info("Playwright数据接收中客户端断开，立即设置done信号")
                    completion_event.set()
                break
            if line:
                chunk_size = 5
                for i in range(0, len(line), chunk_size):
                    chunk = line[i : i + chunk_size]
                    yield generate_sse_chunk(chunk, req_id, model_name_for_stream)
                    await asyncio.sleep(0.03)
            if line_idx < len(lines) - 1:
                yield generate_sse_chunk("\n", req_id, model_name_for_stream)
                await asyncio.sleep(0.01)
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            final_content,
            "",
        )
        logger.info(f"[Usage] Playwright Non-Stream Token 统计: {usage_stats}")
        yield generate_sse_stop_chunk(
            req_id, model_name_for_stream, "stop", usage_stats
        )
    except ClientDisconnectedError:
        logger.info("Playwright流式生成器中检测到客户端断开连接")
        if data_receiving and not completion_event.is_set():
            logger.info("Playwright客户端断开异常处理中立即设置done信号")
            completion_event.set()
    except asyncio.CancelledError:
        logger.info("Playwright流式生成器被取消")
        if not completion_event.is_set():
            completion_event.set()
        raise
    except Exception as e:
        logger.error(f"Playwright流式生成器处理过程中发生错误: {e}", exc_info=True)
        # 设置完成事件以避免调用者永久等待
        if not completion_event.is_set():
            completion_event.set()
        # 重新抛出异常，让流式响应正常终止，而不是将错误作为聊天内容返回
        raise
    finally:
        if not completion_event.is_set():
            completion_event.set()
            logger.info("Playwright流式生成器完成事件已设置")
