"""
请求处理器模块
包含核心的请求处理逻辑
"""

import asyncio
import json
import os
import random
import time
from typing import Optional, Tuple, Callable, AsyncGenerator
from asyncio import Event, Future

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.async_api import Page as AsyncPage, Locator, Error as PlaywrightAsyncError, expect as expect_async

# --- 配置模块导入 ---
from config import *

# --- models模块导入 ---
from models import ChatCompletionRequest, ClientDisconnectedError

# --- browser_utils模块导入 ---
from browser_utils import (
    switch_ai_studio_model,
    save_error_snapshot
)

# --- api_utils模块导入 ---
from .utils import (
    validate_chat_request,
    prepare_combined_prompt,
    generate_sse_chunk,
    generate_sse_stop_chunk,
    use_stream_response,
    calculate_usage_stats
)
from browser_utils.page_controller import PageController


async def _initialize_request_context(req_id: str, request: ChatCompletionRequest) -> dict:
    """初始化请求上下文"""
    from server import (
        logger, page_instance, is_page_ready, parsed_model_list,
        current_ai_studio_model_id, model_switching_lock, page_params_cache,
        params_cache_lock
    )
    
    logger.info(f"[{req_id}] 开始处理请求...")
    logger.info(f"[{req_id}]   请求参数 - Model: {request.model}, Stream: {request.stream}")
    
    context = {
        'logger': logger,
        'page': page_instance,
        'is_page_ready': is_page_ready,
        'parsed_model_list': parsed_model_list,
        'current_ai_studio_model_id': current_ai_studio_model_id,
        'model_switching_lock': model_switching_lock,
        'page_params_cache': page_params_cache,
        'params_cache_lock': params_cache_lock,
        'is_streaming': request.stream,
        'model_actually_switched': False,
        'requested_model': request.model,
        'model_id_to_use': None,
        'needs_model_switching': False
    }
    
    return context


async def _analyze_model_requirements(req_id: str, context: dict, request: ChatCompletionRequest) -> dict:
    """分析模型需求并确定是否需要切换"""
    logger = context['logger']
    current_ai_studio_model_id = context['current_ai_studio_model_id']
    parsed_model_list = context['parsed_model_list']
    requested_model = request.model
    
    if requested_model and requested_model != MODEL_NAME:
        from .model_manager import get_model_manager
        model_manager = get_model_manager()

        try:
            # 使用模型管理器验证模型请求
            requested_model_id = await model_manager.validate_model_request(requested_model, req_id)
            logger.info(f"[{req_id}] 请求使用模型: {requested_model_id}")

            context['model_id_to_use'] = requested_model_id

            # 检查是否需要切换模型
            if await model_manager.needs_model_switch(requested_model_id):
                context['needs_model_switching'] = True
                current_model_id = await model_manager.get_current_model_id()
                logger.info(f"[{req_id}] 需要切换模型: 当前={current_model_id} -> 目标={requested_model_id}")

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    return context


async def _test_client_connection(req_id: str, http_request: Request) -> bool:
    """通过发送测试数据包来主动检测客户端连接状态"""
    try:
        # 尝试发送一个小的测试数据包
        test_chunk = "data: {\"type\":\"ping\"}\n\n"

        # 获取底层的响应对象
        if hasattr(http_request, '_receive'):
            # 检查接收通道是否还活跃
            try:
                # 尝试非阻塞地检查是否有断开消息
                import asyncio
                receive_task = asyncio.create_task(http_request._receive())
                done, pending = await asyncio.wait([receive_task], timeout=0.01)

                if done:
                    message = receive_task.result()
                    if message.get("type") == "http.disconnect":
                        return False
                else:
                    # 取消未完成的任务
                    receive_task.cancel()
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass

            except Exception:
                # 如果检查过程中出现异常，可能表示连接有问题
                return False

        # 如果上述检查都通过，认为连接正常
        return True

    except Exception as e:
        # 任何异常都认为连接已断开
        return False

