"""
Server Control API Router

Provides endpoints for server status and control operations.
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("CamoufoxLauncher")

router = APIRouter(prefix="/api/server", tags=["server"])

# Track server start time
_SERVER_START_TIME: Optional[float] = None


def _init_start_time() -> None:
    """Initialize server start time (called once at startup)."""
    global _SERVER_START_TIME
    if _SERVER_START_TIME is None:
        _SERVER_START_TIME = time.time()


_init_start_time()


class ServerStatus(BaseModel):
    """Server status information."""

    status: str
    uptime_seconds: float
    uptime_formatted: str
    launch_mode: str
    server_port: int
    stream_port: int
    version: str
    python_version: str
    started_at: str


class RestartRequest(BaseModel):
    """Restart request with mode."""

    mode: str = "headless"  # headless, debug, virtual_display
    confirm: bool = False


def _format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    parts.append(f"{secs}秒")

    return " ".join(parts)


@router.get("/status")
async def get_server_status() -> JSONResponse:
    """获取服务器状态信息。"""
    import sys

    uptime = time.time() - (_SERVER_START_TIME or time.time())
    started_at = datetime.fromtimestamp(_SERVER_START_TIME or time.time())

    status = ServerStatus(
        status="running",
        uptime_seconds=round(uptime, 2),
        uptime_formatted=_format_uptime(uptime),
        launch_mode=os.environ.get("LAUNCH_MODE", "unknown"),
        server_port=int(
            os.environ.get("SERVER_PORT_INFO", os.environ.get("PORT", 2048))
        ),
        stream_port=int(os.environ.get("STREAM_PORT", 3120)),
        version="1.0.0",  # Could read from package
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        started_at=started_at.isoformat(),
    )

    return JSONResponse(content=status.model_dump())


@router.post("/restart")
async def restart_server(request: RestartRequest) -> JSONResponse:
    """
    请求服务器重启。

    注意：这个操作会终止当前进程，需要外部进程管理器重新启动。
    """
    if not request.confirm:
        return JSONResponse(
            content={
                "success": False,
                "message": "重启操作需要确认。请设置 confirm=true",
            },
            status_code=400,
        )

    valid_modes = ["headless", "debug", "virtual_display"]
    if request.mode not in valid_modes:
        return JSONResponse(
            content={
                "success": False,
                "message": f"无效的启动模式。有效选项: {valid_modes}",
            },
            status_code=400,
        )

    logger.info(f"[Server] 收到重启请求，目标模式: {request.mode}")

    # Set environment variable for next launch
    os.environ["REQUESTED_RESTART_MODE"] = request.mode

    # Return success - actual restart needs to be handled by process manager
    return JSONResponse(
        content={
            "success": True,
            "message": f"服务器将以 {request.mode} 模式重启。请刷新页面。",
            "mode": request.mode,
        }
    )
