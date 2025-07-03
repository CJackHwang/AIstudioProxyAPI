"""
状态迁移工具
将现有的全局变量迁移到状态管理器，确保向后兼容性
"""

import asyncio
import logging
from typing import Any, Optional
from .state_manager import get_state_manager

logger = logging.getLogger("AIStudioProxyServer")


class StateProxy:
    """状态代理类，提供与原全局变量兼容的接口"""
    
    def __init__(self):
        self._state_manager = get_state_manager()
        self._cache = {}
        self._cache_lock = asyncio.Lock()

    async def _get_cached_or_fetch(self, key: str, fetch_func):
        """获取缓存值或从状态管理器获取"""
        async with self._cache_lock:
            if key in self._cache:
                return self._cache[key]
            
            value = await fetch_func()
            self._cache[key] = value
            return value

    async def _invalidate_cache(self, key: str):
        """使缓存失效"""
        async with self._cache_lock:
            self._cache.pop(key, None)

    # Playwright相关属性代理
    @property
    def playwright_manager(self):
        """获取Playwright管理器"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.playwright_manager)
            return task
        except RuntimeError:
            return None

    @playwright_manager.setter
    def playwright_manager(self, value):
        """设置Playwright管理器"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_playwright_manager(value))
        except RuntimeError:
            pass

    @property
    def browser_instance(self):
        """获取浏览器实例"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.browser_instance)
            return task
        except RuntimeError:
            return None

    @browser_instance.setter
    def browser_instance(self, value):
        """设置浏览器实例"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_browser_instance(value))
        except RuntimeError:
            pass

    @property
    def page_instance(self):
        """获取页面实例"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.page_instance)
            return task
        except RuntimeError:
            return None

    @page_instance.setter
    def page_instance(self, value):
        """设置页面实例"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_page_instance(value))
        except RuntimeError:
            pass

    # 状态标志代理
    @property
    def is_playwright_ready(self):
        """获取Playwright就绪状态"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_status_flag('is_playwright_ready'))
            return task
        except RuntimeError:
            return False

    @is_playwright_ready.setter
    def is_playwright_ready(self, value):
        """设置Playwright就绪状态"""
        try:
            loop = asyncio.get_running_loop()
            if value:
                loop.create_task(self._state_manager.set_playwright_manager(self._get_current_playwright_manager()))
            else:
                loop.create_task(self._state_manager.set_playwright_manager(None))
        except RuntimeError:
            pass

    @property
    def is_browser_connected(self):
        """获取浏览器连接状态"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_status_flag('is_browser_connected'))
            return task
        except RuntimeError:
            return False

    @is_browser_connected.setter
    def is_browser_connected(self, value):
        """设置浏览器连接状态"""
        # 这个状态由set_browser_instance自动管理，不需要单独设置
        pass

    @property
    def is_page_ready(self):
        """获取页面就绪状态"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_status_flag('is_page_ready'))
            return task
        except RuntimeError:
            return False

    @is_page_ready.setter
    def is_page_ready(self, value):
        """设置页面就绪状态"""
        try:
            loop = asyncio.get_running_loop()
            current_page = self._get_current_page_instance()
            loop.create_task(self._state_manager.set_page_instance(current_page, value))
        except RuntimeError:
            pass

    @property
    def is_initializing(self):
        """获取初始化状态"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_status_flag('is_initializing'))
            return task
        except RuntimeError:
            return False

    @is_initializing.setter
    def is_initializing(self, value):
        """设置初始化状态"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_initializing(value))
        except RuntimeError:
            pass

    async def _get_status_flag(self, flag_name: str):
        """获取状态标志"""
        flags = await self._state_manager.get_status_flags()
        return flags.get(flag_name, False)

    def _get_current_playwright_manager(self):
        """获取当前的Playwright管理器（同步方式）"""
        # 这里需要从实际的全局变量获取，因为我们正在迁移过程中
        import server
        return getattr(server, 'playwright_manager', None)

    def _get_current_page_instance(self):
        """获取当前的页面实例（同步方式）"""
        import server
        return getattr(server, 'page_instance', None)

    # 模型相关代理
    @property
    def current_ai_studio_model_id(self):
        """获取当前模型ID"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_current_model_id())
            return task
        except RuntimeError:
            return None

    @current_ai_studio_model_id.setter
    def current_ai_studio_model_id(self, value):
        """设置当前模型ID"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_current_model_id(value))
        except RuntimeError:
            pass

    @property
    def parsed_model_list(self):
        """获取解析的模型列表"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_model_list())
            return task
        except RuntimeError:
            return []

    @parsed_model_list.setter
    def parsed_model_list(self, value):
        """设置解析的模型列表"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_model_list(value))
        except RuntimeError:
            pass

    @property
    def excluded_model_ids(self):
        """获取排除的模型ID"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_excluded_model_ids())
            return task
        except RuntimeError:
            return set()

    @excluded_model_ids.setter
    def excluded_model_ids(self, value):
        """设置排除的模型ID"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_excluded_model_ids(value))
        except RuntimeError:
            pass

    # 锁和队列代理
    @property
    def request_queue(self):
        """获取请求队列"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_request_queue())
            return task
        except RuntimeError:
            return None

    @property
    def processing_lock(self):
        """获取处理锁"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_processing_lock())
            return task
        except RuntimeError:
            return None

    @property
    def model_switching_lock(self):
        """获取模型切换锁"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_model_switching_lock())
            return task
        except RuntimeError:
            return None

    @property
    def params_cache_lock(self):
        """获取参数缓存锁"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_params_cache_lock())
            return task
        except RuntimeError:
            return None

    # 缓存代理
    @property
    def page_params_cache(self):
        """获取页面参数缓存"""
        # 返回一个代理字典，支持异步操作
        return CacheProxy(self._state_manager)


class CacheProxy:
    """缓存代理类，提供字典接口"""
    
    def __init__(self, state_manager):
        self._state_manager = state_manager

    def get(self, key, default=None):
        """获取缓存值"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._state_manager.get_cache_value(key, default))
            return task
        except RuntimeError:
            return default

    def __getitem__(self, key):
        """获取缓存值"""
        return self.get(key)

    def __setitem__(self, key, value):
        """设置缓存值"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.set_cache_value(key, value))
        except RuntimeError:
            pass

    def clear(self):
        """清空缓存"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._state_manager.clear_cache())
        except RuntimeError:
            pass