async def _setup_disconnect_monitoring(req_id: str, http_request: Request, result_future: Future) -> Tuple[Event, asyncio.Task, Callable]:
    """设置客户端断开连接监控"""
    from server import logger

    client_disconnected_event = Event()

    async def check_disconnect_periodically():
        while not client_disconnected_event.is_set():
            try:
                # 使用主动检测方法
                is_connected = await _test_client_connection(req_id, http_request)
                if not is_connected:
                    logger.info(f"[{req_id}] 主动检测到客户端断开连接。")
                    client_disconnected_event.set()
                    if not result_future.done():
                        result_future.set_exception(HTTPException(status_code=499, detail=f"[{req_id}] 客户端关闭了请求"))
                    break

                # 备用检查：使用原有的is_disconnected方法
                if await http_request.is_disconnected():
                    logger.info(f"[{req_id}] 备用检测到客户端断开连接。")
                    client_disconnected_event.set()
                    if not result_future.done():
                        result_future.set_exception(HTTPException(status_code=499, detail=f"[{req_id}] 客户端关闭了请求"))
                    break

                await asyncio.sleep(0.3)  # 更频繁的检查间隔，从0.5秒改为0.3秒
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{req_id}] (Disco Check Task) 错误: {e}")
                client_disconnected_event.set()
                if not result_future.done():
                    result_future.set_exception(HTTPException(status_code=500, detail=f"[{req_id}] Internal disconnect checker error: {e}"))
                break

    disconnect_check_task = asyncio.create_task(check_disconnect_periodically())

    def check_client_disconnected(stage: str = ""):
        if client_disconnected_event.is_set():
            logger.info(f"[{req_id}] 在 '{stage}' 检测到客户端断开连接。")
            raise ClientDisconnectedError(f"[{req_id}] Client disconnected at stage: {stage}")
        return False

    return client_disconnected_event, disconnect_check_task, check_client_disconnected


async def _validate_page_status(req_id: str, context: dict, check_client_disconnected: Callable) -> None:
    """验证页面状态"""
    page = context['page']
    is_page_ready = context['is_page_ready']
    
    if not page or page.is_closed() or not is_page_ready:
        raise HTTPException(status_code=503, detail=f"[{req_id}] AI Studio 页面丢失或未就绪。", headers={"Retry-After": "30"})
    
    check_client_disconnected("Initial Page Check")


async def _handle_model_switching(req_id: str, context: dict, check_client_disconnected: Callable) -> dict:
    """处理模型切换逻辑"""
    if not context['needs_model_switching']:
        return context

    logger = context['logger']
    page = context['page']
    model_id_to_use = context['model_id_to_use']

    from .model_manager import get_model_manager
    model_manager = get_model_manager()

    # 使用模型管理器进行安全的模型切换
    switch_success = await model_manager.switch_model_safe(page, model_id_to_use, req_id)

    if switch_success:
        context['model_actually_switched'] = True
        context['current_ai_studio_model_id'] = model_id_to_use
        logger.info(f"[{req_id}] ✅ 模型切换成功: {model_id_to_use}")
    else:
        await _handle_model_switch_failure(req_id, page, model_id_to_use, await model_manager.get_current_model_id(), logger)

    return context


async def _handle_model_switch_failure(req_id: str, page: AsyncPage, model_id_to_use: str, model_before_switch: str, logger) -> None:
    """处理模型切换失败的情况"""
    logger.warning(f"[{req_id}] ❌ 模型切换至 {model_id_to_use} 失败。")

    # 模型管理器已经处理了状态恢复，这里只需要抛出异常
    raise HTTPException(
        status_code=422,
        detail=f"[{req_id}] 未能切换到模型 '{model_id_to_use}'。请确保模型可用。"
    )


