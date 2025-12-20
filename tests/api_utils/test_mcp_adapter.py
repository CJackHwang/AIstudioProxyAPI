"""
High-quality tests for api_utils/mcp_adapter.py - MCP-over-HTTP adapter.

Focus: Test all functions with success paths, error paths, edge cases.
Strategy: Mock httpx AsyncClient, environment variables, test all code paths.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api_utils.mcp_adapter import (
    _normalize_endpoint,
    execute_mcp_tool,
    execute_mcp_tool_with_endpoint,
)


class TestNormalizeEndpoint:
    """Tests for _normalize_endpoint function."""

    def test_empty_string_raises(self):
        """
        测试场景: 空字符串端点
        预期: 抛出 RuntimeError (lines 9-10)
        """
        with pytest.raises(RuntimeError) as exc_info:
            _normalize_endpoint("")

        # 验证: 错误消息
        assert "MCP HTTP endpoint not provided" in str(exc_info.value)

    def test_no_trailing_slash(self):
        """
        测试场景: 正常 URL 无尾部斜杠
        预期: 原样返回 (line 11)
        """
        url = "http://localhost:8080"
        result = _normalize_endpoint(url)

        # 验证: 不变
        assert result == url

    def test_with_single_trailing_slash(self):
        """
        测试场景: URL 有单个尾部斜杠
        预期: 去除尾部斜杠 (line 11)
        """
        url = "http://localhost:8080/"
        result = _normalize_endpoint(url)

        # 验证: 斜杠被去除
        assert result == "http://localhost:8080"

    def test_with_multiple_trailing_slashes(self):
        """
        测试场景: URL 有多个尾部斜杠
        预期: 去除所有尾部斜杠 (line 11)
        """
        url = "http://localhost:8080///"
        result = _normalize_endpoint(url)

        # 验证: 所有斜杠被去除
        assert result == "http://localhost:8080"

    def test_with_path_and_trailing_slash(self):
        """
        测试场景: URL 有路径和尾部斜杠
        预期: 只移除尾部斜杠,保持路径
        """
        url = "http://localhost:8080/api/v1/"
        result = _normalize_endpoint(url)

        assert result == "http://localhost:8080/api/v1"


class TestExecuteMcpTool:
    """Tests for execute_mcp_tool async function."""

    @pytest.mark.asyncio
    async def test_success_with_json_response(self):
        """
        测试场景: 成功执行 MCP 工具,返回 JSON
        预期: 返回 JSON 字符串
        """
        tool_name = "test_tool"
        params = {"arg1": "value1", "arg2": 123}
        response_data = {"result": "success", "data": {"output": "test"}}

        with patch.dict(os.environ, {"MCP_HTTP_ENDPOINT": "http://localhost:8080"}):
            mock_response = MagicMock()
            mock_response.json.return_value = response_data
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await execute_mcp_tool(tool_name, params)

        # 验证: 返回 JSON 字符串
        assert result == json.dumps(response_data, ensure_ascii=False)

        # 验证: POST 请求参数正确
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8080/tools/execute"
        assert call_args[1]["json"] == {"name": tool_name, "arguments": params}
        assert call_args[1]["headers"] == {"Content-Type": "application/json"}

    @pytest.mark.asyncio
    async def test_success_with_non_json_response(self):
        """
        测试场景: 成功执行但响应非 JSON
        预期: 返回 {"raw": text} 格式
        """
        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {"MCP_HTTP_ENDPOINT": "http://localhost:8080"}):
            mock_response = MagicMock()
            mock_response.json.side_effect = Exception("Invalid JSON")
            mock_response.text = "Plain text response"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await execute_mcp_tool(tool_name, params)

        # 验证: 返回包装后的文本
        expected = json.dumps({"raw": "Plain text response"}, ensure_ascii=False)
        assert result == expected

    @pytest.mark.asyncio
    async def test_missing_endpoint_env(self):
        """
        测试场景: MCP_HTTP_ENDPOINT 未配置
        预期: 抛出 RuntimeError
        """
        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                await execute_mcp_tool(tool_name, params)

        # 验证: 错误消息
        assert "MCP_HTTP_ENDPOINT not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_error(self):
        """
        测试场景: HTTP 请求失败 (非 2xx 状态)
        预期: 抛出 HTTPStatusError
        """
        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {"MCP_HTTP_ENDPOINT": "http://localhost:8080"}):
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=MagicMock()
            )

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(httpx.HTTPStatusError):
                    await execute_mcp_tool(tool_name, params)

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """
        测试场景: 自定义超时时间 (MCP_HTTP_TIMEOUT)
        预期: 使用自定义超时创建客户端
        """
        tool_name = "test_tool"
        params = {}
        custom_timeout = "30"

        with patch.dict(
            os.environ,
            {
                "MCP_HTTP_ENDPOINT": "http://localhost:8080",
                "MCP_HTTP_TIMEOUT": custom_timeout,
            },
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = {"result": "ok"}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch(
                "httpx.AsyncClient", return_value=mock_client
            ) as mock_async_client:
                await execute_mcp_tool(tool_name, params)

            # 验证: AsyncClient 使用自定义超时
            mock_async_client.assert_called_once_with(timeout=30.0)

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        """
        测试场景: 使用默认超时时间
        预期: 使用 15.0 秒超时
        """
        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {"MCP_HTTP_ENDPOINT": "http://localhost:8080"}):
            mock_response = MagicMock()
            mock_response.json.return_value = {"result": "ok"}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch(
                "httpx.AsyncClient", return_value=mock_client
            ) as mock_async_client:
                await execute_mcp_tool(tool_name, params)

            # 验证: AsyncClient 使用默认超时
            mock_async_client.assert_called_once_with(timeout=15.0)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """
        测试场景: asyncio.CancelledError 发生
        预期: 错误被重新抛出,不被捕获
        """
        import asyncio

        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {"MCP_HTTP_ENDPOINT": "http://localhost:8080"}):
            mock_response = MagicMock()
            mock_response.json.side_effect = asyncio.CancelledError()
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(asyncio.CancelledError):
                    await execute_mcp_tool(tool_name, params)


class TestExecuteMcpToolWithEndpoint:
    """Tests for execute_mcp_tool_with_endpoint async function."""

    @pytest.mark.asyncio
    async def test_success(self):
        """
        测试场景: 成功执行 (使用显式端点)
        预期: 返回 JSON 字符串
        """
        endpoint = "http://custom-endpoint:9000"
        tool_name = "custom_tool"
        params = {"key": "value"}
        response_data = {"status": "done"}

        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

        # 验证: 返回 JSON 字符串
        assert result == json.dumps(response_data, ensure_ascii=False)

        # 验证: 使用正确的 URL
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://custom-endpoint:9000/tools/execute"

    @pytest.mark.asyncio
    async def test_empty_endpoint_raises(self):
        """
        测试场景: 空端点字符串
        预期: _normalize_endpoint 抛出 RuntimeError
        """
        endpoint = ""
        tool_name = "test_tool"
        params = {}

        with pytest.raises(RuntimeError) as exc_info:
            await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

        # 验证: 错误来自 _normalize_endpoint
        assert "MCP HTTP endpoint not provided" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_json_response(self):
        """
        测试场景: 使用显式端点执行,响应非 JSON
        预期: 返回 {"raw": text} 格式
        """
        endpoint = "http://custom-endpoint:9000"
        tool_name = "custom_tool"
        params = {"key": "value"}

        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Non-JSON custom response"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

        # 验证: 返回包装后的文本
        expected = json.dumps({"raw": "Non-JSON custom response"}, ensure_ascii=False)
        assert result == expected

    @pytest.mark.asyncio
    async def test_http_error(self):
        """
        测试场景: HTTP 请求失败
        预期: 抛出 HTTPStatusError
        """
        endpoint = "http://custom-endpoint:9000"
        tool_name = "test_tool"
        params = {}

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """
        测试场景: asyncio.CancelledError 发生
        预期: 错误被重新抛出
        """
        import asyncio

        endpoint = "http://custom-endpoint:9000"
        tool_name = "test_tool"
        params = {}

        mock_response = MagicMock()
        mock_response.json.side_effect = asyncio.CancelledError()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(asyncio.CancelledError):
                await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

    @pytest.mark.asyncio
    async def test_uses_env_timeout(self):
        """
        测试场景: 使用环境变量超时
        预期: 从 MCP_HTTP_TIMEOUT 获取超时值
        """
        endpoint = "http://custom-endpoint:9000"
        tool_name = "test_tool"
        params = {}

        with patch.dict(os.environ, {"MCP_HTTP_TIMEOUT": "60"}):
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch(
                "httpx.AsyncClient", return_value=mock_client
            ) as mock_async_client:
                await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

            mock_async_client.assert_called_once_with(timeout=60.0)

    @pytest.mark.asyncio
    async def test_endpoint_with_path(self):
        """
        测试场景: 端点包含路径
        预期: 正确拼接 /tools/execute
        """
        endpoint = "http://custom-endpoint:9000/api/v1"
        tool_name = "test_tool"
        params = {}
        response_data = {"ok": True}

        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://custom-endpoint:9000/api/v1/tools/execute"

    @pytest.mark.asyncio
    async def test_complex_params(self):
        """
        测试场景: 复杂参数结构
        预期: 正确序列化嵌套数据
        """
        endpoint = "http://custom-endpoint:9000"
        tool_name = "complex_tool"
        params = {
            "nested": {"level1": {"level2": "value"}},
            "list": [1, 2, 3],
            "unicode": "你好世界",
            "boolean": True,
            "null": None,
        }
        response_data = {"received": True}

        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await execute_mcp_tool_with_endpoint(endpoint, tool_name, params)

        # 验证: 请求包含正确的复杂参数
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["arguments"] == params
        assert result == json.dumps(response_data, ensure_ascii=False)
