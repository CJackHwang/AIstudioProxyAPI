"""
异步任务管理器
统一管理应用中的异步任务，确保任务正确取消和清理
"""

import asyncio
import logging
import weakref
from typing import Set, Optional, Dict, Any, Callable, Awaitable
from contextlib import asynccontextmanager

logger = logging.getLogger("AIStudioProxyServer")


class AsyncTaskManager:
    """异步任务管理器，确保所有任务正确取消和清理"""

    def __init__(self):
        self._tasks: Set[asyncio.Task] = set()
        self._named_tasks: Dict[str, asyncio.Task] = {}
        self._is_shutting_down = False
        self._lock = asyncio.Lock()

    async def create_task(
        self, 
        coro: Awaitable[Any], 
        name: Optional[str] = None,
        callback: Optional[Callable[[asyncio.Task], None]] = None
    ) -> asyncio.Task:
        """创建并跟踪异步任务"""
        if self._is_shutting_down:
            raise RuntimeError("任务管理器正在关闭，无法创建新任务")

        task = asyncio.create_task(coro, name=name)
        
        async with self._lock:
            self._tasks.add(task)
            if name:
                # 如果已存在同名任务，先取消旧任务
                if name in self._named_tasks:
                    old_task = self._named_tasks[name]
                    if not old_task.done():
                        old_task.cancel()
                        logger.info(f"取消旧的同名任务: {name}")
                self._named_tasks[name] = task

        # 添加完成回调
        def task_done_callback(completed_task: asyncio.Task):
            # 从跟踪集合中移除
            self._tasks.discard(completed_task)
            if name and self._named_tasks.get(name) == completed_task:
                self._named_tasks.pop(name, None)
            
            # 执行用户回调
            if callback:
                try:
                    callback(completed_task)
                except Exception as e:
                    logger.error(f"任务回调执行失败: {e}")

        task.add_done_callback(task_done_callback)
        
        if name:
            logger.debug(f"创建命名任务: {name}")
        else:
            logger.debug(f"创建任务: {task}")
        
        return task

    async def cancel_task(self, name: str, timeout: float = 5.0) -> bool:
        """取消指定名称的任务"""
        async with self._lock:
            task = self._named_tasks.get(name)
            if not task or task.done():
                return False

        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.error(f"取消任务 {name} 时发生异常: {e}")

        logger.info(f"任务已取消: {name}")
        return True

    async def cancel_all_tasks(self, timeout: float = 10.0) -> None:
        """取消所有任务"""
        self._is_shutting_down = True
        
        async with self._lock:
            tasks_to_cancel = [task for task in self._tasks if not task.done()]
        
        if not tasks_to_cancel:
            logger.info("没有需要取消的任务")
            return

        logger.info(f"开始取消 {len(tasks_to_cancel)} 个任务...")
        
        # 取消所有任务
        for task in tasks_to_cancel:
            task.cancel()

        # 等待所有任务完成或超时
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"部分任务在 {timeout} 秒内未能完成取消")

        # 清理跟踪集合
        async with self._lock:
            self._tasks.clear()
            self._named_tasks.clear()

        logger.info("所有任务已取消")

    def get_task(self, name: str) -> Optional[asyncio.Task]:
        """获取指定名称的任务"""
        return self._named_tasks.get(name)

    def get_task_count(self) -> int:
        """获取活跃任务数量"""
        return len([task for task in self._tasks if not task.done()])

    def get_task_info(self) -> Dict[str, Any]:
        """获取任务信息"""
        active_tasks = [task for task in self._tasks if not task.done()]
        return {
            "total_tasks": len(self._tasks),
            "active_tasks": len(active_tasks),
            "named_tasks": list(self._named_tasks.keys()),
            "is_shutting_down": self._is_shutting_down
        }

    @asynccontextmanager
    async def managed_task(
        self, 
        coro: Awaitable[Any], 
        name: Optional[str] = None
    ):
        """上下文管理器，自动管理任务生命周期"""
        task = await self.create_task(coro, name)
        try:
            yield task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cancel_all_tasks()


# 全局任务管理器实例
_task_manager: Optional[AsyncTaskManager] = None


def get_task_manager() -> AsyncTaskManager:
    """获取全局任务管理器实例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = AsyncTaskManager()
    return _task_manager


async def cleanup_global_tasks() -> None:
    """清理全局任务"""
    global _task_manager
    if _task_manager:
        await _task_manager.cancel_all_tasks()
        _task_manager = None


# 便捷函数
async def create_managed_task(
    coro: Awaitable[Any], 
    name: Optional[str] = None,
    callback: Optional[Callable[[asyncio.Task], None]] = None
) -> asyncio.Task:
    """创建受管理的任务"""
    return await get_task_manager().create_task(coro, name, callback)


async def cancel_managed_task(name: str, timeout: float = 5.0) -> bool:
    """取消受管理的任务"""
    return await get_task_manager().cancel_task(name, timeout)


def get_managed_task(name: str) -> Optional[asyncio.Task]:
    """获取受管理的任务"""
    return get_task_manager().get_task(name)


def get_task_info() -> Dict[str, Any]:
    """获取任务信息"""
    return get_task_manager().get_task_info()