async def _handle_parameter_cache(req_id: str, context: dict) -> None:
    """处理参数缓存"""
    logger = context['logger']
    current_ai_studio_model_id = context['current_ai_studio_model_id']
    model_actually_switched = context['model_actually_switched']

    from .state_manager import get_state_manager
    state_manager = get_state_manager()

    # 使用状态管理器的线程安全缓存操作
    cached_model_for_params = await state_manager.get_cache_value("last_known_model_id_for_params")

    if model_actually_switched or (current_ai_studio_model_id != cached_model_for_params):
        logger.info(f"[{req_id}] 模型已更改，参数缓存失效。")
        await state_manager.clear_cache()
        await state_manager.set_cache_value("last_known_model_id_for_params", current_ai_studio_model_id)


async def _prepare_and_validate_request(req_id: str, request: ChatCompletionRequest, check_client_disconnected: Callable) -> str:
    """准备和验证请求"""
    try:
        validate_chat_request(request.messages, req_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"[{req_id}] 无效请求: {e}")
    
    prepared_prompt = prepare_combined_prompt(request.messages, req_id)
    check_client_disconnected("After Prompt Prep")
    
    return prepared_prompt

async def _handle_response_processing(req_id: str, request: ChatCompletionRequest, page: AsyncPage,
                                    context: dict, result_future: Future,
                                    submit_button_locator: Locator, check_client_disconnected: Callable) -> Optional[Tuple[Event, Locator, Callable]]:
    """处理响应生成"""
    from server import logger
    
    is_streaming = request.stream
    current_ai_studio_model_id = context.get('current_ai_studio_model_id')
    
    # 检查是否使用辅助流
    stream_port = os.environ.get('STREAM_PORT')
    use_stream = stream_port != '0'
    
    if use_stream:
        return await _handle_auxiliary_stream_response(req_id, request, context, result_future, submit_button_locator, check_client_disconnected)
    else:
        return await _handle_playwright_response(req_id, request, page, context, result_future, submit_button_locator, check_client_disconnected)


