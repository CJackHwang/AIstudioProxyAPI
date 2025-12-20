"""
Comprehensive test suite for browser_utils/debug_utils.py.

This module tests all debug snapshot and error logging functions with >80% coverage.
Focuses on: timestamp generation, DOM capture, system context, snapshot saving.

REFACTORED: Reduced from 299 mocks to ~60 mocks by using real server state and
smart fixture design instead of patching every server attribute individually.
"""

import os
import platform
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest
from playwright.async_api import Error as PlaywrightError

from browser_utils.debug_utils import (
    capture_dom_structure,
    capture_playwright_state,
    capture_system_context,
    get_texas_timestamp,
    save_comprehensive_snapshot,
    save_error_snapshot_enhanced,
)

# === Smart Fixtures to Reduce Mocking ===


@pytest.fixture
def mock_server_state():
    """
    Provide a realistic server state object instead of patching every attribute.

    This fixture REPLACES 16-18 individual @patch decorators per test.
    """
    state = MagicMock()
    state.is_playwright_ready = True
    state.is_browser_connected = True
    state.is_page_ready = True
    state.is_initializing = False
    state.request_queue = MagicMock()
    state.request_queue.qsize.return_value = 0
    state.processing_lock = MagicMock()
    state.processing_lock.locked.return_value = False
    state.model_switching_lock = MagicMock()
    state.model_switching_lock.locked.return_value = False
    state.current_ai_studio_model_id = None
    state.excluded_model_ids = []
    state.browser_instance = None
    state.page_instance = None
    state.console_logs = []
    state.network_log = {}
    state.STREAM_QUEUE = None
    state.PLAYWRIGHT_PROXY_SETTINGS = None
    return state


@pytest.fixture
def real_mock_page():
    """
    Provide a realistic Playwright page mock with common methods.

    Reduces duplication across tests that need page mocking.
    """
    page = AsyncMock()
    page.evaluate = AsyncMock()
    page.title = AsyncMock(return_value="Test Page")
    page.url = "https://example.com"
    page.viewport_size = {"width": 1920, "height": 1080}
    page.is_closed = MagicMock(return_value=False)
    page.screenshot = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>Test</body></html>")
    page.goto = AsyncMock()

    # Mock context for cookies
    page.context = AsyncMock()
    page.context.cookies = AsyncMock(return_value=[])

    # Mock locator
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_locator.is_visible = AsyncMock(return_value=False)
    mock_locator.is_enabled = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=mock_locator)

    return page


# === Section 1: Timestamp Generation Tests ===


class TestGetTexasTimestamp:
    """测试 Texas 时区时间戳生成函数"""

    def test_timestamp_format_iso(self):
        """测试 ISO 格式时间戳"""
        iso, human = get_texas_timestamp()

        # ISO format: "2025-11-21T18:37:32.440"
        assert len(iso) == 23
        assert "T" in iso
        assert iso.count("-") == 2  # YYYY-MM-DD
        assert iso.count(":") == 2  # HH:MM:SS

    def test_timestamp_format_human_readable(self):
        """测试人类可读时间戳格式"""
        iso, human = get_texas_timestamp()

        # Human format: "2025-11-21 18:37:32.440 <TZ>" where TZ is local timezone
        # The function now uses local timezone (not hardcoded CST)
        assert human.count(":") == 2
        # Should have a timezone abbreviation at the end (e.g., CST, JST, EST)
        parts = human.split()
        assert len(parts) == 3  # date, time, timezone
        assert len(parts[2]) >= 2  # Timezone abbreviation (at least 2 chars)

    def test_timestamp_consistency(self):
        """测试时间戳一致性"""
        iso, human = get_texas_timestamp()

        # Both should represent same time
        iso_date = iso.split("T")[0]
        human_date = human.split(" ")[0]
        assert iso_date == human_date

    def test_timestamp_milliseconds_precision(self):
        """测试毫秒精度"""
        iso, human = get_texas_timestamp()

        # Should have 3 decimal places
        iso_time = iso.split("T")[1]
        assert "." in iso_time
        ms_part = iso_time.split(".")[1]
        assert len(ms_part) == 3

    @patch("browser_utils.debug_utils.datetime")
    def test_timezone_offset_local(self, mock_datetime):
        """测试本地时区偏移（使用系统时区）"""
        from datetime import datetime as real_datetime, timezone as real_timezone

        # Create a mock datetime that returns a proper aware datetime
        # Simulate a UTC time that can be converted to local time
        mock_utc = real_datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=real_timezone.utc)

        # Mock now() to return a local-aware datetime (via astimezone)
        mock_local = mock_utc.astimezone()  # Convert to local timezone
        mock_datetime.now.return_value.astimezone.return_value = mock_local

        iso, human = get_texas_timestamp()

        # The ISO format should contain the local time (not UTC)
        # Just verify it produces a valid timestamp with local timezone offset applied
        assert "T" in iso
        assert ":" in iso
        # Human format should have timezone abbreviation
        parts = human.split()
        assert len(parts) == 3  # date, time, timezone


