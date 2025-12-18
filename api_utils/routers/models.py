import asyncio
import logging
import time
from asyncio import Event
from typing import Any, Dict, List, Set

from fastapi import Depends
from playwright.async_api import Page as AsyncPage

from config import DEFAULT_FALLBACK_MODEL_ID

from ..dependencies import (
    get_excluded_model_ids,
    get_logger,
    get_model_list_fetch_event,
    get_page_instance,
    get_parsed_model_list,
)


async def list_models(
    logger: logging.Logger = Depends(get_logger),
    model_list_fetch_event: Event = Depends(get_model_list_fetch_event),
    page_instance: AsyncPage = Depends(get_page_instance),
    parsed_model_list: List[Dict[str, Any]] = Depends(get_parsed_model_list),
    excluded_model_ids: Set[str] = Depends(get_excluded_model_ids),
):
    logger.debug("[API] 收到 /v1/models 请求。")

    if (
        not model_list_fetch_event.is_set()
        and page_instance
        and not page_instance.is_closed()
    ):
        logger.info("/v1/models: 模型列表事件未设置，尝试刷新页面...")
        try:
            await page_instance.reload(wait_until="domcontentloaded", timeout=20000)
            await asyncio.wait_for(model_list_fetch_event.wait(), timeout=10.0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"/v1/models: 刷新或等待模型列表时出错: {e}")
        finally:
            if not model_list_fetch_event.is_set():
                model_list_fetch_event.set()

    if parsed_model_list:
        final_model_list = [
            m
            for m in parsed_model_list
            if isinstance(m, dict) and m.get("id") not in excluded_model_ids
        ]
        return {"object": "list", "data": final_model_list}
    else:
        logger.warning("模型列表为空，返回默认后备模型。")
        return {
            "object": "list",
            "data": [
                {
                    "id": DEFAULT_FALLBACK_MODEL_ID,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "camoufox-proxy-fallback",
                }
            ],
        }
