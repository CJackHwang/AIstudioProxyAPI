"""
静态文件服务路由
仅支持React构建（旧版已弃用）
"""

import logging
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from ..dependencies import get_logger

_BASE_DIR = Path(__file__).parent.parent.parent

# React build directory
_REACT_DIST = _BASE_DIR / "static" / "frontend" / "dist"


def _serve_file(path: Path, media_type: str | None = None) -> FileResponse:
    """Serve a file with proper headers."""
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    return FileResponse(path, media_type=media_type)


async def read_index(logger: logging.Logger = Depends(get_logger)) -> FileResponse:
    """Serve React index.html."""
    react_index = _REACT_DIST / "index.html"
    if react_index.exists():
        return FileResponse(react_index)

    logger.error("React build not found - run 'npm run build' in static/frontend/")
    raise HTTPException(
        status_code=503,
        detail="Frontend not built. Run 'npm run build' in static/frontend/",
    )


async def serve_react_assets(
    filename: str, logger: logging.Logger = Depends(get_logger)
) -> FileResponse:
    """Serve React built assets (JS, CSS, etc.)."""
    asset_path = _REACT_DIST / "assets" / filename

    if not asset_path.exists():
        logger.debug(f"Asset not found: {asset_path}")
        raise HTTPException(status_code=404, detail=f"Asset {filename} not found")

    # Determine media type
    media_type = None
    suffix = asset_path.suffix.lower()
    if suffix == ".js":
        media_type = "application/javascript"
    elif suffix == ".css":
        media_type = "text/css"
    elif suffix == ".map":
        media_type = "application/json"

    return FileResponse(asset_path, media_type=media_type)
