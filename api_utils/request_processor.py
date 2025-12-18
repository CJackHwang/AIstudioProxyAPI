"""
Request Processor Module
Contains core request processing logic.
"""

import asyncio
import json
import logging
import os
from asyncio import Event, Future
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Type aliases for common function signatures
CheckClientDisconnected = Callable[[str], bool]
Logger = logging.Logger
from playwright.async_api import (
    Error as PlaywrightAsyncError,
)
from playwright.async_api import (
    Locator,
)
from playwright.async_api import (
    Page as AsyncPage,
)

# --- Browser Utils Imports ---
from browser_utils import save_error_snapshot
from browser_utils.page_controller import PageController

# --- Config Imports ---
from config import (
    MODEL_NAME,
    ONLY_COLLECT_CURRENT_USER_ATTACHMENTS,
    SUBMIT_BUTTON_SELECTOR,
    UPLOAD_FILES_DIR,
)

# --- Logging Utils Imports ---
from logging_utils import log_context, set_request_id, set_source

# --- Models Imports ---
from models import ChatCompletionRequest, ClientDisconnectedError

from .client_connection import (
    check_client_connection as _check_client_connection,
)
from .client_connection import (
    setup_disconnect_monitoring as _setup_disconnect_monitoring,
)
from .common_utils import random_id as _random_id
from .context_init import initialize_request_context as _init_request_context
from .context_types import RequestContext
from .model_switching import (
    analyze_model_requirements as ms_analyze,
)
from .model_switching import (
    handle_model_switching as ms_switch,
)
from .model_switching import (
    handle_parameter_cache as ms_param_cache,
)
from .page_response import locate_response_elements
from .response_generators import gen_sse_from_aux_stream, gen_sse_from_playwright
from .response_payloads import build_chat_completion_response_json

# --- API Utils Imports ---
from .utils import (
    maybe_execute_tools,
    prepare_combined_prompt,
)
from .utils_ext.stream import use_stream_response
from .utils_ext.tokens import calculate_usage_stats
from .utils_ext.validation import validate_chat_request

_initialize_request_context = _init_request_context

# Error helpers
from .error_utils import (
    bad_request,
    client_disconnected,
    server_error,
    upstream_error,
)


async def _analyze_model_requirements(
    req_id: str, context: RequestContext, request: ChatCompletionRequest
) -> RequestContext:
    """Delegates to model_switching.analyze_model_requirements"""
    return await ms_analyze(req_id, context, request.model or "", MODEL_NAME)


async def _validate_page_status(
    req_id: str,
    context: RequestContext,
    check_client_disconnected: CheckClientDisconnected,
) -> None:
    """Validates page status"""
    page = context["page"]
    is_page_ready = context["is_page_ready"]

    if not page or page.is_closed() or not is_page_ready:
        raise HTTPException(
            status_code=503,
            detail=f"[{req_id}] AI Studio page lost or not ready.",
            headers={"Retry-After": "30"},
        )

    check_client_disconnected("Initial Page Check")


async def _handle_model_switching(
    req_id: str,
    context: RequestContext,
    check_client_disconnected: CheckClientDisconnected,
) -> RequestContext:
    """Delegates to model_switching.handle_model_switching"""
    return await ms_switch(req_id, context)


async def _handle_model_switch_failure(  # pyright: ignore[reportUnusedFunction] - Called by tests
    req_id: str,
    page: AsyncPage,
    model_id_to_use: str,
    model_before_switch: str,
    logger: Logger,
) -> None:
    """Handles model switching failure"""
    from api_utils.server_state import state

    set_request_id(req_id)
    logger.warning(f"Model switch to {model_id_to_use} failed.")
    # Try to restore global state
    state.current_ai_studio_model_id = model_before_switch

    raise HTTPException(
        status_code=422,
        detail=f"[{req_id}] Failed to switch to model '{model_id_to_use}'. Please ensure model is available.",
    )


