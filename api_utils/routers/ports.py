"""
Port Configuration and Status API Router

Endpoints for port configuration, status querying, and process management.
"""

import json
import os
import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/ports", tags=["ports"])

# Config file path
_CONFIG_DIR = Path(__file__).parent.parent.parent
_PORTS_CONFIG_FILE = _CONFIG_DIR / "ports_config.json"


class PortConfig(BaseModel):
    """Port configuration model."""

    fastapi_port: int = Field(default=2048, ge=1024, le=65535)
    camoufox_debug_port: int = Field(default=9222, ge=1024, le=65535)
    stream_proxy_port: int = Field(default=3120, ge=0, le=65535)
    stream_proxy_enabled: bool = True

    @field_validator("fastapi_port", "camoufox_debug_port")
    @classmethod
    def validate_required_port(cls, v: int) -> int:
        if v < 1024:
            raise ValueError("端口必须 >= 1024")
        return v


class ProcessInfo(BaseModel):
    """Information about a process."""

    pid: int
    name: str


class PortStatus(BaseModel):
    """Status of a port."""

    port: int
    port_type: str
    in_use: bool
    processes: list[ProcessInfo] = []


class KillRequest(BaseModel):
    """Request to kill a process."""

    pid: int = Field(..., ge=1, description="要终止的进程PID")
    confirm: bool = Field(default=False, description="确认终止")


def _load_port_config() -> PortConfig:
    """Load port config from file or environment."""
    # Environment variables take priority
    config = PortConfig(
        fastapi_port=int(os.environ.get("DEFAULT_FASTAPI_PORT", "2048")),
        camoufox_debug_port=int(os.environ.get("DEFAULT_CAMOUFOX_PORT", "9222")),
        stream_proxy_port=int(os.environ.get("STREAM_PORT", "3120")),
        stream_proxy_enabled=os.environ.get("STREAM_PORT", "3120") != "0",
    )

    # Override with saved config if exists
    if _PORTS_CONFIG_FILE.exists():
        try:
            data = json.loads(_PORTS_CONFIG_FILE.read_text(encoding="utf-8"))
            config = PortConfig(**data)
        except Exception:
            pass

    return config


def _save_port_config(config: PortConfig) -> None:
    """Save port config to file."""
    _PORTS_CONFIG_FILE.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_processes_on_port(port: int) -> list[ProcessInfo]:
    """Find processes listening on a port."""
    processes: list[ProcessInfo] = []
    system = platform.system()

    try:
        if system in ("Linux", "Darwin"):
            cmd = f"lsof -ti tcp:{port} -sTCP:LISTEN"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = [
                    int(p) for p in result.stdout.strip().splitlines() if p.isdigit()
                ]
                for pid in pids:
                    name = _get_process_name(pid)
                    processes.append(ProcessInfo(pid=pid, name=name))

        elif system == "Windows":
            cmd = "netstat -ano -p TCP"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    parts = line.split()
                    if (
                        len(parts) >= 5
                        and parts[0].upper() == "TCP"
                        and parts[3].upper() == "LISTENING"
                    ):
                        local_addr = parts[1]
                        if local_addr.endswith(f":{port}"):
                            pid_str = parts[4]
                            if pid_str.isdigit():
                                pid = int(pid_str)
                                name = _get_process_name(pid)
                                processes.append(ProcessInfo(pid=pid, name=name))

    except Exception:
        pass

    # Deduplicate by PID
    seen_pids: set[int] = set()
    unique_processes: list[ProcessInfo] = []
    for p in processes:
        if p.pid not in seen_pids:
            seen_pids.add(p.pid)
            unique_processes.append(p)

    return unique_processes


