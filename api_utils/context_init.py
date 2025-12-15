from typing import Any, cast

from logging_utils import set_request_id
from models import ChatCompletionRequest

from .context_types import RequestContext


async def initialize_request_context(
    req_id: str, request: ChatCompletionRequest, session: Any
) -> RequestContext:
    from api_utils.server_state import state

    set_request_id(req_id)
    state.logger.info("开始处理请求...")
    state.logger.info(f"  请求参数 - Model: {request.model}, Stream: {request.stream}")

    context: RequestContext = cast(
        RequestContext,
        {
            "logger": state.logger,
            "session": session,
            "page": session.page if session else None,
            "is_page_ready": session.is_ready if session else False,
            "parsed_model_list": state.parsed_model_list,
            "current_ai_studio_model_id": state.current_ai_studio_model_id,
            "model_switching_lock": state.model_switching_lock,
            "page_params_cache": state.page_params_cache,
            "params_cache_lock": state.params_cache_lock,
            "is_streaming": request.stream,
            "model_actually_switched": False,
            "requested_model": request.model,
            "model_id_to_use": None,
            "needs_model_switching": False,
        },
    )

    return context