# 全局状态代理实例
_state_proxy: Optional[StateProxy] = None


def get_state_proxy() -> StateProxy:
    """获取状态代理实例"""
    global _state_proxy
    if _state_proxy is None:
        _state_proxy = StateProxy()
    return _state_proxy


async def migrate_existing_state():
    """迁移现有的全局状态到状态管理器"""
    try:
        import server
        state_manager = get_state_manager()
        
        # 初始化锁和队列
        await state_manager.initialize_locks_and_queues()
        
        # 迁移现有状态
        if hasattr(server, 'playwright_manager'):
            await state_manager.set_playwright_manager(server.playwright_manager)
        
        if hasattr(server, 'browser_instance'):
            await state_manager.set_browser_instance(server.browser_instance)
        
        if hasattr(server, 'page_instance'):
            await state_manager.set_page_instance(
                server.page_instance, 
                getattr(server, 'is_page_ready', False)
            )
        
        if hasattr(server, 'is_initializing'):
            await state_manager.set_initializing(server.is_initializing)
        
        if hasattr(server, 'current_ai_studio_model_id'):
            await state_manager.set_current_model_id(server.current_ai_studio_model_id)
        
        if hasattr(server, 'parsed_model_list'):
            await state_manager.set_model_list(server.parsed_model_list)
        
        if hasattr(server, 'excluded_model_ids'):
            await state_manager.set_excluded_model_ids(server.excluded_model_ids)
        
        logger.info("现有状态已迁移到状态管理器")
        
    except Exception as e:
        logger.error(f"状态迁移失败: {e}", exc_info=True)
