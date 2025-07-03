"""
浏览器资源管理器
统一管理浏览器实例、页面和上下文的生命周期，确保资源正确释放
"""

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, Set, AsyncGenerator
from playwright.async_api import (
    Browser as AsyncBrowser,
    BrowserContext as AsyncBrowserContext,
    Page as AsyncPage,
    Error as PlaywrightAsyncError,
)

logger = logging.getLogger("AIStudioProxyServer")


class BrowserResourceManager:
    """浏览器资源管理器，确保所有资源正确释放"""

    def __init__(self):
        self._browser: Optional[AsyncBrowser] = None
        self._contexts: Set[AsyncBrowserContext] = set()
        self._pages: Set[AsyncPage] = set()
        self._cleanup_tasks: Set[asyncio.Task] = set()
        self._is_shutting_down = False
        self._lock = asyncio.Lock()

    @property
    def browser(self) -> Optional[AsyncBrowser]:
        """获取当前浏览器实例"""
        return self._browser

    @property
    def is_connected(self) -> bool:
        """检查浏览器是否连接"""
        if self._browser is None:
            return False
        try:
            # 处理可能的异步调用
            result = self._browser.is_connected()
            if asyncio.iscoroutine(result):
                # 如果是协程，我们无法在同步属性中等待，返回False
                return False
            return result
        except Exception:
            return False

    async def set_browser(self, browser: AsyncBrowser) -> None:
        """设置浏览器实例"""
        async with self._lock:
            if self._browser and self._browser.is_connected():
                logger.warning("设置新浏览器实例时，旧实例仍然连接，将先关闭旧实例")
                await self._close_browser_internal()
            
            self._browser = browser
            logger.info("✅ 浏览器实例已设置")

    @asynccontextmanager
    async def create_context(self, **options) -> AsyncGenerator[AsyncBrowserContext, None]:
        """创建浏览器上下文的上下文管理器"""
        if not self._browser:
            raise RuntimeError("浏览器未连接，无法创建上下文")

        # 安全地检查浏览器连接状态
        try:
            is_connected = self._browser.is_connected()
            if asyncio.iscoroutine(is_connected):
                is_connected = await is_connected
            if not is_connected:
                raise RuntimeError("浏览器未连接，无法创建上下文")
        except Exception as e:
            raise RuntimeError(f"检查浏览器连接状态失败: {e}")

        context = None
        try:
            context = await self._browser.new_context(**options)
            async with self._lock:
                self._contexts.add(context)
            logger.info("✅ 浏览器上下文已创建")
            yield context
        except Exception as e:
            logger.error(f"创建浏览器上下文时发生错误: {e}")
            raise
        finally:
            if context:
                await self._close_context_safe(context)

    @asynccontextmanager
    async def create_page(
        self, context: Optional[AsyncBrowserContext] = None, **context_options
    ) -> AsyncGenerator[AsyncPage, None]:
        """创建页面的上下文管理器"""
        page = None
        created_context = None

        try:
            if context is None:
                # 如果没有提供上下文，创建一个新的但不使用上下文管理器
                if not self._browser:
                    raise RuntimeError("浏览器未连接，无法创建页面")

                # 安全地检查浏览器连接状态
                try:
                    is_connected = self._browser.is_connected()
                    if asyncio.iscoroutine(is_connected):
                        is_connected = await is_connected
                    if not is_connected:
                        raise RuntimeError("浏览器未连接，无法创建页面")
                except Exception as e:
                    raise RuntimeError(f"检查浏览器连接状态失败: {e}")

                created_context = await self._browser.new_context(**context_options)
                async with self._lock:
                    self._contexts.add(created_context)
                context = created_context
                logger.info("✅ 浏览器上下文已创建")

            page = await context.new_page()
            async with self._lock:
                self._pages.add(page)
            logger.info("✅ 页面已创建")
            yield page

        except Exception as e:
            logger.error(f"创建页面时发生错误: {e}")
            raise
        finally:
            if page:
                await self._close_page_safe(page)
            if created_context:
                await self._close_context_safe(created_context)

    async def _close_page_safe(self, page: AsyncPage) -> None:
        """安全关闭页面"""
        try:
            async with self._lock:
                self._pages.discard(page)

            # 安全地检查页面是否已关闭
            try:
                is_closed = page.is_closed()
                if asyncio.iscoroutine(is_closed):
                    is_closed = await is_closed
                if not is_closed:
                    await page.close()
                    logger.info("✅ 页面已关闭")
            except Exception as check_error:
                # 如果检查状态失败，直接尝试关闭
                try:
                    await page.close()
                    logger.info("✅ 页面已关闭（强制关闭）")
                except Exception:
                    pass  # 忽略关闭失败
        except PlaywrightAsyncError as e:
            logger.warning(f"关闭页面时出现Playwright错误: {e}")
        except Exception as e:
            logger.error(f"关闭页面时出现意外错误: {e}")

    async def _close_context_safe(self, context: AsyncBrowserContext) -> None:
        """安全关闭浏览器上下文"""
        try:
            async with self._lock:
                self._contexts.discard(context)
            
            # 先关闭上下文中的所有页面
            for page in context.pages:
                await self._close_page_safe(page)
            
            await context.close()
            logger.info("✅ 浏览器上下文已关闭")
        except PlaywrightAsyncError as e:
            logger.warning(f"关闭浏览器上下文时出现Playwright错误: {e}")
        except Exception as e:
            logger.error(f"关闭浏览器上下文时出现意外错误: {e}")

    async def _close_browser_internal(self) -> None:
        """内部浏览器关闭方法"""
        if not self._browser:
            return

        try:
            # 关闭所有页面
            pages_to_close = list(self._pages)
            for page in pages_to_close:
                await self._close_page_safe(page)

            # 关闭所有上下文
            contexts_to_close = list(self._contexts)
            for context in contexts_to_close:
                await self._close_context_safe(context)

            # 关闭浏览器
            try:
                is_connected = self._browser.is_connected()
                if asyncio.iscoroutine(is_connected):
                    is_connected = await is_connected
                if is_connected:
                    await self._browser.close()
                    logger.info("✅ 浏览器已关闭")
            except Exception as browser_close_error:
                logger.warning(f"关闭浏览器时出错: {browser_close_error}")

        except Exception as e:
            logger.error(f"关闭浏览器时发生错误: {e}")
        finally:
            self._browser = None
            self._contexts.clear()
            self._pages.clear()

    async def close_all(self) -> None:
        """关闭所有资源"""
        async with self._lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True

        try:
            logger.info("开始关闭所有浏览器资源...")
            
            # 取消所有清理任务
            for task in self._cleanup_tasks:
                if not task.done():
                    task.cancel()
            
            # 等待所有任务完成或取消
            if self._cleanup_tasks:
                await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
            
            await self._close_browser_internal()
            logger.info("✅ 所有浏览器资源已关闭")
            
        except Exception as e:
            logger.error(f"关闭所有资源时发生错误: {e}")
        finally:
            self._is_shutting_down = False

    def schedule_cleanup(self, coro) -> None:
        """调度清理任务"""
        if not self._is_shutting_down:
            task = asyncio.create_task(coro)
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()


# 全局资源管理器实例
_resource_manager: Optional[BrowserResourceManager] = None


def get_resource_manager() -> BrowserResourceManager:
    """获取全局资源管理器实例"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = BrowserResourceManager()
    return _resource_manager


async def cleanup_global_resources() -> None:
    """清理全局资源"""
    global _resource_manager
    if _resource_manager:
        await _resource_manager.close_all()
        _resource_manager = None
