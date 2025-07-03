"""
全局状态管理器
统一管理应用的全局状态，确保并发安全
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Set, List
from contextlib import asynccontextmanager
from playwright.async_api import Browser as AsyncBrowser, Page as AsyncPage, Playwright as AsyncPlaywright
from asyncio import Queue, Lock, Event, Task

logger = logging.getLogger("AIStudioProxyServer")


class GlobalStateManager:
    """全局状态管理器，确保状态更新的原子性和一致性"""

    def __init__(self):
        # 主要状态锁
        self._state_lock = asyncio.Lock()
        
        # Playwright相关状态
        self._playwright_manager: Optional[AsyncPlaywright] = None
        self._browser_instance: Optional[AsyncBrowser] = None
        self._page_instance: Optional[AsyncPage] = None
        
        # 状态标志
        self._is_playwright_ready = False
        self._is_browser_connected = False
        self._is_page_ready = False
        self._is_initializing = False
        
        # 模型相关状态
        self._current_ai_studio_model_id: Optional[str] = None
        self._global_model_list_raw_json: Optional[List[Any]] = None
        self._parsed_model_list: List[Dict[str, Any]] = []
        self._excluded_model_ids: Set[str] = set()
        self._model_list_fetch_event = asyncio.Event()
        
        # 队列和锁
        self._request_queue: Optional[Queue] = None
        self._processing_lock: Optional[Lock] = None
        self._model_switching_lock: Optional[Lock] = None
        self._params_cache_lock: Optional[Lock] = None
        self._worker_task: Optional[Task] = None
        
        # 缓存
        self._page_params_cache: Dict[str, Any] = {}
        
        # 代理配置
        self._playwright_proxy_settings: Optional[Dict[str, str]] = None
        
        # WebSocket管理器
        self._log_ws_manager = None
        
        # 流相关
        self._stream_queue = None
        self._stream_process = None

    # Playwright相关属性
    @property
    async def playwright_manager(self) -> Optional[AsyncPlaywright]:
        async with self._state_lock:
            return self._playwright_manager

    async def set_playwright_manager(self, manager: Optional[AsyncPlaywright]) -> None:
        async with self._state_lock:
            self._playwright_manager = manager
            self._is_playwright_ready = manager is not None
            logger.info(f"Playwright管理器状态更新: ready={self._is_playwright_ready}")

    @property
    async def browser_instance(self) -> Optional[AsyncBrowser]:
        async with self._state_lock:
            return self._browser_instance

    async def set_browser_instance(self, browser: Optional[AsyncBrowser]) -> None:
        async with self._state_lock:
            self._browser_instance = browser
            if browser:
                try:
                    # 安全地检查浏览器连接状态
                    is_connected = browser.is_connected()
                    if asyncio.iscoroutine(is_connected):
                        is_connected = await is_connected
                    self._is_browser_connected = is_connected
                except Exception:
                    self._is_browser_connected = False
            else:
                self._is_browser_connected = False
            logger.info(f"浏览器实例状态更新: connected={self._is_browser_connected}")

    @property
    async def page_instance(self) -> Optional[AsyncPage]:
        async with self._state_lock:
            return self._page_instance

    async def set_page_instance(self, page: Optional[AsyncPage], is_ready: bool = None) -> None:
        async with self._state_lock:
            self._page_instance = page
            if is_ready is not None:
                self._is_page_ready = is_ready
            else:
                self._is_page_ready = page is not None
            logger.info(f"页面实例状态更新: ready={self._is_page_ready}")

    # 状态标志属性
    async def get_status_flags(self) -> Dict[str, bool]:
        """获取所有状态标志"""
        async with self._state_lock:
            return {
                "is_playwright_ready": self._is_playwright_ready,
                "is_browser_connected": self._is_browser_connected,
                "is_page_ready": self._is_page_ready,
                "is_initializing": self._is_initializing,
            }

    async def set_initializing(self, initializing: bool) -> None:
        async with self._state_lock:
            self._is_initializing = initializing
            logger.info(f"初始化状态更新: initializing={initializing}")

    async def is_ready(self) -> bool:
        """检查系统是否完全就绪"""
        async with self._state_lock:
            return (self._is_playwright_ready and 
                   self._is_browser_connected and 
                   self._is_page_ready and 
                   not self._is_initializing)

    # 模型相关方法
    async def get_current_model_id(self) -> Optional[str]:
        async with self._state_lock:
            return self._current_ai_studio_model_id

    async def set_current_model_id(self, model_id: Optional[str]) -> None:
        async with self._state_lock:
            self._current_ai_studio_model_id = model_id
            logger.info(f"当前模型ID更新: {model_id}")

    async def get_model_list(self) -> List[Dict[str, Any]]:
        async with self._state_lock:
            return self._parsed_model_list.copy()

    async def set_model_list(self, model_list: List[Dict[str, Any]], raw_json: Optional[List[Any]] = None) -> None:
        async with self._state_lock:
            self._parsed_model_list = model_list.copy()
            if raw_json is not None:
                self._global_model_list_raw_json = raw_json
            if not self._model_list_fetch_event.is_set():
                self._model_list_fetch_event.set()
            logger.info(f"模型列表更新: {len(model_list)} 个模型")

    async def get_excluded_model_ids(self) -> Set[str]:
        async with self._state_lock:
            return self._excluded_model_ids.copy()

    async def set_excluded_model_ids(self, excluded_ids: Set[str]) -> None:
        async with self._state_lock:
            self._excluded_model_ids = excluded_ids.copy()
            logger.info(f"排除模型ID更新: {len(excluded_ids)} 个模型")

    # 锁和队列管理
    async def initialize_locks_and_queues(self) -> None:
        """初始化锁和队列"""
        async with self._state_lock:
            if self._request_queue is None:
                self._request_queue = Queue()
            if self._processing_lock is None:
                self._processing_lock = Lock()
            if self._model_switching_lock is None:
                self._model_switching_lock = Lock()
            if self._params_cache_lock is None:
                self._params_cache_lock = Lock()
            logger.info("锁和队列已初始化")

    async def get_request_queue(self) -> Optional[Queue]:
        async with self._state_lock:
            return self._request_queue

    async def get_processing_lock(self) -> Optional[Lock]:
        async with self._state_lock:
            return self._processing_lock

    async def get_model_switching_lock(self) -> Optional[Lock]:
        async with self._state_lock:
            return self._model_switching_lock

    async def get_params_cache_lock(self) -> Optional[Lock]:
        async with self._state_lock:
            return self._params_cache_lock

    # 缓存管理
    @asynccontextmanager
    async def cache_operation(self):
        """缓存操作的上下文管理器"""
        cache_lock = await self.get_params_cache_lock()
        if cache_lock:
            async with cache_lock:
                yield self._page_params_cache
        else:
            yield self._page_params_cache

    async def get_cache_value(self, key: str, default=None):
        """安全地获取缓存值"""
        async with self.cache_operation() as cache:
            return cache.get(key, default)

    async def set_cache_value(self, key: str, value: Any) -> None:
        """安全地设置缓存值"""
        async with self.cache_operation() as cache:
            cache[key] = value

    async def clear_cache(self) -> None:
        """清空缓存"""
        async with self.cache_operation() as cache:
            cache.clear()
            logger.info("页面参数缓存已清空")

    # 工作任务管理
    async def set_worker_task(self, task: Optional[Task]) -> None:
        async with self._state_lock:
            self._worker_task = task

    async def get_worker_task(self) -> Optional[Task]:
        async with self._state_lock:
            return self._worker_task

    # 代理配置
    async def set_proxy_settings(self, settings: Optional[Dict[str, str]]) -> None:
        async with self._state_lock:
            self._playwright_proxy_settings = settings

    async def get_proxy_settings(self) -> Optional[Dict[str, str]]:
        async with self._state_lock:
            return self._playwright_proxy_settings

    # WebSocket管理器
    async def set_log_ws_manager(self, manager) -> None:
        async with self._state_lock:
            self._log_ws_manager = manager

    async def get_log_ws_manager(self):
        async with self._state_lock:
            return self._log_ws_manager

    # 流相关
    async def set_stream_queue(self, queue) -> None:
        async with self._state_lock:
            self._stream_queue = queue

    async def get_stream_queue(self):
        async with self._state_lock:
            return self._stream_queue

    async def set_stream_process(self, process) -> None:
        async with self._state_lock:
            self._stream_process = process

    async def get_stream_process(self):
        async with self._state_lock:
            return self._stream_process

    # 事件管理
    async def get_model_list_fetch_event(self) -> Event:
        async with self._state_lock:
            return self._model_list_fetch_event

    # 状态重置
    async def reset_all_state(self) -> None:
        """重置所有状态"""
        async with self._state_lock:
            # 重置Playwright相关
            self._playwright_manager = None
            self._browser_instance = None
            self._page_instance = None
            
            # 重置状态标志
            self._is_playwright_ready = False
            self._is_browser_connected = False
            self._is_page_ready = False
            self._is_initializing = False
            
            # 重置模型相关
            self._current_ai_studio_model_id = None
            self._global_model_list_raw_json = None
            self._parsed_model_list = []
            self._excluded_model_ids = set()
            
            # 清空缓存
            self._page_params_cache = {}
            
            # 重置其他状态
            self._log_ws_manager = None
            self._stream_queue = None
            self._stream_process = None
            self._worker_task = None
            
            logger.info("所有全局状态已重置")


# 全局状态管理器实例
_state_manager: Optional[GlobalStateManager] = None


def get_state_manager() -> GlobalStateManager:
    """获取全局状态管理器实例"""
    global _state_manager
    if _state_manager is None:
        _state_manager = GlobalStateManager()
    return _state_manager


async def reset_global_state() -> None:
    """重置全局状态"""
    global _state_manager
    if _state_manager:
        await _state_manager.reset_all_state()
        _state_manager = None
