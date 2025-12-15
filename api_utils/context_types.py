import logging
from asyncio import Future, Lock
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict, Union

from playwright.async_api import Page as AsyncPage

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse, StreamingResponse

    from models.chat import ChatCompletionRequest


class QueueItem(TypedDict):
    """Type definition for items in the request queue.

    This defines the structure of each item put into the request_queue,
    ensuring type safety for queue operations.
    """

    req_id: str
    request_data: "ChatCompletionRequest"
    http_request: "Request"
    result_future: "Future[Union[JSONResponse, StreamingResponse]]"
    enqueue_time: float
    cancelled: bool


class RequestContext(TypedDict):
    """Request context with all keys always present after initialization.

    All keys are required (always exist in the dict) after context_init.py initialization.
    Optional[] types indicate that the VALUE can be None, not that the key might not exist.
    """

    # Core components (always set by context_init.py)
    req_id: str
    logger: logging.Logger
    session: Any  # Session object
    page: Optional[AsyncPage]  # Value can be None if browser not ready
    is_page_ready: bool
    parsed_model_list: List[Dict[str, Any]]
    current_ai_studio_model_id: Optional[str]  # Value can be None initially

    # Locks (always set by server_state)
    model_switching_lock: Lock
    page_params_cache: Dict[str, Any]
    params_cache_lock: Lock

    # Request-specific state (always initialized)
    is_streaming: bool
    model_actually_switched: bool
    requested_model: Optional[str]  # Value can be None if not specified
    model_id_to_use: Optional[str]  # Value set during model analysis
    needs_model_switching: bool