async def _handle_parameter_cache(  # pyright: ignore[reportUnusedFunction] - Called by tests
    req_id: str, context: RequestContext
) -> None:
    """Delegates to model_switching.handle_parameter_cache"""
    await ms_param_cache(req_id, context)


async def _prepare_and_validate_request(
    req_id: str,
    request: ChatCompletionRequest,
    check_client_disconnected: CheckClientDisconnected,
) -> Tuple[str, List[str]]:
    """Prepares and validates request, returns (combined_prompt, images_list)."""
    try:
        validate_chat_request(request.messages, req_id)
    except ValueError as e:
        raise bad_request(req_id, f"Invalid request: {e}")

    prepared_prompt, images_list = prepare_combined_prompt(
        request.messages,
        req_id,
        getattr(request, "tools", None),
        getattr(request, "tool_choice", None),
    )

    # Active function execution based on tools/tool_choice (supports per-request MCP endpoint)
    try:
        # Inject mcp_endpoint into utils.maybe_execute_tools registration logic
        if hasattr(request, "mcp_endpoint") and request.mcp_endpoint:
            from .tools_registry import register_runtime_tools

            register_runtime_tools(
                getattr(request, "tools", None), request.mcp_endpoint
            )
        tool_exec_results = await maybe_execute_tools(
            request.messages, request.tools, getattr(request, "tool_choice", None)
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        tool_exec_results = None

    check_client_disconnected("After Prompt Prep")

    # Inline results at the end of prompt for web submission
    if tool_exec_results:
        try:
            for res in tool_exec_results:
                name = res.get("name")
                args = res.get("arguments")
                result_str = res.get("result")
                prepared_prompt += f"\n---\nTool Execution: {name}\nArguments:\n{args}\nResult:\n{result_str}\n"
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # Filter attachments if configured to only collect current user attachments
    try:
        if ONLY_COLLECT_CURRENT_USER_ATTACHMENTS:
            latest_user = None
            for msg in reversed(request.messages or []):
                if getattr(msg, "role", None) == "user":
                    latest_user = msg
                    break
            if latest_user is not None:
                filtered: List[str] = []
                import os
                from urllib.parse import unquote, urlparse

                from api_utils.utils import extract_data_url_to_local

                # Collect data:/file:/absolute paths (existing) from this user message
                getattr(latest_user, "content", None)
                # Unified extraction from messages attachment fields
                for key in ("attachments", "images", "files", "media"):
                    arr: Any = getattr(latest_user, key, None)
                    if not isinstance(arr, list):
                        continue
                    # Type narrowing after isinstance check
                    for it in arr:
                        url_value: Optional[str] = None
                        if isinstance(it, str):
                            url_value = it
                        elif isinstance(it, dict):
                            # Type narrowed to dict by isinstance
                            url_value = str(it.get("url") or it.get("path") or "")
                        if not url_value:
                            continue
                        url_value = url_value.strip()
                        if not url_value:
                            continue
                        if url_value.startswith("data:"):
                            fp: Optional[str] = extract_data_url_to_local(url_value)
                            if fp:
                                filtered.append(fp)
                        elif url_value.startswith("file:"):
                            parsed = urlparse(url_value)
                            lp: str = unquote(parsed.path)
                            if os.path.exists(lp):
                                filtered.append(lp)
                        elif os.path.isabs(url_value) and os.path.exists(url_value):
                            filtered.append(url_value)
                images_list = filtered
    except asyncio.CancelledError:
        raise
    except Exception:
        pass

    return prepared_prompt, images_list


async def _handle_response_processing(
    req_id: str,
    request: ChatCompletionRequest,
    page: Optional[AsyncPage],
    context: RequestContext,
    result_future: Future[Union[StreamingResponse, JSONResponse]],
    submit_button_locator: Optional[Locator],
    check_client_disconnected: CheckClientDisconnected,
) -> Optional[Tuple[Optional[Event], Locator, CheckClientDisconnected]]:
    """Handles response generation"""
    import logging

    logging.getLogger("AIStudioProxyServer")

    context.get("current_ai_studio_model_id")

    # Check if using auxiliary stream
    from config import get_environment_variable

    stream_port = get_environment_variable("STREAM_PORT")
    use_stream = stream_port != "0"

    if use_stream:
        if submit_button_locator is None:
            raise server_error(
                req_id, "Submit button locator is None in _handle_response_processing"
            )
        return await _handle_auxiliary_stream_response(
            req_id,
            request,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )
    else:
        if page is None:
            raise server_error(req_id, "Page is None in _handle_response_processing")
        if submit_button_locator is None:
            raise server_error(
                req_id, "Submit button locator is None in _handle_response_processing"
            )
        # RequestContext is a TypedDict, which is structurally compatible with Dict[str, Any]
        # at runtime, but we need explicit typing for the function signature
        return await _handle_playwright_response(
            req_id,
            request,
            page,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )


async def _handle_auxiliary_stream_response(
    req_id: str,
    request: ChatCompletionRequest,
    context: RequestContext,
    result_future: Future[Union[StreamingResponse, JSONResponse]],
    submit_button_locator: Locator,
    check_client_disconnected: CheckClientDisconnected,
) -> Optional[Tuple[Optional[Event], Locator, CheckClientDisconnected]]:
    """Auxiliary stream response path: converts STREAM_QUEUE data to OpenAI compatible SSE/JSON.

    - Streaming mode: Returns StreamingResponse, pushing delta and final usage incrementally.
    - Non-streaming mode: Aggregates final content and function calls, returns JSONResponse.
    """
    import logging

    logger = logging.getLogger("AIStudioProxyServer")

    is_streaming = request.stream
    current_ai_studio_model_id = context.get("current_ai_studio_model_id")
    completion_event: Optional[Event] = None

    if is_streaming:
        try:
            completion_event = Event()
            # 创建 stream_state 用于跟踪流是否收到内容
            stream_state: Dict[str, Any] = {"has_content": False}
            # Use generator as response body, handled by FastAPI for SSE push
            stream_gen_func = gen_sse_from_aux_stream(
                req_id,
                request,
                current_ai_studio_model_id or MODEL_NAME,
                check_client_disconnected,
                completion_event,
                stream_state,
            )
            if not result_future.done():
                result_future.set_result(
                    StreamingResponse(stream_gen_func, media_type="text/event-stream")
                )
            else:
                if not completion_event.is_set():
                    completion_event.set()

            # Return only first 3 elements to match function signature
            # stream_state is used internally by the caller but not part of return type
            return (
                completion_event,
                submit_button_locator,
                check_client_disconnected,
            )

        except asyncio.CancelledError:
            if completion_event and not completion_event.is_set():
                completion_event.set()
            raise
        except Exception as e:
            logger.error(f"Error getting stream data from queue: {e}", exc_info=True)
            if completion_event and not completion_event.is_set():
                completion_event.set()
            raise

    else:  # Non-streaming
        content: Optional[str] = None
        reasoning_content: Optional[str] = None
        functions: Optional[List[Dict[str, Any]]] = None
        final_data_from_aux_stream: Optional[Dict[str, Any]] = None

        # Non-streaming: Consume auxiliary queue final result and assemble JSON response
        async for raw_data in use_stream_response(req_id):
            check_client_disconnected(f"Non-streaming Aux Stream - Loop ({req_id}): ")

            # Ensure data is dict type
            data: Dict[str, Any]
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse non-stream data JSON: {raw_data}")
                    continue
            elif isinstance(raw_data, dict):
                # Type narrowed to dict by isinstance check
                data = raw_data  # type: Dict[str, Any]
            else:
                logger.warning(f"Non-stream unknown data type: {type(raw_data)}")
                continue

            final_data_from_aux_stream = data
            if data.get("done"):
                content = data.get("body")
                reasoning_content = data.get("reason")
                functions = data.get("function")
                break

        if (
            final_data_from_aux_stream
            and final_data_from_aux_stream.get("reason") == "internal_timeout"
        ):
            logger.error(
                "Non-streaming request failed via aux stream: Internal Timeout"
            )
            raise HTTPException(
                status_code=502,
                detail=f"[{req_id}] Aux stream processing error (Internal Timeout)",
            )

        if (
            final_data_from_aux_stream
            and final_data_from_aux_stream.get("done") is True
            and content is None
            and not functions
        ):
            logger.error(
                "Non-streaming request completed via aux stream but no content provided"
            )
            raise HTTPException(
                status_code=502,
                detail=f"[{req_id}] Aux stream completed but no content provided",
            )

        model_name_for_json = current_ai_studio_model_id or MODEL_NAME
        message_payload: Dict[str, Any] = {"role": "assistant", "content": content}
        finish_reason_val = "stop"

        if functions and len(functions) > 0:
            tool_calls_list: List[Dict[str, Any]] = []
            func_idx: int
            function_call_data: Dict[str, Any]
            for func_idx, function_call_data in enumerate(functions):
                tool_calls_list.append(
                    {
                        "id": f"call_{_random_id()}",
                        "index": func_idx,
                        "type": "function",
                        "function": {
                            "name": function_call_data["name"],
                            "arguments": json.dumps(function_call_data["params"]),
                        },
                    }
                )
            message_payload["tool_calls"] = tool_calls_list
            finish_reason_val = "tool_calls"
            message_payload["content"] = None

        if reasoning_content:
            message_payload["reasoning_content"] = reasoning_content

        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            content or "",
            reasoning_content or "",
        )

        response_payload = build_chat_completion_response_json(
            req_id,
            model_name_for_json,
            message_payload,
            finish_reason_val,
            usage_stats,
            system_fingerprint="camoufox-proxy",
            seed=request.seed
            if hasattr(request, "seed") and request.seed is not None
            else 0,
            response_format=(
                request.response_format
                if hasattr(request, "response_format")
                and isinstance(request.response_format, dict)
                else {}
            ),
        )

        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))
        return None


