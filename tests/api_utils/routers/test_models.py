from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_utils.routers.models import list_models
from config import DEFAULT_FALLBACK_MODEL_ID


@pytest.mark.asyncio
async def test_list_models_success(mock_env):
    # Mock dependencies
    logger = MagicMock()
    model_list_fetch_event = MagicMock()
    model_list_fetch_event.is_set.return_value = True

    page_instance = AsyncMock()
    page_instance.is_closed.return_value = False

    parsed_model_list = [
        {"id": "gemini-1.5-pro", "object": "model"},
        {"id": "gemini-1.5-flash", "object": "model"},
    ]
    excluded_model_ids = {"gemini-1.5-flash"}

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == "gemini-1.5-pro"


@pytest.mark.asyncio
async def test_list_models_fallback(mock_env):
    logger = MagicMock()
    model_list_fetch_event = MagicMock()
    model_list_fetch_event.is_set.return_value = True

    page_instance = AsyncMock()
    parsed_model_list = []  # Empty list
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == DEFAULT_FALLBACK_MODEL_ID


@pytest.mark.asyncio
async def test_list_models_fetch_timeout(mock_env):
    logger = MagicMock()
    model_list_fetch_event = AsyncMock()
    model_list_fetch_event.is_set.return_value = False
    # Simulate wait timeout
    model_list_fetch_event.wait.side_effect = TimeoutError("Timeout")

    page_instance = AsyncMock()
    page_instance.is_closed.return_value = False

    parsed_model_list = []
    excluded_model_ids = set()

    # Should handle exception gracefully and return fallback
    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == DEFAULT_FALLBACK_MODEL_ID


"""
Extended tests for api_utils/routers/models.py - Edge case coverage.

Focus: Cover uncovered lines in model refresh logic (35-43).
Strategy: Test page reload scenarios, event waiting, exception handling.
"""

import asyncio


@pytest.mark.asyncio
async def test_list_models_event_not_set_reload_success(mock_env):
    """
    测试场景: 模型列表事件未设置,页面重新加载成功
    预期: 执行 reload 和 wait_for, 覆盖 lines 35-38
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = False

    # Use MagicMock for page, only reload is async
    page_instance = MagicMock()
    page_instance.is_closed.return_value = False
    page_instance.reload = AsyncMock()

    # Mock wait() 在 wait_for 内部成功完成
    async def mock_wait():
        # 模拟成功等待
        model_list_fetch_event.is_set.return_value = True
        return

    model_list_fetch_event.wait = mock_wait

    parsed_model_list = [{"id": "gemini-1.5-pro", "object": "model"}]
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: 页面被重新加载
    page_instance.reload.assert_called_once()

    # 验证: 返回模型列表
    assert response["object"] == "list"
    assert len(response["data"]) == 1


@pytest.mark.asyncio
async def test_list_models_reload_timeout(mock_env):
    """
    测试场景: wait_for 超时,触发 except 和 finally
    预期: 捕获异常,记录错误,设置事件 (lines 38-43)
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = False

    # Use MagicMock for page, only reload is async
    page_instance = MagicMock()
    page_instance.is_closed.return_value = False
    page_instance.reload = AsyncMock()

    # Mock wait() to sleep briefly, but longer than the mocked timeout
    async def mock_wait_longer_than_timeout():
        await asyncio.sleep(0.2)  # Longer than mocked 0.1s timeout

    model_list_fetch_event.wait = mock_wait_longer_than_timeout

    parsed_model_list = [{"id": "gemini-1.5-pro", "object": "model"}]
    excluded_model_ids = set()

    # Patch the wait_for timeout to be very short for testing
    with patch(
        "api_utils.routers.models.asyncio.wait_for", wraps=asyncio.wait_for
    ) as mock_wait_for:
        # Override wait_for to use a short timeout
        async def short_timeout_wait_for(coro, timeout):
            return await asyncio.wait_for(coro, timeout=0.1)

        mock_wait_for.side_effect = short_timeout_wait_for

        response = await list_models(
            logger=logger,
            model_list_fetch_event=model_list_fetch_event,
            page_instance=page_instance,
            parsed_model_list=parsed_model_list,
            excluded_model_ids=excluded_model_ids,
        )

    # 验证: 错误被记录
    assert logger.error.called

    # 验证: 事件被设置 (finally block)
    model_list_fetch_event.set.assert_called()

    # 验证: 返回模型列表 (因为 parsed_model_list 不为空)
    assert response["object"] == "list"
    assert len(response["data"]) == 1


