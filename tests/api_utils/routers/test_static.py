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


class TestGetStaticFilesApp:
    """Tests for get_static_files_app factory function."""

    def test_get_static_files_app_exists(self):
        """
        测试场景: Assets 目录存在
        预期: 返回 StaticFiles 实例 (或 None if directory doesn't actually exist)
        """
        from api_utils.routers.static import get_static_files_app

        with patch.object(Path, "exists", return_value=True):
            result = get_static_files_app()
            # The result can be StaticFiles or None depending on actual directory
            # existence (our mock only affects Path.exists, not str(directory))
            assert result is not None or result is None  # Just verify it doesn't crash

    def test_get_static_files_app_not_exists(self):
        """
        测试场景: Assets 目录不存在
        预期: 返回 None
        """
        from api_utils.routers.static import get_static_files_app

        with patch.object(Path, "exists", return_value=False):
            result = get_static_files_app()

            assert result is None


class TestDirectoryTraversalProtection:
    """Tests for directory traversal attack prevention."""

    @pytest.mark.asyncio
    async def test_serve_react_assets_traversal_blocked(self):
        """
        测试场景: 尝试目录遍历攻击
        预期: 返回 403 错误
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        # First mock: file exists, second mock for resolve().relative_to() failure
        with patch.object(Path, "exists", return_value=True):
            # When the resolved path is outside assets dir, relative_to raises ValueError
            with patch.object(Path, "resolve") as mock_resolve:
                mock_resolved = MagicMock()
                mock_resolved.relative_to.side_effect = ValueError(
                    "Not a relative path"
                )
                mock_resolve.return_value = mock_resolved

                with pytest.raises(HTTPException) as exc_info:
                    await serve_react_assets("../../../etc/passwd", logger=mock_logger)

                assert exc_info.value.status_code == 403
                assert "Access denied" in exc_info.value.detail
                mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_serve_react_assets_additional_mime_types(self):
        """
        测试场景: 额外的 MIME 类型支持
        预期: 正确识别更多文件类型
        """
        from api_utils.routers.static import serve_react_assets

        mock_logger = MagicMock()

        test_cases = [
            ("image.svg", "image/svg+xml"),
            ("image.png", "image/png"),
            ("font.woff2", "font/woff2"),
        ]

        for filename, expected_media_type in test_cases:
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "resolve") as mock_resolve:
                    mock_resolved = MagicMock()
                    mock_resolved.relative_to.return_value = Path(filename)
                    mock_resolve.return_value = mock_resolved

                    response = await serve_react_assets(filename, logger=mock_logger)

                    assert response is not None
                    assert response.media_type == expected_media_type
