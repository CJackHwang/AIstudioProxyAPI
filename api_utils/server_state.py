"""
Centralized server state module.

This module contains all shared state variables that were previously in server.py.
It has NO imports from project modules (only stdlib), making it safe to import
at module level anywhere in the codebase without circular dependency issues.

Usage:
    from api_utils.server_state import state
    # Access state attributes
    page = state.page_instance
    state.current_ai_studio_model_id = "new-model"
"""

import asyncio
import logging
import multiprocessing
from asyncio import Event, Lock, Queue, Task
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from playwright.async_api import (
        Browser as AsyncBrowser,
    )
    from playwright.async_api import (
        Page as AsyncPage,
    )
    from playwright.async_api import (
        Playwright as AsyncPlaywright,
    )

    from api_utils.context_types import QueueItem
    from api_utils.session_manager import SessionManager
    from models.logging import WebSocketConnectionManager


class ServerState:
    """
    Centralized container for all server state.

    This class holds all mutable state that needs to be shared across modules.
    Using a class allows for better organization and easier testing (state can be reset).
    """

    def __init__(self) -> None:
        """Initialize all state variables with default values."""
        self.reset()

    def reset(self) -> None:
        """Reset all state to initial values. Useful for testing."""
        # --- Stream Queue ---
        self.STREAM_QUEUE: Optional[multiprocessing.Queue] = None
        self.STREAM_PROCESS: Optional[multiprocessing.Process] = None

        # --- Playwright/Browser State ---
        self.playwright_manager: Optional["AsyncPlaywright"] = None
        self.browser_instance: Optional["AsyncBrowser"] = None
        self.page_instance: Optional["AsyncPage"] = None  # Deprecated: Use session_manager
        self.session_manager: Optional["SessionManager"] = None
        self.is_playwright_ready: bool = False
        self.is_browser_connected: bool = False
        self.is_page_ready: bool = False
        self.is_initializing: bool = False

        # --- Proxy Configuration ---
        self.PLAYWRIGHT_PROXY_SETTINGS: Optional[Dict[str, str]] = None

        # --- Model State ---
        self.global_model_list_raw_json: Optional[str] = None
        self.parsed_model_list: List[Dict[str, Any]] = []
        self.model_list_fetch_event: Event = asyncio.Event()
        self.current_ai_studio_model_id: Optional[str] = None
        self.model_switching_lock: Optional[Lock] = None
        self.excluded_model_ids: Set[str] = set()

        # --- Request Processing State ---
        self.request_queue: "Optional[Queue[QueueItem]]" = None
        self.processing_lock: Optional[Lock] = None
        self.worker_task: "Optional[Task[None]]" = None

        # --- Parameter Cache ---
        self.page_params_cache: Dict[str, Any] = {}
        self.params_cache_lock: Optional[Lock] = None

        # --- Debug Logging State ---
        self.console_logs: List[Dict[str, Any]] = []
        self.network_log: Dict[str, List[Dict[str, Any]]] = {
            "requests": [],
            "responses": [],
        }

        # --- Logging ---
        self.logger: logging.Logger = logging.getLogger("AIStudioProxyServer")
        self.log_ws_manager: Optional["WebSocketConnectionManager"] = None

        # --- Control Flags ---
        self.should_exit: bool = False

    def clear_debug_logs(self) -> None:
        """Clear console and network logs (called after each request)."""
        self.console_logs = []
        self.network_log = {"requests": [], "responses": []}

    def get_server_status(self) -> Dict[str, Any]:
        """Get current server status as a dictionary."""
        return {
            "is_initializing": self.is_initializing,
            "is_playwright_ready": self.is_playwright_ready,
            "is_browser_connected": self.is_browser_connected,
            "is_page_ready": self.is_page_ready,
            "current_model": self.current_ai_studio_model_id,
            "queue_size": self.request_queue.qsize() if self.request_queue else 0,
            "worker_running": bool(self.worker_task and not self.worker_task.done()),
        }


# Global singleton instance
state = ServerState()


# Convenience exports for backward compatibility
# These allow direct attribute access like: from server_state import page_instance
# But the recommended way is: from api_utils.server_state import state; state.page_instance


def __getattr__(name: str) -> Any:
    """
    Module-level attribute access for backward compatibility.

    Allows:
        from server_state import page_instance
    Instead of:
        from api_utils.server_state import state
        page_instance = state.page_instance
    """
    if hasattr(state, name):
        return getattr(state, name)
    raise AttributeError(f"module 'server_state' has no attribute '{name}'")
