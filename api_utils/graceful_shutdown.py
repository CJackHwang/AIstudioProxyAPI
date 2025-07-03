"""
优雅关闭管理器
确保应用在关闭时正确清理所有资源
"""

import asyncio
import logging
import signal
import sys
from typing import List, Callable, Awaitable, Optional
from contextlib import asynccontextmanager

logger = logging.getLogger("AIStudioProxyServer")


class GracefulShutdownManager:
    """优雅关闭管理器"""

    def __init__(self):
        self._shutdown_handlers: List[Callable[[], Awaitable[None]]] = []
        self._is_shutting_down = False
        self._shutdown_event = asyncio.Event()
        self._signal_handlers_installed = False

    def add_shutdown_handler(self, handler: Callable[[], Awaitable[None]]) -> None:
        """添加关闭处理器"""
        if self._is_shutting_down:
            logger.warning("应用正在关闭，无法添加新的关闭处理器")
            return
        
        self._shutdown_handlers.append(handler)
        logger.debug(f"添加关闭处理器: {handler.__name__}")

    def install_signal_handlers(self) -> None:
        """安装信号处理器"""
        if self._signal_handlers_installed:
            return

        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}，开始优雅关闭...")
            asyncio.create_task(self.shutdown())

        # 安装信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Windows 不支持 SIGHUP
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, signal_handler)
        
        self._signal_handlers_installed = True
        logger.info("信号处理器已安装")

    async def shutdown(self) -> None:
        """执行优雅关闭"""
        if self._is_shutting_down:
            logger.info("关闭已在进行中...")
            await self._shutdown_event.wait()
            return

        self._is_shutting_down = True
        logger.info("开始优雅关闭...")

        try:
            # 按相反顺序执行关闭处理器
            for i, handler in enumerate(reversed(self._shutdown_handlers)):
                try:
                    logger.info(f"执行关闭处理器 {len(self._shutdown_handlers) - i}: {handler.__name__}")
                    await handler()
                except Exception as e:
                    logger.error(f"关闭处理器 {handler.__name__} 执行失败: {e}", exc_info=True)

            logger.info("优雅关闭完成")
        except Exception as e:
            logger.error(f"优雅关闭过程中发生错误: {e}", exc_info=True)
        finally:
            self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """等待关闭完成"""
        await self._shutdown_event.wait()

    @property
    def is_shutting_down(self) -> bool:
        """检查是否正在关闭"""
        return self._is_shutting_down

    @asynccontextmanager
    async def managed_shutdown(self):
        """上下文管理器，自动处理关闭"""
        try:
            yield self
        finally:
            if not self._is_shutting_down:
                await self.shutdown()


# 全局优雅关闭管理器实例
_shutdown_manager: Optional[GracefulShutdownManager] = None


def get_shutdown_manager() -> GracefulShutdownManager:
    """获取全局优雅关闭管理器实例"""
    global _shutdown_manager
    if _shutdown_manager is None:
        _shutdown_manager = GracefulShutdownManager()
    return _shutdown_manager


def add_shutdown_handler(handler: Callable[[], Awaitable[None]]) -> None:
    """添加关闭处理器的便捷函数"""
    get_shutdown_manager().add_shutdown_handler(handler)


async def graceful_shutdown() -> None:
    """执行优雅关闭的便捷函数"""
    await get_shutdown_manager().shutdown()


def install_signal_handlers() -> None:
    """安装信号处理器的便捷函数"""
    get_shutdown_manager().install_signal_handlers()


# 预定义的关闭处理器
async def cleanup_browser_resources():
    """清理浏览器资源"""
    try:
        from browser_utils import cleanup_global_resources
        await cleanup_global_resources()
        logger.info("浏览器资源已清理")
    except Exception as e:
        logger.error(f"清理浏览器资源时出错: {e}")


async def cleanup_async_tasks():
    """清理异步任务"""
    try:
        from .task_manager import cleanup_global_tasks
        await cleanup_global_tasks()
        logger.info("异步任务已清理")
    except Exception as e:
        logger.error(f"清理异步任务时出错: {e}")


async def cleanup_websocket_connections():
    """清理WebSocket连接"""
    try:
        import server
        if server.log_ws_manager:
            await server.log_ws_manager.shutdown()
            logger.info("WebSocket连接已清理")
    except Exception as e:
        logger.error(f"清理WebSocket连接时出错: {e}")


async def cleanup_stream_proxy():
    """清理流代理进程"""
    try:
        import server
        if server.STREAM_PROCESS:
            server.STREAM_PROCESS.terminate()
            server.STREAM_PROCESS.join(timeout=5.0)
            if server.STREAM_PROCESS.is_alive():
                server.STREAM_PROCESS.kill()
            logger.info("流代理进程已清理")
    except Exception as e:
        logger.error(f"清理流代理进程时出错: {e}")


async def cleanup_playwright():
    """清理Playwright"""
    try:
        import server
        if server.playwright_manager:
            await server.playwright_manager.stop()
            logger.info("Playwright已清理")
    except Exception as e:
        logger.error(f"清理Playwright时出错: {e}")


def setup_default_shutdown_handlers():
    """设置默认的关闭处理器"""
    shutdown_manager = get_shutdown_manager()
    
    # 按依赖关系顺序添加处理器
    shutdown_manager.add_shutdown_handler(cleanup_async_tasks)
    shutdown_manager.add_shutdown_handler(cleanup_websocket_connections)
    shutdown_manager.add_shutdown_handler(cleanup_stream_proxy)
    shutdown_manager.add_shutdown_handler(cleanup_browser_resources)
    shutdown_manager.add_shutdown_handler(cleanup_playwright)
    
    logger.info("默认关闭处理器已设置")
