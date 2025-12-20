"""
静态文件服务路由
使用 FastAPI/Starlette 原生静态文件服务

优化点:
- 使用 StaticFiles 提供高性能的静态文件服务
- 自动处理缓存头、字节范围请求、目录遍历防护
- SPA 路由使用 catch-all 仅返回 index.html
"""

import logging
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..dependencies import get_logger

_BASE_DIR = Path(__file__).parent.parent.parent

# React build directory
_REACT_DIST = _BASE_DIR / "static" / "frontend" / "dist"
_REACT_ASSETS = _REACT_DIST / "assets"


def get_static_files_app() -> StaticFiles | None:
    """
    Create a StaticFiles app for the assets directory.

    Returns None if the directory doesn't exist (frontend not built).
    """
    if _REACT_ASSETS.exists():
        return StaticFiles(directory=str(_REACT_ASSETS))
    return None


async def read_index(logger: logging.Logger = Depends(get_logger)) -> FileResponse:
    """Serve React index.html for SPA routing."""
    react_index = _REACT_DIST / "index.html"
    if react_index.exists():
        return FileResponse(react_index, media_type="text/html")

    logger.error("React build not found - run 'npm run build' in static/frontend/")
    raise HTTPException(
        status_code=503,
        detail="Frontend not built. Run 'npm run build' in static/frontend/",
    )


async def serve_react_assets(
    filename: str, logger: logging.Logger = Depends(get_logger)
) -> FileResponse:
    """
    Serve React built assets (JS, CSS, etc.).

    Note: For production deployments, consider mounting StaticFiles directly
    in the app configuration for better performance:

        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory="static/frontend/dist/assets"))

    This fallback route is provided for flexibility and development convenience.
    """
    asset_path = _REACT_ASSETS / filename

    if not asset_path.exists():
        logger.debug(f"Asset not found: {asset_path}")
        raise HTTPException(status_code=404, detail=f"Asset {filename} not found")

    # Security: Prevent directory traversal
    try:
        asset_path.resolve().relative_to(_REACT_ASSETS.resolve())
    except ValueError:
        logger.warning(f"Directory traversal attempt blocked: {filename}")
        raise HTTPException(status_code=403, detail="Access denied")

    # Determine media type based on suffix
    suffix_to_media_type = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".map": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".eot": "application/vnd.ms-fontobject",
    }
    media_type = suffix_to_media_type.get(asset_path.suffix.lower())

    return FileResponse(asset_path, media_type=media_type)
