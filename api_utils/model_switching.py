import logging

from playwright.async_api import Page as AsyncPage

from api_utils.server_state import state
from logging_utils import set_request_id

from .context_types import RequestContext


async def analyze_model_requirements(
    req_id: str, context: RequestContext, requested_model: str, proxy_model_name: str
) -> RequestContext:
    set_request_id(req_id)
    logger = context["logger"]
    current_ai_studio_model_id = context["current_ai_studio_model_id"]
    parsed_model_list = context["parsed_model_list"]

    if requested_model and requested_model != proxy_model_name:
        requested_model_id = requested_model.split("/")[-1]

        if parsed_model_list:
            valid_model_ids = [
                str(m.get("id")) for m in parsed_model_list if m.get("id")
            ]
            if requested_model_id not in valid_model_ids:
                from .error_utils import bad_request

                raise bad_request(
                    req_id,
                    f"Invalid model '{requested_model_id}'. Available models: {', '.join(valid_model_ids)}",
                )

        context["model_id_to_use"] = requested_model_id
        if current_ai_studio_model_id != requested_model_id:
            context["needs_model_switching"] = True
            logger.debug(
                f"[Model] 判定需切换: {current_ai_studio_model_id} -> {requested_model_id}"
            )

    return context


async def handle_model_switching(
    req_id: str, context: RequestContext
) -> RequestContext:
    set_request_id(req_id)
    if not context["needs_model_switching"]:
        return context

    logger = context["logger"]
    page = context["page"]
    model_switching_lock = context["model_switching_lock"]
    model_id_to_use = context["model_id_to_use"]

    # Assert non-None values required for model switching
    assert page is not None, "Page must be ready for model switching"
    assert model_id_to_use is not None, "Target model ID must be set"

    async with model_switching_lock:
        if state.current_ai_studio_model_id != model_id_to_use:
            from browser_utils import switch_ai_studio_model

            switch_success = await switch_ai_studio_model(page, model_id_to_use, req_id)
            if switch_success:
                state.current_ai_studio_model_id = model_id_to_use
                context["model_actually_switched"] = True
                context["current_ai_studio_model_id"] = model_id_to_use
            else:
                # Current model ID should exist when switching fails
                current_model = state.current_ai_studio_model_id or "unknown"
                await _handle_model_switch_failure(
                    req_id,
                    page,
                    model_id_to_use,
                    current_model,
                    logger,
                )

    return context


async def _handle_model_switch_failure(
    req_id: str,
    page: AsyncPage,
    model_id_to_use: str,
    model_before_switch: str,
    logger: logging.Logger,
) -> None:
    set_request_id(req_id)
    logger.warning(f"模型切换至 {model_id_to_use} 失败。")
    state.current_ai_studio_model_id = model_before_switch
    from .error_utils import http_error

    raise http_error(
        422, f"[{req_id}] 未能切换到模型 '{model_id_to_use}'。请确保模型可用。"
    )


async def handle_parameter_cache(req_id: str, context: RequestContext) -> None:
    set_request_id(req_id)
    params_cache_lock = context["params_cache_lock"]
    page_params_cache = context["page_params_cache"]
    current_ai_studio_model_id = context["current_ai_studio_model_id"]
    model_actually_switched = context["model_actually_switched"]

    async with params_cache_lock:
        cached_model_for_params = page_params_cache.get(
            "last_known_model_id_for_params"
        )
        if model_actually_switched or (
            current_ai_studio_model_id != cached_model_for_params
        ):
            page_params_cache.clear()
            page_params_cache["last_known_model_id_for_params"] = (
                current_ai_studio_model_id
            )