async def _handle_auxiliary_stream_response(req_id: str, request: ChatCompletionRequest, context: dict, 
                                          result_future: Future, submit_button_locator: Locator, 
                                          check_client_disconnected: Callable) -> Optional[Tuple[Event, Locator, Callable]]:
    """使用辅助流处理响应"""
    from server import logger
    
    is_streaming = request.stream
    current_ai_studio_model_id = context.get('current_ai_studio_model_id')
    
    def generate_random_string(length):
        charset = "abcdefghijklmnopqrstuvwxyz0123456789"
        return ''.join(random.choice(charset) for _ in range(length))

    if is_streaming:
        try:
            completion_event = Event()
            
            async def create_stream_generator_from_helper(event_to_set: Event) -> AsyncGenerator[str, None]:
                last_reason_pos = 0
                last_body_pos = 0
                model_name_for_stream = current_ai_studio_model_id or MODEL_NAME
                chat_completion_id = f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{int(time.time())}-{random.randint(100, 999)}"
                created_timestamp = int(time.time())

                # 用于收集完整内容以计算usage
                full_reasoning_content = ""
                full_body_content = ""

                # 数据接收状态标记
                data_receiving = False

                try:
                    async for raw_data in use_stream_response(req_id):
                        # 标记数据接收状态
                        data_receiving = True

                        # 检查客户端是否断开连接
                        try:
                            check_client_disconnected(f"流式生成器循环 ({req_id}): ")
                        except ClientDisconnectedError:
                            logger.info(f"[{req_id}] 客户端断开连接，终止流式生成")
                            # 如果正在接收数据时客户端断开，立即设置done信号
                            if data_receiving and not event_to_set.is_set():
                                logger.info(f"[{req_id}] 数据接收中客户端断开，立即设置done信号")
                                event_to_set.set()
                            break
                        
                        # 确保 data 是字典类型
                        if isinstance(raw_data, str):
                            try:
                                data = json.loads(raw_data)
                            except json.JSONDecodeError:
                                logger.warning(f"[{req_id}] 无法解析流数据JSON: {raw_data}")
                                continue
                        elif isinstance(raw_data, dict):
                            data = raw_data
                        else:
                            logger.warning(f"[{req_id}] 未知的流数据类型: {type(raw_data)}")
                            continue
                        
                        # 确保必要的键存在
                        if not isinstance(data, dict):
                            logger.warning(f"[{req_id}] 数据不是字典类型: {data}")
                            continue
                        
                        reason = data.get("reason", "")
                        body = data.get("body", "")
                        done = data.get("done", False)
                        function = data.get("function", [])
                        
                        # 更新完整内容记录
                        if reason:
                            full_reasoning_content = reason
                        if body:
                            full_body_content = body
                        
                        # 处理推理内容
                        if len(reason) > last_reason_pos:
                            output = {
                                "id": chat_completion_id,
                                "object": "chat.completion.chunk",
                                "model": model_name_for_stream,
                                "created": created_timestamp,
                                "choices":[{
                                    "index": 0,
                                    "delta":{
                                        "role": "assistant",
                                        "content": None,
                                        "reasoning_content": reason[last_reason_pos:],
                                    },
                                    "finish_reason": None,
                                    "native_finish_reason": None,
                                }]
                            }
                            last_reason_pos = len(reason)
                            yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
                        
                        # 处理主体内容
                        if len(body) > last_body_pos:
                            finish_reason_val = None
                            if done:
                                finish_reason_val = "stop"
                            
                            delta_content = {"role": "assistant", "content": body[last_body_pos:]}
                            choice_item = {
                                "index": 0,
                                "delta": delta_content,
                                "finish_reason": finish_reason_val,
                                "native_finish_reason": finish_reason_val,
                            }

                            if done and function and len(function) > 0:
                                tool_calls_list = []
                                for func_idx, function_call_data in enumerate(function):
                                    tool_calls_list.append({
                                        "id": f"call_{generate_random_string(24)}",
                                        "index": func_idx,
                                        "type": "function",
                                        "function": {
                                            "name": function_call_data["name"],
                                            "arguments": json.dumps(function_call_data["params"]),
                                        },
                                    })
                                delta_content["tool_calls"] = tool_calls_list
                                choice_item["finish_reason"] = "tool_calls"
                                choice_item["native_finish_reason"] = "tool_calls"
                                delta_content["content"] = None

                            output = {
                                "id": chat_completion_id,
                                "object": "chat.completion.chunk",
                                "model": model_name_for_stream,
                                "created": created_timestamp,
                                "choices": [choice_item]
                            }
                            last_body_pos = len(body)
                            yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
                        
                        # 处理只有done=True但没有新内容的情况（仅有函数调用或纯结束）
                        elif done:
                            # 如果有函数调用但没有新的body内容
                            if function and len(function) > 0:
                                delta_content = {"role": "assistant", "content": None}
                                tool_calls_list = []
                                for func_idx, function_call_data in enumerate(function):
                                    tool_calls_list.append({
                                        "id": f"call_{generate_random_string(24)}",
                                        "index": func_idx,
                                        "type": "function",
                                        "function": {
                                            "name": function_call_data["name"],
                                            "arguments": json.dumps(function_call_data["params"]),
                                        },
                                    })
                                delta_content["tool_calls"] = tool_calls_list
                                choice_item = {
                                    "index": 0,
                                    "delta": delta_content,
                                    "finish_reason": "tool_calls",
                                    "native_finish_reason": "tool_calls",
                                }
                            else:
                                # 纯结束，没有新内容和函数调用
                                choice_item = {
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
                                "choices": [choice_item]
                            }
                            yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
                
                except ClientDisconnectedError:
                    logger.info(f"[{req_id}] 流式生成器中检测到客户端断开连接")
                    # 客户端断开时立即设置done信号
                    if data_receiving and not event_to_set.is_set():
                        logger.info(f"[{req_id}] 客户端断开异常处理中立即设置done信号")
                        event_to_set.set()
                except Exception as e:
                    logger.error(f"[{req_id}] 流式生成器处理过程中发生错误: {e}", exc_info=True)
                    # 发送错误信息给客户端
                    try:
                        error_chunk = {
                            "id": chat_completion_id,
                            "object": "chat.completion.chunk",
                            "model": model_name_for_stream,
                            "created": created_timestamp,
                            "choices": [{
                                "index": 0,
                                "delta": {"role": "assistant", "content": f"\n\n[错误: {str(e)}]"},
                                "finish_reason": "stop",
                                "native_finish_reason": "stop",
                            }]
                        }
                        yield f"data: {json.dumps(error_chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
                    except Exception:
                        pass  # 如果无法发送错误信息，继续处理结束逻辑
                finally:
                    # 计算usage统计
                    try:
                        usage_stats = calculate_usage_stats(
                            [msg.model_dump() for msg in request.messages],
                            full_body_content,
                            full_reasoning_content
                        )
                        logger.info(f"[{req_id}] 计算的token使用统计: {usage_stats}")
                        
                        # 发送带usage的最终chunk
                        final_chunk = {
                            "id": chat_completion_id,
                            "object": "chat.completion.chunk",
                            "model": model_name_for_stream,
                            "created": created_timestamp,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                                "native_finish_reason": "stop"
                            }],
                            "usage": usage_stats
                        }
                        yield f"data: {json.dumps(final_chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
                        logger.info(f"[{req_id}] 已发送带usage统计的最终chunk")
                        
                    except Exception as usage_err:
                        logger.error(f"[{req_id}] 计算或发送usage统计时出错: {usage_err}")
                    
                    # 确保总是发送 [DONE] 标记
                    try:
                        logger.info(f"[{req_id}] 流式生成器完成，发送 [DONE] 标记")
                        yield "data: [DONE]\n\n"
                    except Exception as done_err:
                        logger.error(f"[{req_id}] 发送 [DONE] 标记时出错: {done_err}")
                    
                    # 确保事件被设置
                    if not event_to_set.is_set():
                        event_to_set.set()
                        logger.info(f"[{req_id}] 流式生成器完成事件已设置")

            stream_gen_func = create_stream_generator_from_helper(completion_event)
            if not result_future.done():
                result_future.set_result(StreamingResponse(stream_gen_func, media_type="text/event-stream"))
            else:
                if not completion_event.is_set():
                    completion_event.set()
            
            return completion_event, submit_button_locator, check_client_disconnected

        except Exception as e:
            logger.error(f"[{req_id}] 从队列获取流式数据时出错: {e}", exc_info=True)
            if completion_event and not completion_event.is_set():
                completion_event.set()
            raise

    else:  # 非流式
        content = None
        reasoning_content = None
        functions = None
        final_data_from_aux_stream = None

        async for raw_data in use_stream_response(req_id):
            check_client_disconnected(f"非流式辅助流 - 循环中 ({req_id}): ")
            
            # 确保 data 是字典类型
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"[{req_id}] 无法解析非流式数据JSON: {raw_data}")
                    continue
            elif isinstance(raw_data, dict):
                data = raw_data
            else:
                logger.warning(f"[{req_id}] 非流式未知数据类型: {type(raw_data)}")
                continue
            
            # 确保数据是字典类型
            if not isinstance(data, dict):
                logger.warning(f"[{req_id}] 非流式数据不是字典类型: {data}")
                continue
                
            final_data_from_aux_stream = data
            if data.get("done"):
                content = data.get("body")
                reasoning_content = data.get("reason")
                functions = data.get("function")
                break
        
        if final_data_from_aux_stream and final_data_from_aux_stream.get("reason") == "internal_timeout":
            logger.error(f"[{req_id}] 非流式请求通过辅助流失败: 内部超时")
            raise HTTPException(status_code=502, detail=f"[{req_id}] 辅助流处理错误 (内部超时)")

        if final_data_from_aux_stream and final_data_from_aux_stream.get("done") is True and content is None:
             logger.error(f"[{req_id}] 非流式请求通过辅助流完成但未提供内容")
             raise HTTPException(status_code=502, detail=f"[{req_id}] 辅助流完成但未提供内容")

        model_name_for_json = current_ai_studio_model_id or MODEL_NAME
        message_payload = {"role": "assistant", "content": content}
        finish_reason_val = "stop"

        if functions and len(functions) > 0:
            tool_calls_list = []
            for func_idx, function_call_data in enumerate(functions):
                tool_calls_list.append({
                    "id": f"call_{generate_random_string(24)}",
                    "index": func_idx,
                    "type": "function",
                    "function": {
                        "name": function_call_data["name"],
                        "arguments": json.dumps(function_call_data["params"]),
                    },
                })
            message_payload["tool_calls"] = tool_calls_list
            finish_reason_val = "tool_calls"
            message_payload["content"] = None
        
        if reasoning_content:
            message_payload["reasoning_content"] = reasoning_content

        # 计算token使用统计
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            content or "",
            reasoning_content
        )

        response_payload = {
            "id": f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name_for_json,
            "choices": [{
                "index": 0,
                "message": message_payload,
                "finish_reason": finish_reason_val,
                "native_finish_reason": finish_reason_val,
            }],
            "usage": usage_stats
        }

        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))
        return None