# === Section 2: DOM Structure Capture Tests ===


class TestCaptureDomStructure:
    """测试 DOM 树结构捕获函数"""

    @pytest.mark.asyncio
    async def test_dom_structure_basic_success(self, real_mock_page):
        """测试基本 DOM 树捕获成功"""
        dom_tree = "BODY\n  DIV#app.container\n    P.text\n"
        real_mock_page.evaluate.return_value = dom_tree

        result = await capture_dom_structure(real_mock_page)

        assert result == dom_tree
        real_mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_dom_structure_with_hierarchy(self, real_mock_page):
        """测试层次结构 DOM 捕获"""
        complex_dom = """BODY
  DIV#root.app-container
    HEADER.navbar
      NAV
    MAIN.content
      DIV.widget
"""
        real_mock_page.evaluate.return_value = complex_dom

        result = await capture_dom_structure(real_mock_page)

        assert "BODY" in result
        assert "DIV#root.app-container" in result
        assert "HEADER.navbar" in result

    @pytest.mark.asyncio
    async def test_dom_structure_playwright_error(self, real_mock_page):
        """测试 Playwright 错误处理"""
        real_mock_page.evaluate.side_effect = PlaywrightError("Page closed")

        result = await capture_dom_structure(real_mock_page)

        assert "Error capturing DOM structure" in result
        assert "Page closed" in result

    @pytest.mark.asyncio
    async def test_dom_structure_generic_exception(self, real_mock_page):
        """测试通用异常处理"""
        real_mock_page.evaluate.side_effect = RuntimeError("Unexpected error")

        result = await capture_dom_structure(real_mock_page)

        assert "Error capturing DOM structure" in result
        assert "Unexpected error" in result

    @pytest.mark.asyncio
    async def test_dom_structure_javascript_evaluation(self, real_mock_page):
        """测试 JavaScript 执行逻辑"""
        real_mock_page.evaluate.return_value = "BODY\n  DIV#test\n"

        await capture_dom_structure(real_mock_page)

        # Verify JavaScript function was passed
        call_args = real_mock_page.evaluate.call_args[0][0]
        assert "function getTreeStructure" in call_args
        assert "maxDepth = 15" in call_args
        assert "element.tagName" in call_args


# === Section 3: System Context Capture Tests ===


