import os
import random
import time
import logging
from asyncio import Queue, Future
from fastapi import Depends, HTTPException, Request
from ..dependencies import get_logger, get_request_queue, get_server_state, get_worker_task
from config import RESPONSE_COMPLETION_TIMEOUT
from config.global_state import GlobalState
from models import ChatCompletionRequest
import asyncio
from fastapi.responses import JSONResponse
from config import get_environment_variable
from ..error_utils import service_unavailable


async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    logger: logging.Logger = Depends(get_logger),
    request_queue: Queue = Depends(get_request_queue),
    server_state: dict = Depends(get_server_state),
    worker_task = Depends(get_worker_task)
) -> JSONResponse:
    req_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=7))
    logger.info(f"[{req_id}] 收到 /v1/chat/completions 请求 (Stream={request.stream})")

    if GlobalState.IS_QUOTA_EXCEEDED:
        logger.warning(f"[{req_id}] ⛔ Rejected incoming request due to active Quota Lock.")
        raise HTTPException(status_code=503, detail={"error": "Quota exceeded. System is rotating credentials. Please retry in a few seconds."})

    launch_mode = get_environment_variable('LAUNCH_MODE', 'unknown')
    browser_page_critical = launch_mode != "direct_debug_no_browser"

    service_unavailable = server_state["is_initializing"] or \
                          not server_state["is_playwright_ready"] or \
                          (browser_page_critical and (not server_state["is_page_ready"] or not server_state["is_browser_connected"])) or \
                          not worker_task or worker_task.done()

    if service_unavailable:
        raise service_unavailable(req_id)

    result_future = Future()
    await request_queue.put({
        "req_id": req_id, "request_data": request, "http_request": http_request,
        "result_future": result_future, "enqueue_time": time.time(), "cancelled": False
    })

    try:
        timeout_seconds = RESPONSE_COMPLETION_TIMEOUT / 1000 + 120
        return await asyncio.wait_for(result_future, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"[{req_id}] 请求处理超时。")
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail=f"[{req_id}] 请求被客户端取消。")
    except HTTPException as http_exc:
        if http_exc.status_code == 499:
            logger.info(f"[{req_id}] 客户端断开连接: {http_exc.detail}")
        else:
            logger.warning(f"[{req_id}] HTTP异常: {http_exc.detail}")
        raise http_exc
    except Exception as e:
        logger.exception(f"[{req_id}] 等待Worker响应时出错")
        raise HTTPException(status_code=500, detail=f"[{req_id}] 服务器内部错误: {e}")
