"""
队列工作器模块
处理请求队列中的任务
"""

import asyncio
import time
from fastapi import HTTPException
from typing import Any, Dict, Optional, Tuple
from .error_utils import (
    client_disconnected,
    client_cancelled,
    processing_timeout,
    server_error,
)
from models import QuotaExceededError


async def queue_worker() -> None:
    """队列工作器，处理请求队列中的任务"""
    # 导入全局变量
    from server import (
        logger,
        request_queue,
        processing_lock,
        model_switching_lock,
        params_cache_lock,
    )
    from config.global_state import GlobalState
    logger.info("--- 队列 Worker 已启动 ---")

    # 检查并初始化全局变量
    if request_queue is None:
        logger.info("初始化 request_queue...")
        from asyncio import Queue

        request_queue = Queue()

    if processing_lock is None:
        logger.info("初始化 processing_lock...")
        from asyncio import Lock

        processing_lock = Lock()

    if model_switching_lock is None:
        logger.info("初始化 model_switching_lock...")
        from asyncio import Lock

        model_switching_lock = Lock()

    if params_cache_lock is None:
        logger.info("初始化 params_cache_lock...")
        from asyncio import Lock

        params_cache_lock = Lock()

    was_last_request_streaming = False
    last_request_completion_time = 0

    while True:
        request_item = None
        result_future = None
        req_id = "UNKNOWN"
        completion_event = None

        try:
            # 检查队列中的项目，清理已断开连接的请求
            queue_size = request_queue.qsize()
            if queue_size > 0:
                checked_count = 0
                items_to_requeue = []
                processed_ids = set()

                while checked_count < queue_size and checked_count < 10:
                    try:
                        item = request_queue.get_nowait()
                        item_req_id = item.get("req_id", "unknown")

                        if item_req_id in processed_ids:
                            items_to_requeue.append(item)
                            continue

                        processed_ids.add(item_req_id)

                        if not item.get("cancelled", False):
                            item_http_request = item.get("http_request")
                            if item_http_request:
                                try:
                                    if await item_http_request.is_disconnected():
                                        logger.info(
                                            f"[{item_req_id}] (Worker Queue Check) 检测到客户端已断开，标记为取消。"
                                        )
                                        item["cancelled"] = True
                                        item_future = item.get("result_future")
                                        if item_future and not item_future.done():
                                            item_future.set_exception(
                                                client_disconnected(
                                                    item_req_id,
                                                    "Client disconnected while queued.",
                                                )
                                            )
                                except Exception as check_err:
                                    logger.error(
                                        f"[{item_req_id}] (Worker Queue Check) Error checking disconnect: {check_err}"
                                    )

                        items_to_requeue.append(item)
                        checked_count += 1
                    except asyncio.QueueEmpty:
                        break

                for item in items_to_requeue:
                    await request_queue.put(item)

            # 获取下一个请求
            try:
                request_item = await asyncio.wait_for(request_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # 如果5秒内没有新请求，继续循环检查
                continue

            req_id = request_item["req_id"]
            request_data = request_item["request_data"]
            http_request = request_item["http_request"]
            result_future = request_item["result_future"]

            if GlobalState.IS_QUOTA_EXCEEDED:
                logger.warning(f"[{req_id}] (Worker) ⛔ Quota exceeded flag is active. Rejecting queued request.")
                if not result_future.done():
                    result_future.set_exception(HTTPException(status_code=429, detail="Quota exceeded. Please restart with a new profile."))
                request_queue.task_done()
                continue

            if request_item.get("cancelled", False):
                logger.info(f"[{req_id}] (Worker) 请求已取消，跳过。")
                if not result_future.done():
                    result_future.set_exception(
                        client_cancelled(req_id, "请求已被用户取消")
                    )
                request_queue.task_done()
                continue

            is_streaming_request = request_data.stream
            logger.info(
                f"[{req_id}] (Worker) 取出请求。模式: {'流式' if is_streaming_request else '非流式'}"
            )

            # 优化：在开始处理前主动检测客户端连接状态，避免不必要的处理
            from api_utils.request_processor import _test_client_connection

            is_connected = await _test_client_connection(req_id, http_request)
            if not is_connected:
                logger.info(
                    f"[{req_id}] (Worker) ✅ 主动检测到客户端已断开，跳过处理节省资源"
                )
                if not result_future.done():
                    result_future.set_exception(
                        HTTPException(
                            status_code=499,
                            detail=f"[{req_id}] 客户端在处理前已断开连接",
                        )
                    )
                request_queue.task_done()
                continue

            # 流式请求间隔控制
            current_time = time.time()
            if (
                was_last_request_streaming
                and is_streaming_request
                and (current_time - last_request_completion_time < 1.0)
            ):
                delay_time = max(
                    0.5, 1.0 - (current_time - last_request_completion_time)
                )
                logger.info(
                    f"[{req_id}] (Worker) 连续流式请求，添加 {delay_time:.2f}s 延迟..."
                )
                await asyncio.sleep(delay_time)

            # 等待锁前再次主动检测客户端连接
            is_connected = await _test_client_connection(req_id, http_request)
            if not is_connected:
                logger.info(
                    f"[{req_id}] (Worker) ✅ 等待锁时检测到客户端断开，取消处理"
                )
                if not result_future.done():
                    result_future.set_exception(
                        HTTPException(
                            status_code=499, detail=f"[{req_id}] 客户端关闭了请求"
                        )
                    )
                request_queue.task_done()
                continue

            logger.info(f"[{req_id}] (Worker) 等待处理锁...")
            async with processing_lock:
                logger.info(f"[{req_id}] (Worker) 已获取处理锁。开始核心处理...")

                # 获取锁后最终主动检测客户端连接
                is_connected = await _test_client_connection(req_id, http_request)
                if not is_connected:
                    logger.info(
                        f"[{req_id}] (Worker) ✅ 获取锁后检测到客户端断开，取消处理"
                    )
                    if not result_future.done():
                        result_future.set_exception(
                            HTTPException(
                                status_code=499, detail=f"[{req_id}] 客户端关闭了请求"
                            )
                        )
                elif result_future.done():
                    logger.info(
                        f"[{req_id}] (Worker) Future 在处理前已完成/取消。跳过。"
                    )
                else:
                    # 调用实际的请求处理函数
                    try:
                        from api_utils import _process_request_refactored

                        returned_value = await _process_request_refactored(
                            req_id, request_data, http_request, result_future
                        )

                        completion_event, submit_btn_loc, client_disco_checker = (
                            None,
                            None,
                            None,
                        )
                        current_request_was_streaming = False

                        if (
                            isinstance(returned_value, tuple)
                            and len(returned_value) == 3
                        ):
                            completion_event, submit_btn_loc, client_disco_checker = (
                                returned_value
                            )
                            if completion_event is not None:
                                current_request_was_streaming = True
                                logger.info(
                                    f"[{req_id}] (Worker) _process_request_refactored returned stream info (event, locator, checker)."
                                )
                            else:
                                current_request_was_streaming = False
                                logger.info(
                                    f"[{req_id}] (Worker) _process_request_refactored returned a tuple, but completion_event is None (likely non-stream or early exit)."
                                )
                        elif returned_value is None:
                            current_request_was_streaming = False
                            logger.info(
                                f"[{req_id}] (Worker) _process_request_refactored returned non-stream completion (None)."
                            )
                        else:
                            current_request_was_streaming = False
                            logger.warning(
                                f"[{req_id}] (Worker) _process_request_refactored returned unexpected type: {type(returned_value)}"
                            )

                        # 统一的客户端断开检测和响应处理
                        if completion_event:
                            # 流式模式：等待流式生成器完成信号
                            logger.info(
                                f"[{req_id}] (Worker) 等待流式生成器完成信号..."
                            )

                            # 创建一个增强的客户端断开检测器，支持提前done信号触发
                            client_disconnected_early = False

                            async def enhanced_disconnect_monitor():
                                nonlocal client_disconnected_early
                                while not completion_event.is_set():
                                    try:
                                        # Check Global Quota State
                                        if GlobalState.IS_QUOTA_EXCEEDED:
                                            logger.critical(f"[{req_id}] (Worker) ⛔ Quota Exceeded detected mid-stream! Aborting worker wait.")
                                            client_disconnected_early = True # Treat as early exit to skip button handling
                                            if not completion_event.is_set():
                                                completion_event.set()
                                            break

                                        # 主动检查客户端是否断开连接
                                        is_connected = await _test_client_connection(
                                            req_id, http_request
                                        )
                                        if not is_connected:
                                            logger.info(
                                                f"[{req_id}] (Worker) ✅ 流式处理中检测到客户端断开，提前触发done信号"
                                            )
                                            client_disconnected_early = True
                                            # 立即设置completion_event以提前结束等待
                                            if not completion_event.is_set():
                                                completion_event.set()
                                            break
                                        await asyncio.sleep(0.3)  # 更频繁的检查间隔
                                    except Exception as e:
                                        logger.error(
                                            f"[{req_id}] (Worker) 增强断开检测器错误: {e}"
                                        )
                                        break

                            # 启动增强的断开连接监控
                            disconnect_monitor_task = asyncio.create_task(
                                enhanced_disconnect_monitor()
                            )
                        else:
                            # 非流式模式：等待处理完成并检测客户端断开
                            logger.info(
                                f"[{req_id}] (Worker) 非流式模式，等待处理完成..."
                            )

                            client_disconnected_early = False

                            async def non_streaming_disconnect_monitor():
                                nonlocal client_disconnected_early
                                while not result_future.done():
                                    try:
                                        # 主动检查客户端是否断开连接
                                        is_connected = await _test_client_connection(
                                            req_id, http_request
                                        )
                                        if not is_connected:
                                            logger.info(
                                                f"[{req_id}] (Worker) ✅ 非流式处理中检测到客户端断开，取消处理"
                                            )
                                            client_disconnected_early = True
                                            # 取消result_future
                                            if not result_future.done():
                                                result_future.set_exception(
                                                    HTTPException(
                                                        status_code=499,
                                                        detail=f"[{req_id}] 客户端在非流式处理中断开连接",
                                                    )
                                                )
                                            break
                                        await asyncio.sleep(0.3)  # 更频繁的检查间隔
                                    except Exception as e:
                                        logger.error(
                                            f"[{req_id}] (Worker) 非流式断开检测器错误: {e}"
                                        )
                                        break

                            # 启动非流式断开连接监控
                            disconnect_monitor_task = asyncio.create_task(
                                non_streaming_disconnect_monitor()
                            )

                        # 等待处理完成（流式或非流式）
                        try:
                            if completion_event:
                                # 流式模式：等待completion_event
                                from server import RESPONSE_COMPLETION_TIMEOUT

                                await asyncio.wait_for(
                                    completion_event.wait(),
                                    timeout=RESPONSE_COMPLETION_TIMEOUT / 1000 + 60,
                                )
                                logger.info(
                                    f"[{req_id}] (Worker) ✅ 流式生成器完成信号收到。客户端提前断开: {client_disconnected_early}"
                                )
                            else:
                                # 非流式模式：等待result_future完成
                                from server import RESPONSE_COMPLETION_TIMEOUT

                                await asyncio.wait_for(
                                    asyncio.shield(result_future),
                                    timeout=RESPONSE_COMPLETION_TIMEOUT / 1000 + 60,
                                )
                                logger.info(
                                    f"[{req_id}] (Worker) ✅ 非流式处理完成。客户端提前断开: {client_disconnected_early}"
                                )

                            # 如果客户端提前断开，尝试点击停止按钮以中止生成
                            if client_disconnected_early:
                                logger.info(f"[{req_id}] (Worker) 客户端提前断开，尝试停止生成...")
                                if submit_btn_loc:
                                    try:
                                        is_button_enabled = await submit_btn_loc.is_enabled(timeout=2000)
                                        if is_button_enabled:
                                            logger.info(f"[{req_id}] (Worker) 发现停止按钮可用，正在点击以中止生成...")
                                            await submit_btn_loc.click(timeout=5000, force=True)
                                            logger.info(f"[{req_id}] (Worker) ✅ 已点击停止按钮。")
                                        else:
                                            logger.info(f"[{req_id}] (Worker) 停止按钮不可用，无需操作。")
                                    except Exception as stop_err:
                                        logger.warning(f"[{req_id}] (Worker) 尝试停止生成时出错: {stop_err}")
                            elif (
                                submit_btn_loc
                                and client_disco_checker
                                and completion_event
                            ):
                                # 等待发送按钮禁用确认流式响应完全结束
                                logger.info(
                                    f"[{req_id}] (Worker) 流式响应完成，检查并处理发送按钮状态..."
                                )
                                wait_timeout_ms = 30000  # 30 seconds
                                try:
                                    from playwright.async_api import (
                                        expect as expect_async,
                                    )
                                    from api_utils.request_processor import (
                                        ClientDisconnectedError,
                                    )

                                    # 检查客户端连接状态
                                    client_disco_checker(
                                        "流式响应后按钮状态检查 - 前置检查: "
                                    )
                                    await asyncio.sleep(0.5)  # 给UI一点时间更新

                                    # 检查按钮是否仍然启用，如果启用则直接点击停止
                                    logger.info(
                                        f"[{req_id}] (Worker) 检查发送按钮状态..."
                                    )
                                    try:
                                        is_button_enabled = (
                                            await submit_btn_loc.is_enabled(
                                                timeout=2000
                                            )
                                        )
                                        logger.info(
                                            f"[{req_id}] (Worker) 发送按钮启用状态: {is_button_enabled}"
                                        )

                                        if is_button_enabled:
                                            # 流式响应完成后按钮仍启用，直接点击停止
                                            logger.info(
                                                f"[{req_id}] (Worker) 流式响应完成但按钮仍启用，主动点击按钮停止生成..."
                                            )
                                            await submit_btn_loc.click(
                                                timeout=5000, force=True
                                            )
                                            logger.info(
                                                f"[{req_id}] (Worker) ✅ 发送按钮点击完成。"
                                            )
                                        else:
                                            logger.info(
                                                f"[{req_id}] (Worker) 发送按钮已禁用，无需点击。"
                                            )
                                    except Exception as button_check_err:
                                        logger.warning(
                                            f"[{req_id}] (Worker) 检查按钮状态失败: {button_check_err}"
                                        )

                                    # 等待按钮最终禁用
                                    logger.info(
                                        f"[{req_id}] (Worker) 等待发送按钮最终禁用..."
                                    )
                                    await expect_async(submit_btn_loc).to_be_disabled(
                                        timeout=wait_timeout_ms
                                    )
                                    logger.info(f"[{req_id}] ✅ 发送按钮已禁用。")

                                except Exception as e_pw_disabled:
                                    logger.warning(
                                        f"[{req_id}] ⚠️ 流式响应后按钮状态处理超时或错误: {e_pw_disabled}"
                                    )
                                    from api_utils.request_processor import (
                                        save_error_snapshot,
                                    )

                                    await save_error_snapshot(
                                        f"stream_post_submit_button_handling_timeout_{req_id}"
                                    )
                                except ClientDisconnectedError:
                                    logger.info(
                                        f"[{req_id}] 客户端在流式响应后按钮状态处理时断开连接。"
                                    )
                            elif completion_event and current_request_was_streaming:
                                logger.warning(
                                    f"[{req_id}] (Worker) 流式请求但 submit_btn_loc 或 client_disco_checker 未提供。跳过按钮禁用等待。"
                                )

                        except asyncio.TimeoutError:
                            logger.warning(f"[{req_id}] (Worker) ⚠️ 等待处理完成超时。")
                            if not result_future.done():
                                result_future.set_exception(
                                    processing_timeout(
                                        req_id,
                                        "Processing timed out waiting for completion.",
                                    )
                                )
                        except Exception as ev_wait_err:
                            logger.error(
                                f"[{req_id}] (Worker) ❌ 等待处理完成时出错: {ev_wait_err}"
                            )
                            if not result_future.done():
                                result_future.set_exception(
                                    server_error(
                                        req_id,
                                        f"Error waiting for completion: {ev_wait_err}",
                                    )
                                )
                        finally:
                            # 清理断开连接监控任务
                            if (
                                "disconnect_monitor_task" in locals()
                                and not disconnect_monitor_task.done()
                            ):
                                disconnect_monitor_task.cancel()
                                try:
                                    await disconnect_monitor_task
                                except asyncio.CancelledError:
                                    pass

                    except Exception as process_err:
                        logger.error(
                            f"[{req_id}] (Worker) _process_request_refactored execution error: {process_err}"
                        )
                        if not result_future.done():
                            result_future.set_exception(
                                server_error(
                                    req_id, f"Request processing error: {process_err}"
                                )
                            )

                # 在释放处理锁前执行清空操作，确保原子性
                try:
                    # 清空流式队列缓存
                    from api_utils import clear_stream_queue
                    await clear_stream_queue()
                    
                    # [FIX-03] Worker Cleanup Short-Circuit
                    if GlobalState.IS_QUOTA_EXCEEDED:
                        logger.warning(f"[{req_id}] (Worker) ⛔ Quota Exceeded flag detected! Skipping chat history cleanup to allow immediate rotation.")
                    elif submit_btn_loc and client_disco_checker:
                        from server import page_instance, is_page_ready
                        if page_instance and is_page_ready:
                            from browser_utils.page_controller import PageController
                            page_controller = PageController(page_instance, logger, req_id)
                            logger.info(f"[{req_id}] (Worker) 执行聊天历史清空（{'流式' if completion_event else '非流式'}模式）...")
                            
                            # 使用 dummy checker 确保清空操作不受客户端断开影响
                            # 这是一个维护性任务，必须完成，不能因为客户端断开而中断
                            dummy_checker = lambda stage: False
                            
                            try:
                                await page_controller.clear_chat_history(dummy_checker)
                                logger.info(f"[{req_id}] (Worker) ✅ 聊天历史清空完成。")
                            except Exception as clear_chat_err:
                                logger.error(f"[{req_id}] (Worker) ❌ 聊天历史清空失败: {clear_chat_err}")
                                # 如果清空失败（例如因为页面状态错误），强制刷新页面以重置状态
                                # 这能防止下一个请求卡死
                                logger.warning(f"[{req_id}] (Worker) 尝试刷新页面以恢复状态...")
                                try:
                                    await page_instance.reload()
                                    logger.info(f"[{req_id}] (Worker) ✅ 页面刷新成功。")
                                except Exception as reload_err:
                                    logger.error(f"[{req_id}] (Worker) ❌ 页面刷新失败: {reload_err}")

                    else:
                        logger.info(f"[{req_id}] (Worker) 跳过聊天历史清空：缺少必要参数（submit_btn_loc: {bool(submit_btn_loc)}, client_disco_checker: {bool(client_disco_checker)}）")
                except Exception as clear_err:
                    logger.error(f"[{req_id}] (Worker) 清空操作时发生错误: {clear_err}", exc_info=True)
                
                logger.info(f"[{req_id}] (Worker) 释放处理锁。")

            was_last_request_streaming = is_streaming_request
            last_request_completion_time = time.time()

        except asyncio.CancelledError:
            logger.info("--- 队列 Worker 被取消 ---")
            if result_future and not result_future.done():
                result_future.cancel("Worker cancelled")
            break
        except QuotaExceededError as qe:
            logger.error(f"[{req_id}] ⛔ CRITICAL: {qe}")
            if result_future and not result_future.done():
                # Mark this auth profile as 'exhausted' (optional future task).
                # Return 429 (Too Many Requests) to the client.
                result_future.set_exception(HTTPException(status_code=429, detail="Account quota exceeded. Please try a different account."))
        except Exception as e:
            logger.error(f"[{req_id}] (Worker) ❌ 处理请求时发生意外错误: {e}", exc_info=True)
            if result_future and not result_future.done():
                result_future.set_exception(server_error(req_id, f"服务器内部错误: {e}"))
        finally:
            if request_item:
                request_queue.task_done()
    
    logger.info("--- 队列 Worker 已停止 ---")