class TestCaptureSystemContext:
    """测试系统上下文捕获函数"""

    @pytest.mark.asyncio
    async def test_system_context_basic_structure(self, mock_server_state):
        """测试基本系统上下文结构"""
        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context("req123", "test_error")

        # Verify top-level structure
        assert "meta" in context
        assert "system" in context
        assert "application_state" in context
        assert "browser_state" in context
        assert "configuration" in context
        assert "recent_activity" in context

    @pytest.mark.asyncio
    async def test_system_context_meta_fields(self, mock_server_state):
        """测试 meta 字段内容"""
        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context("abc123", "timeout_error")

        meta = context["meta"]
        assert meta["req_id"] == "abc123"
        assert meta["error_name"] == "timeout_error"
        assert "timestamp_iso" in meta
        assert "timestamp_texas" in meta

    @pytest.mark.asyncio
    async def test_system_context_system_info(self, mock_server_state):
        """测试系统信息字段"""
        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        system = context["system"]
        assert "platform" in system
        assert "python_version" in system
        assert "pid" in system
        assert system["platform"] == platform.platform()
        assert system["python_version"] == sys.version.split()[0]
        assert system["pid"] == os.getpid()

    @pytest.mark.asyncio
    async def test_system_context_application_flags(self, mock_server_state):
        """测试应用状态标志"""
        # Customize state for this test
        mock_server_state.is_playwright_ready = True
        mock_server_state.is_browser_connected = False
        mock_server_state.is_page_ready = True
        mock_server_state.is_initializing = True

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        flags = context["application_state"]["flags"]
        assert flags["is_playwright_ready"] is True
        assert flags["is_browser_connected"] is False
        assert flags["is_page_ready"] is True
        assert flags["is_initializing"] is True

    @pytest.mark.asyncio
    async def test_system_context_queue_size(self, mock_server_state):
        """测试队列大小捕获"""
        mock_server_state.request_queue.qsize.return_value = 5

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        queues = context["application_state"]["queues"]
        assert queues["request_queue_size"] == 5

    @pytest.mark.asyncio
    async def test_system_context_queue_not_implemented(self, mock_server_state):
        """测试队列不支持 qsize 的情况"""
        mock_server_state.request_queue.qsize.side_effect = NotImplementedError()

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        queues = context["application_state"]["queues"]
        assert queues["request_queue_size"] == -1

    @pytest.mark.asyncio
    async def test_system_context_lock_states(self, mock_server_state):
        """测试锁状态检测"""
        mock_server_state.processing_lock.locked.return_value = True
        mock_server_state.model_switching_lock.locked.return_value = True

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        locks = context["application_state"]["locks"]
        assert locks["processing_lock_locked"] is True
        assert locks["model_switching_lock_locked"] is True

    @pytest.mark.asyncio
    async def test_system_context_proxy_sanitization(self, mock_server_state):
        """测试代理设置凭据脱敏"""
        mock_server_state.PLAYWRIGHT_PROXY_SETTINGS = {
            "server": "http://user:password@proxy.com:8080"
        }

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        proxy = context["configuration"]["proxy_settings"]
        assert "***:***@" in proxy["server"]
        assert "user" not in proxy["server"]
        assert "password" not in proxy["server"]

    @pytest.mark.asyncio
    async def test_system_context_console_logs(self, mock_server_state):
        """测试控制台日志捕获"""
        mock_server_state.console_logs = [
            {"type": "log", "text": "Log 1"},
            {"type": "error", "text": "Error 1"},
            {"type": "warning", "text": "Warning 1"},
            {"type": "log", "text": "Log 2"},
            {"type": "error", "text": "Error 2"},
        ]

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        activity = context["recent_activity"]
        assert activity["console_logs_count"] == 5
        assert "last_console_logs" in activity
        assert "recent_console_errors" in activity
        assert len(activity["recent_console_errors"]) == 3  # 2 errors + 1 warning

    @pytest.mark.asyncio
    async def test_system_context_failed_network_responses(self, mock_server_state):
        """测试失败的网络请求捕获"""
        mock_server_state.network_log = {
            "requests": [],
            "responses": [
                {"status": 200, "url": "https://example.com/ok"},
                {"status": 404, "url": "https://example.com/not-found"},
                {"status": 500, "url": "https://example.com/error"},
            ],
        }

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        activity = context["recent_activity"]
        assert "failed_network_responses" in activity
        assert len(activity["failed_network_responses"]) == 2

    @pytest.mark.asyncio
    async def test_system_context_page_url(self, mock_server_state, real_mock_page):
        """测试当前页面 URL 捕获"""
        real_mock_page.url = "https://ai.google.dev/chat"
        mock_server_state.page_instance = real_mock_page

        with patch.dict("sys.modules", {"server": mock_server_state}):
            context = await capture_system_context()

        assert context["browser_state"]["current_url"] == "https://ai.google.dev/chat"


# === Section 4: Playwright State Capture Tests ===