async def _handle_playwright_response(req_id: str, request: ChatCompletionRequest, page: AsyncPage, 
                                    context: dict, result_future: Future, submit_button_locator: Locator, 
                                    check_client_disconnected: Callable) -> Optional[Tuple[Event, Locator, Callable]]:
    """使用Playwright处理响应"""
    from server import logger
    
    is_streaming = request.stream
    current_ai_studio_model_id = context.get('current_ai_studio_model_id')
    
    logger.info(f"[{req_id}] 定位响应元素...")
    response_container = page.locator(RESPONSE_CONTAINER_SELECTOR).last
    response_element = response_container.locator(RESPONSE_TEXT_SELECTOR)
    
    try:
        await expect_async(response_container).to_be_attached(timeout=20000)
        check_client_disconnected("After Response Container Attached: ")
        await expect_async(response_element).to_be_attached(timeout=90000)
        logger.info(f"[{req_id}] 响应元素已定位。")
    except (PlaywrightAsyncError, asyncio.TimeoutError, ClientDisconnectedError) as locate_err:
        if isinstance(locate_err, ClientDisconnectedError):
            raise
        logger.error(f"[{req_id}] ❌ 错误: 定位响应元素失败或超时: {locate_err}")
        await save_error_snapshot(f"response_locate_error_{req_id}")
        raise HTTPException(status_code=502, detail=f"[{req_id}] 定位AI Studio响应元素失败: {locate_err}")
    except Exception as locate_exc:
        logger.exception(f"[{req_id}] ❌ 错误: 定位响应元素时意外错误")
        await save_error_snapshot(f"response_locate_unexpected_{req_id}")
        raise HTTPException(status_code=500, detail=f"[{req_id}] 定位响应元素时意外错误: {locate_exc}")

    check_client_disconnected("After Response Element Located: ")

    if is_streaming:
        completion_event = Event()

        async def create_response_stream_generator():
            # 数据接收状态标记
            data_receiving = False

            try:
                # 使用PageController获取响应
                page_controller = PageController(page, logger, req_id)
                final_content = await page_controller.get_response(check_client_disconnected)

                # 标记数据接收状态
                data_receiving = True

                # 生成流式响应 - 保持Markdown格式
                # 按行分割以保持换行符和Markdown结构
                lines = final_content.split('\n')
                for line_idx, line in enumerate(lines):
                    # 检查客户端是否断开连接
                    try:
                        check_client_disconnected(f"Playwright流式生成器循环 ({req_id}): ")
                    except ClientDisconnectedError:
                        logger.info(f"[{req_id}] Playwright流式生成器中检测到客户端断开连接")
                        # 如果正在接收数据时客户端断开，立即设置done信号
                        if data_receiving and not completion_event.is_set():
                            logger.info(f"[{req_id}] Playwright数据接收中客户端断开，立即设置done信号")
                            completion_event.set()
                        break

                    # 输出当前行的内容（包括空行，以保持Markdown格式）
                    if line:  # 非空行按字符分块输出
                        chunk_size = 5  # 每次输出5个字符，平衡速度和体验
                        for i in range(0, len(line), chunk_size):
                            chunk = line[i:i+chunk_size]
                            yield generate_sse_chunk(chunk, req_id, current_ai_studio_model_id or MODEL_NAME)
                            await asyncio.sleep(0.03)  # 适中的输出速度

                    # 添加换行符（除了最后一行）
                    if line_idx < len(lines) - 1:
                        yield generate_sse_chunk('\n', req_id, current_ai_studio_model_id or MODEL_NAME)
                        await asyncio.sleep(0.01)
                
                # 计算并发送带usage的完成块
                usage_stats = calculate_usage_stats(
                    [msg.model_dump() for msg in request.messages],
                    final_content,
                    ""  # Playwright模式没有reasoning content
                )
                logger.info(f"[{req_id}] Playwright非流式计算的token使用统计: {usage_stats}")
                
                # 发送带usage的完成块
                yield generate_sse_stop_chunk(req_id, current_ai_studio_model_id or MODEL_NAME, "stop", usage_stats)
                
            except ClientDisconnectedError:
                logger.info(f"[{req_id}] Playwright流式生成器中检测到客户端断开连接")
                # 客户端断开时立即设置done信号
                if data_receiving and not completion_event.is_set():
                    logger.info(f"[{req_id}] Playwright客户端断开异常处理中立即设置done信号")
                    completion_event.set()
            except Exception as e:
                logger.error(f"[{req_id}] Playwright流式生成器处理过程中发生错误: {e}", exc_info=True)
                # 发送错误信息给客户端
                try:
                    yield generate_sse_chunk(f"\n\n[错误: {str(e)}]", req_id, current_ai_studio_model_id or MODEL_NAME)
                    yield generate_sse_stop_chunk(req_id, current_ai_studio_model_id or MODEL_NAME)
                except Exception:
                    pass  # 如果无法发送错误信息，继续处理结束逻辑
            finally:
                # 确保事件被设置
                if not completion_event.is_set():
                    completion_event.set()
                    logger.info(f"[{req_id}] Playwright流式生成器完成事件已设置")

        stream_gen_func = create_response_stream_generator()
        if not result_future.done():
            result_future.set_result(StreamingResponse(stream_gen_func, media_type="text/event-stream"))
        
        return completion_event, submit_button_locator, check_client_disconnected
    else:
        # 使用PageController获取响应
        page_controller = PageController(page, logger, req_id)
        final_content = await page_controller.get_response(check_client_disconnected)
        
        # 计算token使用统计
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            final_content,
            ""  # Playwright模式没有reasoning content
        )
        logger.info(f"[{req_id}] Playwright非流式计算的token使用统计: {usage_stats}")
        
        response_payload = {
            "id": f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": current_ai_studio_model_id or MODEL_NAME,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": final_content},
                "finish_reason": "stop"
            }],
            "usage": usage_stats
        }
        
        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))
        
        return None