def _get_process_name(pid: int) -> str:
    """Get process name by PID."""
    system = platform.system()

    try:
        if system == "Linux":
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        elif system == "Darwin":
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        elif system == "Windows":
            result = subprocess.run(
                ["tasklist", "/NH", "/FO", "CSV", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('","')
                if parts:
                    return parts[0].strip('"')

    except Exception:
        pass

    return "Unknown"


def _kill_process(pid: int) -> tuple[bool, str]:
    """Kill a process by PID. Returns (success, message)."""
    system = platform.system()

    try:
        if system in ("Linux", "Darwin"):
            # Try SIGTERM first
            subprocess.run(["kill", "-TERM", str(pid)], capture_output=True, timeout=3)
            import time

            time.sleep(0.5)

            # Check if still alive
            check = subprocess.run(
                ["kill", "-0", str(pid)], capture_output=True, text=True
            )
            if check.returncode != 0:
                return True, f"进程 {pid} 已终止 (SIGTERM)"

            # Force kill
            subprocess.run(["kill", "-KILL", str(pid)], capture_output=True, timeout=3)
            time.sleep(0.2)

            # Verify
            check = subprocess.run(
                ["kill", "-0", str(pid)], capture_output=True, text=True
            )
            if check.returncode != 0:
                return True, f"进程 {pid} 已强制终止 (SIGKILL)"
            else:
                return False, f"无法终止进程 {pid}"

        elif system == "Windows":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            if result.returncode == 0:
                return True, f"进程 {pid} 已终止"
            else:
                return False, f"无法终止进程 {pid}: {result.stderr}"

    except Exception as e:
        return False, f"终止进程时出错: {e}"

    return False, "不支持的操作系统"


@router.get("/config")
async def get_port_config() -> JSONResponse:
    """获取端口配置。"""
    config = _load_port_config()
    return JSONResponse(content=config.model_dump())


@router.post("/config")
async def update_port_config(config: PortConfig) -> JSONResponse:
    """
    更新端口配置。

    注意：更改将在下次重启服务时生效。
    """
    _save_port_config(config)
    return JSONResponse(
        content={
            "success": True,
            "config": config.model_dump(),
            "message": "配置已保存。更改将在下次重启服务时生效。",
        }
    )


@router.get("/status")
async def get_port_status() -> JSONResponse:
    """获取端口占用状态。"""
    config = _load_port_config()

    statuses: list[PortStatus] = []

    # Check FastAPI port
    fastapi_processes = _find_processes_on_port(config.fastapi_port)
    statuses.append(
        PortStatus(
            port=config.fastapi_port,
            port_type="FastAPI",
            in_use=len(fastapi_processes) > 0,
            processes=fastapi_processes,
        )
    )

    # Check Camoufox debug port
    camoufox_processes = _find_processes_on_port(config.camoufox_debug_port)
    statuses.append(
        PortStatus(
            port=config.camoufox_debug_port,
            port_type="Camoufox Debug",
            in_use=len(camoufox_processes) > 0,
            processes=camoufox_processes,
        )
    )

    # Check Stream proxy port (if enabled)
    if config.stream_proxy_enabled and config.stream_proxy_port > 0:
        stream_processes = _find_processes_on_port(config.stream_proxy_port)
        statuses.append(
            PortStatus(
                port=config.stream_proxy_port,
                port_type="Stream Proxy",
                in_use=len(stream_processes) > 0,
                processes=stream_processes,
            )
        )

    return JSONResponse(content={"ports": [s.model_dump() for s in statuses]})


@router.post("/kill")
async def kill_process(request: KillRequest) -> JSONResponse:
    """
    终止指定PID的进程。

    安全性验证：
    - 需要 confirm=true 确认操作
    - PID必须属于配置的端口上的进程

    Args:
        request: 包含 PID 和确认标志的请求

    Raises:
        HTTPException 400: 未确认操作
        HTTPException 403: PID不属于跟踪的端口
    """
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="请设置 confirm=true 确认终止进程",
        )

    # Security: Validate PID belongs to a tracked port
    config = _load_port_config()
    tracked_pids: set[int] = set()

    # Collect PIDs from all configured ports
    for port in [config.fastapi_port, config.camoufox_debug_port]:
        for proc in _find_processes_on_port(port):
            tracked_pids.add(proc.pid)

    # Also check stream proxy port if enabled
    if config.stream_proxy_enabled and config.stream_proxy_port > 0:
        for proc in _find_processes_on_port(config.stream_proxy_port):
            tracked_pids.add(proc.pid)

    if request.pid not in tracked_pids:
        raise HTTPException(
            status_code=403,
            detail=f"安全验证失败：PID {request.pid} 不属于配置的端口。只能终止在 FastAPI ({config.fastapi_port})、Camoufox ({config.camoufox_debug_port}) 或 Stream Proxy ({config.stream_proxy_port}) 端口上运行的进程。",
        )

    success, message = _kill_process(request.pid)

    return JSONResponse(
        content={"success": success, "message": message, "pid": request.pid},
        status_code=200 if success else 500,
    )
