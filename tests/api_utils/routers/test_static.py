"""
High-quality tests for api_utils/routers/static.py - Static file serving.

Focus: Test static file endpoints with both success and error paths.
Strategy: Mock Path.exists() to control file existence, test actual routing logic.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestReadIndex:
    """Tests for read_index endpoint."""

    @pytest.mark.asyncio
    async def test_read_index_react_exists(self):
        """
        测试场景: React index.html 存在
        预期: 返回 FileResponse with React index.html
        """
        from api_utils.routers.static import read_index

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            response = await read_index(logger=mock_logger)

            assert response is not None

    @pytest.mark.asyncio
    async def test_read_index_not_built(self):
        """
        测试场景: React build 不存在
        预期: 返回 503 错误 (Service Unavailable)
        """
        from api_utils.routers.static import read_index

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await read_index(logger=mock_logger)

            assert exc_info.value.status_code == 503
            assert "Frontend not built" in exc_info.value.detail
            mock_logger.error.assert_called_once()


class TestServeReactAssets:
    """Tests for serve_react_assets endpoint."""

    @pytest.mark.asyncio
    async def test_serve_react_assets_js(self):
        """
        测试场景: JS asset 存在
        预期: 返回 FileResponse with application/javascript media type
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            response = await serve_react_assets("main.js", logger=mock_logger)

            assert response is not None
            assert response.media_type == "application/javascript"

    @pytest.mark.asyncio
    async def test_serve_react_assets_css(self):
        """
        测试场景: CSS asset 存在
        预期: 返回 FileResponse with text/css media type
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            response = await serve_react_assets("style.css", logger=mock_logger)

            assert response is not None
            assert response.media_type == "text/css"

    @pytest.mark.asyncio
    async def test_serve_react_assets_map(self):
        """
        测试场景: Source map asset 存在
        预期: 返回 FileResponse with application/json media type
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            response = await serve_react_assets("main.js.map", logger=mock_logger)

            assert response is not None
            assert response.media_type == "application/json"

    @pytest.mark.asyncio
    async def test_serve_react_assets_not_found(self):
        """
        测试场景: Asset 不存在
        预期: 返回 404 错误
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await serve_react_assets("missing.js", logger=mock_logger)

            assert exc_info.value.status_code == 404
            assert "missing.js" in exc_info.value.detail
            mock_logger.debug.assert_called_once()


class TestServeFile:
    """Tests for _serve_file helper function."""

    def test_serve_file_exists(self):
        """
        测试场景: 文件存在
        预期: 返回 FileResponse
        """
        from api_utils.routers.static import _serve_file

        with patch.object(Path, "exists", return_value=True):
            mock_path = Path("/tmp/test.txt")
            response = _serve_file(mock_path)

            assert response is not None

    def test_serve_file_not_exists(self):
        """
        测试场景: 文件不存在
        预期: 抛出 HTTPException 404
        """
        from api_utils.routers.static import _serve_file

        with patch.object(Path, "exists", return_value=False):
            mock_path = Path("/tmp/missing.txt")

            with pytest.raises(HTTPException) as exc_info:
                _serve_file(mock_path)

            assert exc_info.value.status_code == 404
            assert "missing.txt" in exc_info.value.detail

    def test_serve_file_with_media_type(self):
        """
        测试场景: 指定 media_type
        预期: FileResponse 使用指定的 media_type
        """
        from api_utils.routers.static import _serve_file

        with patch.object(Path, "exists", return_value=True):
            mock_path = Path("/tmp/style.css")
            response = _serve_file(mock_path, media_type="text/css")

            assert response is not None
            assert response.media_type == "text/css"