async def _handle_playwright_response(
    req_id: str,
    request: ChatCompletionRequest,
    page: AsyncPage,
    context: Union[RequestContext, Dict[str, Any]],
    result_future: Future[Union[StreamingResponse, JSONResponse]],
    submit_button_locator: Locator,
    check_client_disconnected: CheckClientDisconnected,
) -> Optional[Tuple[Optional[Event], Locator, CheckClientDisconnected]]:
    """Handle response using Playwright"""
    import logging

    logger = logging.getLogger("AIStudioProxyServer")

    is_streaming = request.stream
    current_ai_studio_model_id = context.get("current_ai_studio_model_id")

    await locate_response_elements(page, req_id, logger, check_client_disconnected)

    check_client_disconnected("After Response Element Located: ")

    if is_streaming:
        completion_event = Event()
        stream_gen_func = gen_sse_from_playwright(
            page,
            logger,
            req_id,
            current_ai_studio_model_id or MODEL_NAME,
            request,
            check_client_disconnected,
            completion_event,
        )
        if not result_future.done():
            result_future.set_result(
                StreamingResponse(stream_gen_func, media_type="text/event-stream")
            )

        return completion_event, submit_button_locator, check_client_disconnected
    else:
        # Use PageController to get response
        page_controller = PageController(page, logger, req_id)
        final_content = await page_controller.get_response(check_client_disconnected)

        # Calculate token usage stats
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            final_content,
            "",  # Playwright mode has no reasoning content
        )
        logger.info(f"Playwright non-streaming token usage stats: {usage_stats}")

        # Unified OpenAI compatible response construction
        model_name_for_json = current_ai_studio_model_id or MODEL_NAME
        message_payload = {"role": "assistant", "content": final_content}
        finish_reason_val = "stop"
        response_payload = build_chat_completion_response_json(
            req_id,
            model_name_for_json,
            message_payload,
            finish_reason_val,
            usage_stats,
            system_fingerprint="camoufox-proxy",
            seed=request.seed
            if hasattr(request, "seed") and request.seed is not None
            else 0,
            response_format=(
                request.response_format
                if hasattr(request, "response_format")
                and isinstance(request.response_format, dict)
                else {}
            ),
        )

        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))

        return None


