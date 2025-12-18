import asyncio
import json
from typing import Any, AsyncGenerator

from logging_utils import set_request_id


async def use_stream_response(req_id: str) -> AsyncGenerator[Any, None]:
    import queue

    from api_utils.server_state import state
    from server import STREAM_QUEUE, logger

    set_request_id(req_id)
    if STREAM_QUEUE is None:
        logger.warning("STREAM_QUEUE is None, 无法使用流响应")
        return

    logger.info("开始使用流响应")

    empty_count = 0
    max_empty_retries = 300
    data_received = False
    has_content = False
    received_items_count = 0
    stale_done_ignored = False

    try:
        while True:
            # Check shutdown signal FIRST - every loop iteration
            if state.should_exit:
                logger.info("Shutdown signal received, terminating stream.")
                return

            try:
                data = STREAM_QUEUE.get_nowait()
                if data is None:
                    logger.debug("[Stream] 接收到流结束标志 (None)")
                    break
                empty_count = 0
                data_received = True
                received_items_count += 1

                if isinstance(data, str):
                    try:
                        parsed_data = json.loads(data)

                        # FAIL-FAST: 检测来自 stream proxy 的错误信号
                        if parsed_data.get("error") is True:
                            error_status = parsed_data.get("status", 500)
                            error_message = parsed_data.get(
                                "message", "Unknown upstream error"
                            )
                            logger.error(
                                f"[UPSTREAM ERROR] Detected from stream proxy: {error_status} - {error_message}"
                            )

                            # 根据状态码抛出相应异常，立即中止并触发重试逻辑
                            from models.exceptions import (
                                QuotaExceededError,
                                UpstreamError,
                            )

                            if error_status == 429 or "quota" in error_message.lower():
                                logger.warning(
                                    "[FAIL-FAST] Raising QuotaExceededError for tier switch"
                                )
                                raise QuotaExceededError(
                                    message=f"AI Studio quota exceeded: {error_message}",
                                    req_id=req_id,
                                )
                            else:
                                logger.warning(
                                    "[FAIL-FAST] Raising UpstreamError for tier switch"
                                )
                                raise UpstreamError(
                                    message=f"AI Studio error: {error_message}",
                                    req_id=req_id,
                                    status_code=error_status,
                                )

                        if parsed_data.get("done") is True:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            if body or reason:
                                has_content = True
                            logger.debug(
                                f"[Stream] 捕获完成标志 (body:{len(body)}, reason:{len(reason)}, count:{received_items_count})"
                            )
                            if (
                                not has_content
                                and received_items_count == 1
                                and not stale_done_ignored
                            ):
                                logger.warning(
                                    "[STALE DATA] 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待..."
                                )
                                stale_done_ignored = True
                                continue
                            yield parsed_data
                            break
                        else:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            if body or reason:
                                has_content = True
                            stale_done_ignored = False
                            yield parsed_data
                    except json.JSONDecodeError:
                        logger.debug("[Stream] 返回非 JSON 字符串数据")
                        has_content = True
                        stale_done_ignored = False
                        yield data
                else:
                    yield data
                    if isinstance(data, dict):
                        body = data.get("body", "")
                        reason = data.get("reason", "")
                        if body or reason:
                            has_content = True
                        if data.get("done") is True:
                            logger.debug(
                                f"[Stream] 捕获完成标志 (body:{len(body)}, reason:{len(reason)}, count:{received_items_count})"
                            )
                            if (
                                not has_content
                                and received_items_count == 1
                                and not stale_done_ignored
                            ):
                                logger.warning(
                                    "[STALE DATA] 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待..."
                                )
                                stale_done_ignored = True
                                continue
                            break
                        else:
                            stale_done_ignored = False
            except (queue.Empty, asyncio.QueueEmpty):
                empty_count += 1
                if empty_count % 50 == 0:
                    logger.debug(
                        f"[Stream] 等待数据... ({empty_count}/{max_empty_retries}, 已接收:{received_items_count})"
                    )
                if empty_count >= max_empty_retries:
                    if not data_received:
                        logger.error(
                            "流响应队列空读取次数达到上限且未收到任何数据，可能是辅助流未启动或出错"
                        )
                    else:
                        logger.warning(
                            f"流响应队列空读取次数达到上限 ({max_empty_retries})，结束读取"
                        )
                    yield {
                        "done": True,
                        "reason": "internal_timeout",
                        "body": "",
                        "function": [],
                    }
                    return
                await asyncio.sleep(0.1)
                continue
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"使用流响应时出错: {e}", exc_info=True)
        raise
    finally:
        pass  # Stream completion logged by capture flag


async def clear_stream_queue():
    import queue

    from server import STREAM_QUEUE, logger

    if STREAM_QUEUE is None:
        logger.debug("[Stream] 队列未初始化或已禁用，跳过清空")
        return

    cleared_count = 0
    while True:
        try:
            data_chunk = await asyncio.to_thread(STREAM_QUEUE.get_nowait)
            cleared_count += 1
            if cleared_count <= 3:
                logger.debug(
                    f"[Stream] 清空队列项 #{cleared_count}: {type(data_chunk).__name__}"
                )
        except queue.Empty:
            logger.debug(f"[Stream] 队列已清空 (共 {cleared_count} 项)")
            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                f"清空流式队列时发生意外错误 (已清空{cleared_count}项): {e}",
                exc_info=True,
            )
            break

    # [Stream] 队列已清空 log above is sufficient