async def _cleanup_request_resources(req_id: str, disconnect_check_task: Optional[asyncio.Task], 
                                   completion_event: Optional[Event], result_future: Future, 
                                   is_streaming: bool) -> None:
    """清理请求资源"""
    from server import logger
    
    if disconnect_check_task and not disconnect_check_task.done():
        disconnect_check_task.cancel()
        try: 
            await disconnect_check_task
        except asyncio.CancelledError: 
            pass
        except Exception as task_clean_err: 
            logger.error(f"[{req_id}] 清理任务时出错: {task_clean_err}")
    
    logger.info(f"[{req_id}] 处理完成。")
    
    if is_streaming and completion_event and not completion_event.is_set() and (result_future.done() and result_future.exception() is not None):
         logger.warning(f"[{req_id}] 流式请求异常，确保完成事件已设置。")
         completion_event.set()


async def _process_request_refactored(
    req_id: str,
    request: ChatCompletionRequest,
    http_request: Request,
    result_future: Future
) -> Optional[Tuple[Event, Locator, Callable[[str], bool]]]:
    """核心请求处理函数 - 重构版本"""

    # 优化：在开始任何处理前主动检测客户端连接状态
    is_connected = await _test_client_connection(req_id, http_request)
    if not is_connected:
        from server import logger
        logger.info(f"[{req_id}] ✅ 核心处理前检测到客户端断开，提前退出节省资源")
        if not result_future.done():
            result_future.set_exception(HTTPException(status_code=499, detail=f"[{req_id}] 客户端在处理开始前已断开连接"))
        return None

    context = await _initialize_request_context(req_id, request)
    context = await _analyze_model_requirements(req_id, context, request)
    
    client_disconnected_event, disconnect_check_task, check_client_disconnected = await _setup_disconnect_monitoring(
        req_id, http_request, result_future
    )
    
    page = context['page']
    submit_button_locator = page.locator(SUBMIT_BUTTON_SELECTOR) if page else None
    completion_event = None
    
    try:
        await _validate_page_status(req_id, context, check_client_disconnected)
        
        page_controller = PageController(page, context['logger'], req_id)

        await _handle_model_switching(req_id, context, check_client_disconnected)
        await _handle_parameter_cache(req_id, context)
        
        prepared_prompt,image_list = await _prepare_and_validate_request(req_id, request, check_client_disconnected)

        # 使用PageController处理页面交互
        # 注意：聊天历史清空已移至队列处理锁释放后执行

        await page_controller.adjust_parameters(
            request.model_dump(exclude_none=True), # 使用 exclude_none=True 避免传递None值
            context['page_params_cache'],
            context['params_cache_lock'],
            context['model_id_to_use'],
            context['parsed_model_list'],
            check_client_disconnected
        )

        # 优化：在提交提示前再次检查客户端连接，避免不必要的后台请求
        check_client_disconnected("提交提示前最终检查")

        await page_controller.submit_prompt(prepared_prompt,image_list, check_client_disconnected)
        
        # 响应处理仍然需要在这里，因为它决定了是流式还是非流式，并设置future
        response_result = await _handle_response_processing(
            req_id, request, page, context, result_future, submit_button_locator, check_client_disconnected
        )
        
        if response_result:
            completion_event, _, _ = response_result
        
        return completion_event, submit_button_locator, check_client_disconnected
        
    except ClientDisconnectedError as disco_err:
        context['logger'].info(f"[{req_id}] 捕获到客户端断开连接信号: {disco_err}")
        if not result_future.done():
             result_future.set_exception(HTTPException(status_code=499, detail=f"[{req_id}] Client disconnected during processing."))
    except HTTPException as http_err:
        context['logger'].warning(f"[{req_id}] 捕获到 HTTP 异常: {http_err.status_code} - {http_err.detail}")
        if not result_future.done():
            result_future.set_exception(http_err)
    except PlaywrightAsyncError as pw_err:
        context['logger'].error(f"[{req_id}] 捕获到 Playwright 错误: {pw_err}")
        await save_error_snapshot(f"process_playwright_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(HTTPException(status_code=502, detail=f"[{req_id}] Playwright interaction failed: {pw_err}"))
    except Exception as e:
        context['logger'].exception(f"[{req_id}] 捕获到意外错误")
        await save_error_snapshot(f"process_unexpected_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(HTTPException(status_code=500, detail=f"[{req_id}] Unexpected server error: {e}"))
    finally:
        await _cleanup_request_resources(req_id, disconnect_check_task, completion_event, result_future, request.stream)
