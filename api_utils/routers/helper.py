"""
Helper Configuration API Router

Manages the Helper endpoint configuration.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("CamoufoxLauncher")

router = APIRouter(prefix="/api/helper", tags=["helper"])

# Config file path
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_HELPER_CONFIG_FILE = _CONFIG_DIR / "helper_config.json"


class HelperConfig(BaseModel):
    """Helper configuration."""

    enabled: bool = False
    endpoint: str = Field(default="", description="Helper endpoint URL")
    sapisid: Optional[str] = Field(
        default=None, description="SAPISID value (auto-extracted)"
    )


def _load_config() -> HelperConfig:
    """Load helper configuration from file."""
    if _HELPER_CONFIG_FILE.exists():
        try:
            data = json.loads(_HELPER_CONFIG_FILE.read_text(encoding="utf-8"))
            return HelperConfig(**data)
        except Exception as e:
            logger.warning(f"[Helper] 加载配置失败: {e}")
    return HelperConfig()


def _save_config(config: HelperConfig) -> None:
    """Save helper configuration to file."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _HELPER_CONFIG_FILE.write_text(
            json.dumps(config.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"[Helper] 保存配置失败: {e}")


@router.get("/config")
async def get_helper_config() -> JSONResponse:
    """获取 Helper 配置。"""
    config = _load_config()
    return JSONResponse(content=config.model_dump())


@router.post("/config")
async def update_helper_config(config: HelperConfig) -> JSONResponse:
    """更新 Helper 配置。"""
    _save_config(config)
    logger.info(
        f"[Helper] 配置已更新: enabled={config.enabled}, endpoint={config.endpoint}"
    )

    return JSONResponse(
        content={
            "success": True,
            "message": "Helper 配置已保存",
            "config": config.model_dump(),
        }
    )
