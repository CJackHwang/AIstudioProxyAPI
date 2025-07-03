"""
测试浏览器资源管理器
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from browser_utils.resource_manager import BrowserResourceManager, get_resource_manager


class TestBrowserResourceManager:
    """测试浏览器资源管理器"""

    @pytest.fixture
    async def resource_manager(self):
        """创建资源管理器实例"""
        manager = BrowserResourceManager()
        yield manager
        await manager.close_all()

    @pytest.fixture
    def mock_browser(self):
        """模拟浏览器实例"""
        browser = AsyncMock()
        # 设置为同步方法返回值，而不是异步
        browser.is_connected = MagicMock(return_value=True)
        return browser

    @pytest.fixture
    def mock_context(self):
        """模拟浏览器上下文"""
        context = AsyncMock()
        context.pages = []
        return context

    @pytest.fixture
    def mock_page(self):
        """模拟页面实例"""
        page = AsyncMock()
        # 设置为同步方法返回值
        page.is_closed = MagicMock(return_value=False)
        return page

    async def test_set_browser(self, resource_manager, mock_browser):
        """测试设置浏览器实例"""
        await resource_manager.set_browser(mock_browser)
        assert resource_manager.browser == mock_browser
        assert resource_manager.is_connected is True

    async def test_create_context(self, resource_manager, mock_browser, mock_context):
        """测试创建浏览器上下文"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context

        async with resource_manager.create_context() as context:
            assert context == mock_context
            mock_browser.new_context.assert_called_once()

        # 验证上下文被正确关闭
        mock_context.close.assert_called_once()

    async def test_create_page(self, resource_manager, mock_browser, mock_context, mock_page):
        """测试创建页面"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        async with resource_manager.create_page() as page:
            assert page == mock_page
            mock_context.new_page.assert_called_once()

        # 验证页面被正确关闭
        mock_page.close.assert_called_once()

    async def test_create_page_with_existing_context(self, resource_manager, mock_context, mock_page):
        """测试在现有上下文中创建页面"""
        mock_context.new_page.return_value = mock_page

        async with resource_manager.create_page(context=mock_context) as page:
            assert page == mock_page
            mock_context.new_page.assert_called_once()

        # 验证页面被正确关闭
        mock_page.close.assert_called_once()

    async def test_close_all(self, resource_manager, mock_browser, mock_context, mock_page):
        """测试关闭所有资源"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_context.pages = [mock_page]

        # 创建一些资源
        async with resource_manager.create_context() as context:
            async with resource_manager.create_page(context=context) as page:
                pass

        # 关闭所有资源
        await resource_manager.close_all()

        # 验证所有资源都被关闭
        mock_page.close.assert_called()
        mock_context.close.assert_called()
        mock_browser.close.assert_called_once()

    async def test_exception_handling_in_context_creation(self, resource_manager, mock_browser):
        """测试上下文创建时的异常处理"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.side_effect = Exception("Context creation failed")

        with pytest.raises(Exception, match="Context creation failed"):
            async with resource_manager.create_context():
                pass

    async def test_exception_handling_in_page_creation(self, resource_manager, mock_browser, mock_context):
        """测试页面创建时的异常处理"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.side_effect = Exception("Page creation failed")

        with pytest.raises(Exception, match="Page creation failed"):
            async with resource_manager.create_page():
                pass

    async def test_browser_not_connected_error(self, resource_manager):
        """测试浏览器未连接时的错误"""
        with pytest.raises(RuntimeError, match="浏览器未连接"):
            async with resource_manager.create_context():
                pass

    async def test_global_resource_manager(self):
        """测试全局资源管理器"""
        manager1 = get_resource_manager()
        manager2 = get_resource_manager()
        assert manager1 is manager2  # 应该是同一个实例

    async def test_context_manager_protocol(self, resource_manager):
        """测试上下文管理器协议"""
        async with resource_manager as manager:
            assert manager is resource_manager

        # 验证退出时资源被清理（通过mock验证）
        # 这里我们无法直接验证，但可以确保没有异常抛出

    @pytest.mark.asyncio
    async def test_concurrent_resource_creation(self, resource_manager, mock_browser, mock_context, mock_page):
        """测试并发资源创建"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        async def create_page():
            async with resource_manager.create_page() as page:
                await asyncio.sleep(0.1)  # 模拟一些异步操作
                return page

        # 并发创建多个页面
        tasks = [create_page() for _ in range(3)]
        pages = await asyncio.gather(*tasks)

        assert len(pages) == 3
        assert all(page == mock_page for page in pages)

    async def test_resource_cleanup_on_exception(self, resource_manager, mock_browser, mock_context, mock_page):
        """测试异常时的资源清理"""
        await resource_manager.set_browser(mock_browser)
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        with pytest.raises(ValueError, match="Test exception"):
            async with resource_manager.create_context() as context:
                async with resource_manager.create_page(context=context) as page:
                    raise ValueError("Test exception")

        # 验证即使发生异常，资源也被正确清理
        mock_page.close.assert_called()
        mock_context.close.assert_called()