async def _cleanup_request_resources(
    req_id: str,
    disconnect_check_task: Optional[asyncio.Task[None]],
    completion_event: Optional[Event],
    result_future: Future[Union[StreamingResponse, JSONResponse]],
    is_streaming: bool,
) -> None:
    """Clean up request resources"""
    import logging

    logger = logging.getLogger("AIStudioProxyServer")
    import shutil

    # 确保日志上下文已设置
    set_request_id(req_id)

    if disconnect_check_task and not disconnect_check_task.done():
        disconnect_check_task.cancel()
        try:
            await disconnect_check_task
        except asyncio.CancelledError:
            pass

    # Processing logged at higher level

    # Clean up upload subdirectory for this request to avoid disk accumulation
    try:
        req_dir = os.path.join(UPLOAD_FILES_DIR, req_id)
        if os.path.isdir(req_dir):
            shutil.rmtree(req_dir, ignore_errors=True)
            logger.debug(f"Cleaned up request upload directory: {req_dir}")
    except asyncio.CancelledError:
        raise
    except Exception as clean_err:
        logger.warning(f"Failed to clean upload directory: {clean_err}")

    if (
        is_streaming
        and completion_event
        and not completion_event.is_set()
        and (result_future.done() and result_future.exception() is not None)
    ):
        logger.warning("Streaming request exception, ensuring completion event is set.")
        completion_event.set()
    return None