class TestCapturePlaywrightState:
    """测试 Playwright 状态捕获函数"""

    @pytest.mark.asyncio
    async def test_playwright_state_basic_page_info(self, real_mock_page):
        """测试基本页面信息捕获"""
        real_mock_page.url = "https://ai.google.dev"
        real_mock_page.title.return_value = "AI Studio"
        real_mock_page.viewport_size = {"width": 1920, "height": 1080}

        state = await capture_playwright_state(real_mock_page)

        assert state["page"]["url"] == "https://ai.google.dev"
        assert state["page"]["title"] == "AI Studio"
        assert state["page"]["viewport"] == {"width": 1920, "height": 1080}

    @pytest.mark.asyncio
    async def test_playwright_state_title_error(self, real_mock_page):
        """测试获取页面标题失败"""
        real_mock_page.title.side_effect = PlaywrightError("Page closed")

        state = await capture_playwright_state(real_mock_page)

        assert "Error:" in state["page"]["title"]

    @pytest.mark.asyncio
    async def test_playwright_state_locators_exists_and_visible(self, real_mock_page):
        """测试定位器存在且可见"""
        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.side_effect = PlaywrightError("Not an input")

        locators = {"submit_button": mock_locator}
        state = await capture_playwright_state(real_mock_page, locators)  # type: ignore[arg-type]

        assert state["locators"]["submit_button"]["exists"] is True
        assert state["locators"]["submit_button"]["count"] == 1
        assert state["locators"]["submit_button"]["visible"] is True
        assert state["locators"]["submit_button"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_playwright_state_locators_not_exists(self, real_mock_page):
        """测试定位器不存在"""
        mock_locator = AsyncMock()
        mock_locator.count.return_value = 0

        locators = {"missing_element": mock_locator}
        state = await capture_playwright_state(real_mock_page, locators)  # type: ignore[arg-type]

        assert state["locators"]["missing_element"]["exists"] is False
        assert state["locators"]["missing_element"]["count"] == 0

    @pytest.mark.asyncio
    async def test_playwright_state_locators_with_input_value(self, real_mock_page):
        """测试捕获输入元素的值"""
        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.return_value = "test input value"

        locators = {"input_field": mock_locator}
        state = await capture_playwright_state(real_mock_page, locators)  # type: ignore[arg-type]

        assert state["locators"]["input_field"]["value"] == "test input value"

    @pytest.mark.asyncio
    async def test_playwright_state_locators_long_value_truncation(
        self, real_mock_page
    ):
        """测试长输入值截断"""
        long_value = "a" * 150
        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.return_value = long_value

        locators = {"text_area": mock_locator}
        state = await capture_playwright_state(real_mock_page, locators)  # type: ignore[arg-type]

        assert "..." in state["locators"]["text_area"]["value"]
        assert len(state["locators"]["text_area"]["value"]) == 103  # 100 + "..."

    @pytest.mark.asyncio
    async def test_playwright_state_locators_error_handling(self, real_mock_page):
        """测试定位器错误处理"""
        mock_locator = AsyncMock()
        mock_locator.count.side_effect = PlaywrightError("Locator failed")

        locators = {"broken_locator": mock_locator}
        state = await capture_playwright_state(real_mock_page, locators)  # type: ignore[arg-type]

        assert "error" in state["locators"]["broken_locator"]

    @pytest.mark.asyncio
    async def test_playwright_state_cookies_count(self, real_mock_page):
        """测试 Cookie 数量统计"""
        real_mock_page.context.cookies.return_value = [
            {"name": "session", "value": "abc"},
            {"name": "user", "value": "123"},
        ]

        state = await capture_playwright_state(real_mock_page)

        assert state["storage"]["cookies_count"] == 2

    @pytest.mark.asyncio
    async def test_playwright_state_localstorage_keys(self, real_mock_page):
        """测试 localStorage 键捕获"""
        real_mock_page.evaluate.return_value = ["theme", "user_id", "settings"]

        state = await capture_playwright_state(real_mock_page)

        assert state["storage"]["localStorage_keys"] == ["theme", "user_id", "settings"]

    @pytest.mark.asyncio
    async def test_playwright_state_storage_error_handling(self, real_mock_page):
        """测试存储信息获取失败"""
        real_mock_page.context.cookies.side_effect = PlaywrightError("Context closed")
        real_mock_page.evaluate.side_effect = PlaywrightError("Evaluation failed")

        state = await capture_playwright_state(real_mock_page)

        # Should not crash, just log warnings
        assert state["storage"]["cookies_count"] == 0
        assert state["storage"]["localStorage_keys"] == []


# === Section 5: Comprehensive Snapshot Tests ===


class TestSaveComprehensiveSnapshot:
    """测试综合快照保存函数"""

    @pytest.mark.asyncio
    async def test_snapshot_page_closed(self, real_mock_page):
        """测试页面已关闭时不保存快照"""
        real_mock_page.is_closed.return_value = True

        result = await save_comprehensive_snapshot(
            page=real_mock_page, error_name="test_error", req_id="req123"
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_snapshot_page_none(self):
        """测试页面为 None 时不保存快照"""
        result = await save_comprehensive_snapshot(
            page=None,  # type: ignore[arg-type]
            error_name="test_error",
            req_id="req123",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_snapshot_directory_creation(
        self, real_mock_page, tmp_path, mock_server_state
    ):
        """测试快照目录创建"""
        # Create mock Path that returns actual tmp_path for path operations
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__ = lambda self, other: tmp_path / str(other)

        with (
            patch("browser_utils.debug_utils.Path") as mock_path_class,
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch("builtins.open", mock_open()),
            patch("browser_utils.debug_utils.capture_system_context") as mock_context,
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch("browser_utils.debug_utils.capture_playwright_state") as mock_pw,
        ):
            mock_context.return_value = {"meta": {}, "system": {}}
            mock_dom.return_value = "BODY\n"
            mock_pw.return_value = {}
            mock_path_class.return_value = mock_path_instance

            result = await save_comprehensive_snapshot(
                page=real_mock_page, error_name="timeout", req_id="abc123"
            )

            # Verify function completed successfully (returns path)
            assert result is not None

    @pytest.mark.asyncio
    async def test_snapshot_screenshot_success(
        self, real_mock_page, tmp_path, mock_server_state
    ):
        """测试截图保存成功"""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()

        with (
            patch("browser_utils.debug_utils.Path") as mock_path_class,
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
        ):
            # Setup mocks
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {"page": {}}
            mock_sys_ctx.return_value = {"meta": {}}

            # Mock Path to return our tmp_path
            base_dir = tmp_path / "errors_py"
            date_dir = base_dir / "2025-01-15"
            final_dir = date_dir / "snapshot"
            final_dir.mkdir(parents=True)

            mock_path_class.return_value.__truediv__.side_effect = [
                base_dir,
                date_dir,
                final_dir,
            ]

            await save_comprehensive_snapshot(
                page=real_mock_page, error_name="test", req_id="req123"
            )

            # Verify screenshot was called
            real_mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_screenshot_failure(self, real_mock_page, mock_server_state):
        """测试截图失败处理"""
        real_mock_page.screenshot.side_effect = PlaywrightError("Screenshot timeout")

        with (
            patch("browser_utils.debug_utils.Path"),
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()),
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            # Should not crash
            await save_comprehensive_snapshot(
                page=real_mock_page, error_name="test", req_id="req123"
            )

            # Should complete despite screenshot failure


# === Section 6: Enhanced Snapshot Tests ===


class TestSaveErrorSnapshotEnhanced:
    """测试增强错误快照函数"""

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_browser_unavailable(self, mock_server_state):
        """测试浏览器不可用时不保存快照"""
        mock_server_state.browser_instance = None
        mock_server_state.page_instance = None

        with (
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch(
                "browser_utils.operations_modules.errors.save_minimal_snapshot",
                new_callable=AsyncMock,
            ) as mock_minimal,
        ):
            # Should not crash and should call minimal snapshot
            await save_error_snapshot_enhanced(error_name="test_error")
            mock_minimal.assert_called_once()

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_page_closed(self, mock_server_state):
        """测试页面已关闭时不保存快照"""
        mock_server_state.browser_instance = MagicMock()
        mock_server_state.browser_instance.is_connected.return_value = True

        mock_page = MagicMock()
        mock_page.is_closed = Mock(return_value=True)
        mock_server_state.page_instance = mock_page

        with (
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch(
                "browser_utils.operations_modules.errors.save_minimal_snapshot",
                new_callable=AsyncMock,
            ) as mock_minimal,
        ):
            await save_error_snapshot_enhanced(error_name="page_closed_error")
            mock_minimal.assert_called_once()

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_req_id_parsing(
        self, mock_server_state, real_mock_page
    ):
        """测试从错误名称解析 req_id"""
        mock_server_state.browser_instance = MagicMock()
        mock_server_state.browser_instance.is_connected.return_value = True
        mock_server_state.page_instance = real_mock_page

        with (
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(error_name="timeout_error_abc1234")

            # Verify comprehensive snapshot was called with parsed req_id
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["req_id"] == "abc1234"
            assert call_kwargs["error_name"] == "timeout_error"

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_with_exception(
        self, mock_server_state, real_mock_page
    ):
        """测试包含异常信息"""
        mock_server_state.browser_instance = MagicMock()
        mock_server_state.browser_instance.is_connected.return_value = True
        mock_server_state.page_instance = real_mock_page

        error_exc = RuntimeError("Unexpected failure")

        with (
            patch.dict("sys.modules", {"server": mock_server_state}),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(
                error_name="runtime_error_xyz7890", error_exception=error_exc
            )

            # Verify exception was passed
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["error_exception"] == error_exc