@pytest.mark.asyncio
async def test_list_models_reload_exception(mock_env):
    """
    测试场景: page.reload() 抛出异常
    预期: 捕获异常,记录错误,设置事件 (lines 37-43)
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = False

    # Use MagicMock for page, only reload is async
    page_instance = MagicMock()
    page_instance.is_closed.return_value = False

    # Mock reload 抛出异常
    page_instance.reload = AsyncMock(side_effect=Exception("Reload failed"))

    parsed_model_list = []
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: 错误被记录
    logger.error.assert_called_once()
    error_call_args = logger.error.call_args[0][0]
    assert "出错" in error_call_args

    # 验证: 事件被设置 (finally block)
    model_list_fetch_event.set.assert_called()

    # 验证: 返回后备模型 (因为 parsed_model_list 为空)
    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == DEFAULT_FALLBACK_MODEL_ID


@pytest.mark.asyncio
async def test_list_models_page_closed(mock_env):
    """
    测试场景: 页面已关闭,不执行重新加载
    预期: 跳过 reload 逻辑,直接返回
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = False

    # Use MagicMock for page, is_closed is synchronous
    page_instance = MagicMock()
    page_instance.is_closed.return_value = True  # 页面已关闭

    parsed_model_list = [{"id": "gemini-1.5-pro", "object": "model"}]
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: reload 未被调用
    page_instance.reload.assert_not_called()

    # 验证: 返回模型列表
    assert response["object"] == "list"
    assert len(response["data"]) == 1


@pytest.mark.asyncio
async def test_list_models_page_none(mock_env):
    """
    测试场景: page_instance 为 None
    预期: 跳过 reload 逻辑,直接返回
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = False

    page_instance = None  # 无页面实例

    parsed_model_list = [{"id": "gemini-1.5-pro", "object": "model"}]
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,  # type: ignore[arg-type]
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: 返回模型列表 (无需 reload)
    assert response["object"] == "list"
    assert len(response["data"]) == 1


@pytest.mark.asyncio
async def test_list_models_filter_non_dict_entries(mock_env):
    """
    测试场景: parsed_model_list 包含非字典项
    预期: 过滤掉非字典项,只返回有效的字典
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = True

    # Use MagicMock for page
    page_instance = MagicMock()

    # 包含非字典项
    parsed_model_list = [
        {"id": "gemini-1.5-pro", "object": "model"},
        "invalid_string",  # 非字典
        None,  # 非字典
        {"id": "gemini-1.5-flash", "object": "model"},
    ]
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: 只返回字典项
    assert response["object"] == "list"
    assert len(response["data"]) == 2
    assert all(isinstance(m, dict) for m in response["data"])


@pytest.mark.asyncio
async def test_list_models_empty_after_filtering(mock_env):
    """
    测试场景: 所有模型都被排除
    预期: 返回空列表,不是后备模型 (因为 parsed_model_list 不为 None)
    """
    logger = MagicMock()
    model_list_fetch_event = MagicMock(spec=asyncio.Event)
    model_list_fetch_event.is_set.return_value = True

    # Use MagicMock for page
    page_instance = MagicMock()

    parsed_model_list = [
        {"id": "gemini-1.5-pro", "object": "model"},
        {"id": "gemini-1.5-flash", "object": "model"},
    ]
    excluded_model_ids = {"gemini-1.5-pro", "gemini-1.5-flash"}  # 排除所有

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    # 验证: 返回空列表 (不是后备)
    assert response["object"] == "list"
    assert len(response["data"]) == 0