async def _process_request_refactored(  # pyright: ignore[reportUnusedFunction] - Called by queue_worker.py
    req_id: str,
    request: ChatCompletionRequest,
    http_request: Request,
    result_future: Future[Union[StreamingResponse, JSONResponse]],
) -> Optional[Tuple[Optional[Event], Locator, CheckClientDisconnected]]:
    """Core request processing function - Refactored"""
    # 设置日志上下文 (Grid Logger)
    set_request_id(req_id)
    set_source("PROCESSOR")

    # Optimization: Proactively check client connection before starting any processing
    import logging

    logger = logging.getLogger("AIStudioProxyServer")
    from config import get_environment_variable

    is_connected = await _check_client_connection(req_id, http_request)
    if not is_connected:
        logger.info(
            "Client disconnected before core processing, exiting early to save resources"
        )
        if not result_future.done():
            result_future.set_exception(
                HTTPException(
                    status_code=499,
                    detail=f"[{req_id}] Client disconnected before processing started",
                )
            )
        return None

    stream_port = get_environment_variable("STREAM_PORT")
    use_stream = stream_port != "0"
    if use_stream:
        try:
            from api_utils import clear_stream_queue

            await clear_stream_queue()
        except asyncio.CancelledError:
            raise
        except Exception as clear_err:
            logger.warning(f"[Stream] 清空队列错误: {clear_err}")

    context = await _initialize_request_context(req_id, request)
    context = await _analyze_model_requirements(req_id, context, request)

    (
        _,  # client_disconnected_event - not used, kept for unpacking
        disconnect_check_task,
        check_client_disconnected,
    ) = await _setup_disconnect_monitoring(req_id, http_request, result_future)

    page = context["page"]
    submit_button_locator = page.locator(SUBMIT_BUTTON_SELECTOR) if page else None
    completion_event = None

    try:
        await _validate_page_status(req_id, context, check_client_disconnected)

        if page is None:
            raise server_error(req_id, "Page is None in _process_request_refactored")

        page_controller = PageController(page, context["logger"], req_id)

        await _handle_model_switching(req_id, context, check_client_disconnected)
        await _handle_parameter_cache(req_id, context)

        # Wrap entire processing section in silent context for visual hierarchy
        # This creates the base indentation level for Prompt Prep, Parameters, and Execution
        with log_context("", context["logger"], silent=True):
            prepared_prompt, image_list = await _prepare_and_validate_request(
                req_id, request, check_client_disconnected
            )

            # Extra merge of top-level and message-level attachments/files (compatible with history)
            # Attachment source strategy: Only accept data:/file:/absolute paths (existing) explicitly provided in current request
            from api_utils.utils import collect_and_validate_attachments

            # image_list is already List[str] from _prepare_and_validate_request
            image_list = collect_and_validate_attachments(request, req_id, image_list)

            # Use PageController for page interaction
            # Note: Chat history clearing moved to after queue processing lock release

            request_params = request.model_dump(exclude_none=True)
            # Fix: If stop is explicitly set to None (e.g. sent as null), preserve it to avoid default fallback
            if "stop" in request.model_fields_set and request.stop is None:
                request_params["stop"] = None

            # Wrap parameter adjustment in silent context
            with log_context("Adjusting Parameters", context["logger"], silent=True):
                await page_controller.adjust_parameters(
                    request_params,
                    context["page_params_cache"],
                    context["params_cache_lock"],
                    context["model_id_to_use"],
                    context["parsed_model_list"],
                    check_client_disconnected,
                )

            # Optimization: Final check of client connection before submitting prompt
            check_client_disconnected("Final check before submitting prompt")

            # Wrap prompt submission in silent context
            with log_context("Execution", context["logger"], silent=True):
                await page_controller.submit_prompt(
                    prepared_prompt, image_list, check_client_disconnected
                )

        # Response processing still needs to be here as it determines streaming vs non-streaming and sets future
        response_result = await _handle_response_processing(
            req_id,
            request,
            page,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )

        if response_result:
            # 动态解包，支持 3-tuple 和 4-tuple (带 stream_state)
            if len(response_result) >= 1:
                completion_event = response_result[0]
            # 其他元素 (submit_btn_loc, check_client_disconnected, stream_state)
            # 在 _process_request_refactored 返回时会被正确传递

        if submit_button_locator is None:
            # Should have been caught earlier, but for safety
            return None

        # 直接返回 response_result (可能是 3-tuple 或 4-tuple)
        # queue_worker 已更新为动态处理不同长度的元组
        # Type note: response_result can be 3-tuple or 4-tuple, we return only first 3 elements
        # The return type allows Optional[Event], so None completion_event is valid
        if response_result and len(response_result) >= 3:
            # Extract first 3 elements: (Optional[Event], Locator, CheckClientDisconnected)
            return (response_result[0], response_result[1], response_result[2])

        # If no response_result, return the constructed tuple
        # Note: completion_event can be None for non-streaming responses
        return (completion_event, submit_button_locator, check_client_disconnected)

    except ClientDisconnectedError as disco_err:
        context["logger"].info(f"Caught client disconnected signal: {disco_err}")
        if not result_future.done():
            result_future.set_exception(
                client_disconnected(req_id, "Client disconnected during processing.")
            )
    except asyncio.CancelledError:
        context["logger"].info("Request cancelled.")
        if not result_future.done():
            result_future.cancel()
        raise  # Re-raise CancelledError
    except HTTPException as http_err:
        context["logger"].warning(
            f"Caught HTTP Exception: {http_err.status_code} - {http_err.detail}"
        )
        if not result_future.done():
            result_future.set_exception(http_err)
    except PlaywrightAsyncError as pw_err:
        context["logger"].error(f"Caught Playwright Error: {pw_err}")
        await save_error_snapshot(f"process_playwright_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(
                upstream_error(req_id, f"Playwright interaction failed: {pw_err}")
            )
    except Exception as e:
        context["logger"].exception("Caught unexpected error")
        await save_error_snapshot(f"process_unexpected_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(
                server_error(req_id, f"Unexpected server error: {e}")
            )
    finally:
        await _cleanup_request_resources(
            req_id,
            disconnect_check_task,
            completion_event,
            result_future,
            request.stream or False,
        )

    return None
