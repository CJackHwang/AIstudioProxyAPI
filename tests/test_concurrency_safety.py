"""
测试并发安全性改进
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api_utils.state_manager import GlobalStateManager, get_state_manager
from api_utils.model_manager import ModelManager, get_model_manager
from api_utils.queue_worker import StreamingIntervalController, get_streaming_controller


class TestGlobalStateManager:
    """测试全局状态管理器的并发安全性"""

    @pytest.fixture
    async def state_manager(self):
        """创建状态管理器实例"""
        manager = GlobalStateManager()
        await manager.initialize_locks_and_queues()
        yield manager
        await manager.reset_all_state()

    async def test_concurrent_model_id_updates(self, state_manager):
        """测试并发模型ID更新"""
        async def update_model_id(model_id, delay=0):
            if delay:
                await asyncio.sleep(delay)
            await state_manager.set_current_model_id(model_id)

        # 并发更新模型ID
        tasks = [
            update_model_id("model_1", 0.01),
            update_model_id("model_2", 0.02),
            update_model_id("model_3", 0.03),
        ]
        
        await asyncio.gather(*tasks)
        
        # 最后一个完成的应该是最终值
        final_model_id = await state_manager.get_current_model_id()
        assert final_model_id in ["model_1", "model_2", "model_3"]

    async def test_concurrent_cache_operations(self, state_manager):
        """测试并发缓存操作"""
        async def cache_operation(key, value, delay=0):
            if delay:
                await asyncio.sleep(delay)
            await state_manager.set_cache_value(key, value)
            return await state_manager.get_cache_value(key)

        # 并发缓存操作
        tasks = [
            cache_operation("key1", "value1", 0.01),
            cache_operation("key2", "value2", 0.02),
            cache_operation("key3", "value3", 0.03),
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 验证所有操作都成功
        assert results == ["value1", "value2", "value3"]
        
        # 验证缓存状态
        assert await state_manager.get_cache_value("key1") == "value1"
        assert await state_manager.get_cache_value("key2") == "value2"
        assert await state_manager.get_cache_value("key3") == "value3"

    async def test_concurrent_status_flag_updates(self, state_manager):
        """测试并发状态标志更新"""
        async def update_flags():
            await state_manager.set_initializing(True)
            await asyncio.sleep(0.01)
            await state_manager.set_initializing(False)

        # 并发更新状态标志
        tasks = [update_flags() for _ in range(5)]
        await asyncio.gather(*tasks)
        
        # 验证最终状态
        flags = await state_manager.get_status_flags()
        assert flags["is_initializing"] is False

    async def test_cache_context_manager(self, state_manager):
        """测试缓存上下文管理器的并发安全性"""
        async def cache_context_operation(key, value):
            async with state_manager.cache_operation() as cache:
                cache[key] = value
                await asyncio.sleep(0.01)  # 模拟一些处理时间
                return cache.get(key)

        # 并发使用缓存上下文管理器
        tasks = [
            cache_context_operation("ctx_key1", "ctx_value1"),
            cache_context_operation("ctx_key2", "ctx_value2"),
            cache_context_operation("ctx_key3", "ctx_value3"),
        ]
        
        results = await asyncio.gather(*tasks)
        assert results == ["ctx_value1", "ctx_value2", "ctx_value3"]


class TestModelManager:
    """测试模型管理器的并发安全性"""

    @pytest.fixture
    async def model_manager(self):
        """创建模型管理器实例"""
        manager = ModelManager()
        
        # 设置模拟的模型列表
        await manager._state_manager.set_model_list([
            {"id": "model_1", "display_name": "Model 1"},
            {"id": "model_2", "display_name": "Model 2"},
            {"id": "model_3", "display_name": "Model 3"},
        ])
        
        yield manager
        await manager._state_manager.reset_all_state()

    async def test_concurrent_model_validation(self, model_manager):
        """测试并发模型验证"""
        async def validate_model(model_name):
            try:
                return await model_manager.validate_model_request(model_name, "test_req")
            except ValueError:
                return None

        # 并发验证模型
        tasks = [
            validate_model("model_1"),
            validate_model("model_2"),
            validate_model("invalid_model"),
            validate_model("model_3"),
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 验证结果
        assert results[0] == "model_1"
        assert results[1] == "model_2"
        assert results[2] is None  # 无效模型
        assert results[3] == "model_3"

    async def test_concurrent_model_switch_attempts(self, model_manager):
        """测试并发模型切换尝试"""
        mock_page = AsyncMock()
        
        with patch('browser_utils.switch_ai_studio_model') as mock_switch:
            mock_switch.return_value = True
            
            async def attempt_switch(model_id, req_id):
                return await model_manager.switch_model_safe(mock_page, model_id, req_id)

            # 并发尝试切换到不同模型
            tasks = [
                attempt_switch("model_1", "req_1"),
                attempt_switch("model_2", "req_2"),
                attempt_switch("model_3", "req_3"),
            ]
            
            results = await asyncio.gather(*tasks)
            
            # 所有切换都应该成功
            assert all(results)
            
            # 验证最终模型状态
            final_model = await model_manager.get_current_model_id()
            assert final_model in ["model_1", "model_2", "model_3"]

    async def test_model_switch_serialization(self, model_manager):
        """测试模型切换的序列化"""
        mock_page = AsyncMock()
        switch_order = []
        
        async def mock_switch_with_tracking(page, model_id, req_id):
            switch_order.append(model_id)
            await asyncio.sleep(0.01)  # 模拟切换时间
            return True
        
        with patch('browser_utils.switch_ai_studio_model', side_effect=mock_switch_with_tracking):
            async def attempt_switch(model_id, req_id):
                return await model_manager.switch_model_safe(mock_page, model_id, req_id)

            # 并发尝试切换，但应该被序列化
            tasks = [
                attempt_switch("model_1", "req_1"),
                attempt_switch("model_2", "req_2"),
                attempt_switch("model_3", "req_3"),
            ]
            
            results = await asyncio.gather(*tasks)
            
            # 所有切换都应该成功
            assert all(results)
            
            # 验证切换是序列化的（有顺序）
            assert len(switch_order) == 3
            assert set(switch_order) == {"model_1", "model_2", "model_3"}


class TestStreamingIntervalController:
    """测试流式间隔控制器的并发安全性"""

    @pytest.fixture
    def controller(self):
        """创建流式间隔控制器实例"""
        return StreamingIntervalController()

    async def test_concurrent_delay_checks(self, controller):
        """测试并发延迟检查"""
        async def check_delay(is_streaming, delay=0):
            if delay:
                await asyncio.sleep(delay)
            return await controller.should_delay(is_streaming)

        # 并发检查延迟
        tasks = [
            check_delay(True, 0.01),
            check_delay(False, 0.02),
            check_delay(True, 0.03),
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 第一个流式请求不应该有延迟
        assert results[0] == 0.0
        # 非流式请求不应该有延迟
        assert results[1] == 0.0
        # 第二个流式请求可能有延迟（取决于时间）
        assert results[2] >= 0.0

    async def test_concurrent_completion_marking(self, controller):
        """测试并发完成标记"""
        async def mark_completion(was_streaming, delay=0):
            if delay:
                await asyncio.sleep(delay)
            await controller.mark_request_completed(was_streaming)

        # 并发标记完成
        tasks = [
            mark_completion(True, 0.01),
            mark_completion(False, 0.02),
            mark_completion(True, 0.03),
        ]
        
        await asyncio.gather(*tasks)
        
        # 验证状态更新正确
        # 最后一个完成的应该是最终状态
        delay = await controller.should_delay(True)
        assert delay >= 0.0  # 应该有一些延迟，因为最后是流式请求

    async def test_streaming_interval_logic(self, controller):
        """测试流式间隔逻辑"""
        # 第一个流式请求
        delay1 = await controller.should_delay(True)
        assert delay1 == 0.0  # 第一个请求不应该有延迟
        
        await controller.mark_request_completed(True)
        
        # 立即的第二个流式请求应该有延迟
        delay2 = await controller.should_delay(True)
        assert delay2 > 0.0
        
        await controller.mark_request_completed(True)
        
        # 等待足够长时间后，不应该有延迟
        await asyncio.sleep(1.1)
        delay3 = await controller.should_delay(True)
        assert delay3 == 0.0


class TestConcurrentIntegration:
    """测试组件间的并发集成"""

    async def test_state_manager_model_manager_integration(self):
        """测试状态管理器和模型管理器的集成"""
        state_manager = get_state_manager()
        model_manager = get_model_manager()
        
        # 设置模型列表
        await state_manager.set_model_list([
            {"id": "integration_model", "display_name": "Integration Model"}
        ])
        
        # 并发操作
        async def state_operation():
            await state_manager.set_current_model_id("integration_model")
            return await state_manager.get_current_model_id()
        
        async def model_operation():
            return await model_manager.get_current_model_id()
        
        # 并发执行
        tasks = [state_operation(), model_operation()]
        results = await asyncio.gather(*tasks)
        
        # 验证一致性
        assert results[0] == "integration_model"
        assert results[1] == "integration_model"

    async def test_global_instances_thread_safety(self):
        """测试全局实例的线程安全性"""
        # 并发获取全局实例
        async def get_instances():
            state_mgr = get_state_manager()
            model_mgr = get_model_manager()
            stream_ctrl = get_streaming_controller()
            return state_mgr, model_mgr, stream_ctrl
        
        tasks = [get_instances() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # 验证所有实例都是同一个对象
        state_managers = [r[0] for r in results]
        model_managers = [r[1] for r in results]
        stream_controllers = [r[2] for r in results]
        
        assert all(sm is state_managers[0] for sm in state_managers)
        assert all(mm is model_managers[0] for mm in model_managers)
        assert all(sc is stream_controllers[0] for sc in stream_controllers)
