"""
Proxy Configuration API Router

Endpoints for managing browser proxy settings and testing connectivity.
"""

import socket
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/proxy", tags=["proxy"])

# Config file path (same location as gui_config.json in deprecated GUI)
_CONFIG_DIR = Path(__file__).parent.parent.parent
_PROXY_CONFIG_FILE = _CONFIG_DIR / "proxy_config.json"


class ProxyConfig(BaseModel):
    """Proxy configuration model."""

    enabled: bool = False
    address: str = "http://127.0.0.1:7890"

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate proxy address format."""
        v = v.strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("代理地址必须以 http:// 或 https:// 开头")
        return v


class ProxyTestRequest(BaseModel):
    """Request model for proxy test."""

    address: str = Field(..., description="代理地址")
    test_url: str = Field(default="http://httpbin.org/get", description="测试目标URL")


class ProxyTestResult(BaseModel):
    """Result of proxy connectivity test."""

    success: bool
    message: str
    latency_ms: Optional[float] = None


def _load_config() -> ProxyConfig:
    """Load proxy config from file."""
    import json

    if _PROXY_CONFIG_FILE.exists():
        try:
            data = json.loads(_PROXY_CONFIG_FILE.read_text(encoding="utf-8"))
            return ProxyConfig(**data)
        except Exception:
            pass
    return ProxyConfig()


def _save_config(config: ProxyConfig) -> None:
    """Save proxy config to file."""
    import json

    _PROXY_CONFIG_FILE.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@router.get("/config")
async def get_proxy_config() -> JSONResponse:
    """获取当前代理配置。"""
    config = _load_config()
    return JSONResponse(content=config.model_dump())


@router.post("/config")
async def update_proxy_config(config: ProxyConfig) -> JSONResponse:
    """更新代理配置。"""
    _save_config(config)
    return JSONResponse(content={"success": True, "config": config.model_dump()})


@router.post("/test")
async def test_proxy_connectivity(request: ProxyTestRequest) -> JSONResponse:
    """测试代理连接性。"""
    import time

    import httpx

    proxy_addr = request.address.strip()
    test_url = request.test_url

    if not proxy_addr:
        return JSONResponse(
            content=ProxyTestResult(
                success=False, message="代理地址不能为空"
            ).model_dump(),
            status_code=400,
        )

    try:
        start_time = time.monotonic()
        async with httpx.AsyncClient(
            proxy=proxy_addr,
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(test_url)
            latency = (time.monotonic() - start_time) * 1000

            if 200 <= response.status_code < 300:
                return JSONResponse(
                    content=ProxyTestResult(
                        success=True,
                        message=f"连接成功 (HTTP {response.status_code})",
                        latency_ms=round(latency, 2),
                    ).model_dump()
                )
            else:
                return JSONResponse(
                    content=ProxyTestResult(
                        success=False,
                        message=f"HTTP 错误: {response.status_code}",
                        latency_ms=round(latency, 2),
                    ).model_dump()
                )

    except httpx.ProxyError as e:
        return JSONResponse(
            content=ProxyTestResult(
                success=False, message=f"代理错误: {e}"
            ).model_dump()
        )
    except httpx.ConnectTimeout:
        return JSONResponse(
            content=ProxyTestResult(success=False, message="连接超时").model_dump()
        )
    except httpx.ReadTimeout:
        return JSONResponse(
            content=ProxyTestResult(success=False, message="读取超时").model_dump()
        )
    except socket.gaierror as e:
        return JSONResponse(
            content=ProxyTestResult(
                success=False, message=f"DNS 解析失败: {e}"
            ).model_dump()
        )
    except Exception as e:
        return JSONResponse(
            content=ProxyTestResult(
                success=False, message=f"未知错误: {e}"
            ).model_dump()
        )
