"""
Modular FastAPI routers for api_utils.
Each module defines focused endpoint handlers. This package aggregates them.
"""

# Re-export handlers for convenient imports
from .api_keys import add_api_key, delete_api_key, get_api_keys, test_api_key
from .auth_files import router as auth_files_router
from .chat import chat_completions
from .health import health_check
from .helper import router as helper_router
from .info import get_api_info
from .logs_ws import websocket_log_endpoint
from .model_capabilities import router as model_capabilities_router
from .models import list_models
from .ports import router as ports_router
from .proxy import router as proxy_router
from .queue import cancel_request, get_queue_status
from .server import router as server_router
from .static import read_index, serve_react_assets

__all__ = [
    "read_index",
    "serve_react_assets",
    "get_api_info",
    "health_check",
    "list_models",
    "model_capabilities_router",
    "chat_completions",
    "cancel_request",
    "get_queue_status",
    "websocket_log_endpoint",
    "get_api_keys",
    "add_api_key",
    "test_api_key",
    "delete_api_key",
    "proxy_router",
    "auth_files_router",
    "ports_router",
    "server_router",
    "helper_router",
]
