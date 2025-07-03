"""
测试异步任务管理器
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from api_utils.task_manager import AsyncTaskManager, get_task_manager


class TestAsyncTaskManager:
    """测试异步任务管理器"""

    @pytest.fixture
    async def task_manager(self):
        """创建任务管理器实例"""
        manager = AsyncTaskManager()
        yield manager
        await manager.cancel_all_tasks()

    async def test_create_task(self, task_manager):
        """测试创建任务"""
        async def dummy_task():
            await asyncio.sleep(0.1)
            return "completed"

        task = await task_manager.create_task(dummy_task(), name="test_task")
        assert task is not None
        assert task.get_name() == "test_task"
        
        result = await task
        assert result == "completed"

    async def test_create_named_task(self, task_manager):
        """测试创建命名任务"""
        async def dummy_task():
            await asyncio.sleep(0.1)

        task1 = await task_manager.create_task(dummy_task(), name="same_name")
        task2 = await task_manager.create_task(dummy_task(), name="same_name")

        # 等待一小段时间让取消操作完成
        await asyncio.sleep(0.01)

        # 第二个任务应该取消第一个任务
        assert task1.cancelled()
        assert not task2.cancelled()

    async def test_cancel_task(self, task_manager):
        """测试取消任务"""
        async def long_running_task():
            await asyncio.sleep(10)

        await task_manager.create_task(long_running_task(), name="long_task")
        
        success = await task_manager.cancel_task("long_task")
        assert success is True
        
        # 尝试取消不存在的任务
        success = await task_manager.cancel_task("nonexistent")
        assert success is False

    async def test_cancel_all_tasks(self, task_manager):
        """测试取消所有任务"""
        async def dummy_task():
            await asyncio.sleep(1)

        # 创建多个任务
        tasks = []
        for i in range(3):
            task = await task_manager.create_task(dummy_task(), name=f"task_{i}")
            tasks.append(task)

        # 取消所有任务
        await task_manager.cancel_all_tasks()
        
        # 验证所有任务都被取消
        for task in tasks:
            assert task.cancelled() or task.done()

    async def test_get_task(self, task_manager):
        """测试获取任务"""
        async def dummy_task():
            await asyncio.sleep(0.1)

        task = await task_manager.create_task(dummy_task(), name="get_test")
        retrieved_task = task_manager.get_task("get_test")
        
        assert retrieved_task is task

    async def test_get_task_count(self, task_manager):
        """测试获取任务数量"""
        assert task_manager.get_task_count() == 0
        
        async def dummy_task():
            await asyncio.sleep(0.1)

        await task_manager.create_task(dummy_task())
        await task_manager.create_task(dummy_task())
        
        assert task_manager.get_task_count() == 2

    async def test_get_task_info(self, task_manager):
        """测试获取任务信息"""
        async def dummy_task():
            await asyncio.sleep(0.1)

        await task_manager.create_task(dummy_task(), name="info_test")
        
        info = task_manager.get_task_info()
        assert "total_tasks" in info
        assert "active_tasks" in info
        assert "named_tasks" in info
        assert "is_shutting_down" in info
        assert "info_test" in info["named_tasks"]

    async def test_managed_task_context(self, task_manager):
        """测试任务上下文管理器"""
        async def dummy_task():
            await asyncio.sleep(0.1)
            return "result"

        async with task_manager.managed_task(dummy_task(), name="context_test") as task:
            result = await task
            assert result == "result"

    async def test_managed_task_context_with_exception(self, task_manager):
        """测试任务上下文管理器异常处理"""
        async def failing_task():
            await asyncio.sleep(0.1)
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            async with task_manager.managed_task(failing_task(), name="failing_test") as task:
                await task

    async def test_task_callback(self, task_manager):
        """测试任务回调"""
        callback_called = False
        callback_task = None

        def task_callback(task):
            nonlocal callback_called, callback_task
            callback_called = True
            callback_task = task

        async def dummy_task():
            return "done"

        task = await task_manager.create_task(
            dummy_task(), 
            name="callback_test",
            callback=task_callback
        )
        
        await task
        
        # 等待回调执行
        await asyncio.sleep(0.01)
        
        assert callback_called is True
        assert callback_task is task

    async def test_shutdown_prevents_new_tasks(self, task_manager):
        """测试关闭后无法创建新任务"""
        await task_manager.cancel_all_tasks()
        
        async def dummy_task():
            pass

        with pytest.raises(RuntimeError, match="任务管理器正在关闭"):
            await task_manager.create_task(dummy_task())

    async def test_global_task_manager(self):
        """测试全局任务管理器"""
        manager1 = get_task_manager()
        manager2 = get_task_manager()
        assert manager1 is manager2  # 应该是同一个实例

    async def test_concurrent_task_creation(self, task_manager):
        """测试并发任务创建"""
        async def dummy_task(task_id):
            await asyncio.sleep(0.1)
            return f"task_{task_id}_completed"

        # 并发创建多个任务
        tasks = await asyncio.gather(*[
            task_manager.create_task(dummy_task(i), name=f"concurrent_{i}")
            for i in range(5)
        ])

        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result == f"task_{i}_completed"

    async def test_task_cleanup_on_completion(self, task_manager):
        """测试任务完成后的清理"""
        async def quick_task():
            return "done"

        initial_count = task_manager.get_task_count()
        task = await task_manager.create_task(quick_task(), name="cleanup_test")
        
        # 任务创建后计数应该增加
        assert task_manager.get_task_count() == initial_count + 1
        
        # 等待任务完成
        await task
        
        # 等待清理完成
        await asyncio.sleep(0.01)
        
        # 任务完成后计数应该恢复
        assert task_manager.get_task_count() == initial_count
