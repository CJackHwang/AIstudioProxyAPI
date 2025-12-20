"""
Authentication Files API Router

Endpoints for managing authentication profile files.
"""

import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import ACTIVE_AUTH_DIR, SAVED_AUTH_DIR

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthFileInfo(BaseModel):
    """Information about an auth file."""

    name: str
    path: str
    size_bytes: int
    is_active: bool = False


class ActivateRequest(BaseModel):
    """Request to activate an auth file."""

    filename: str = Field(..., description="要激活的认证文件名")


class AuthFilesResponse(BaseModel):
    """Response containing list of auth files."""

    saved_files: list[AuthFileInfo]
    active_file: Optional[str] = None


def _ensure_dirs() -> None:
    """Ensure auth directories exist."""
    Path(ACTIVE_AUTH_DIR).mkdir(parents=True, exist_ok=True)
    Path(SAVED_AUTH_DIR).mkdir(parents=True, exist_ok=True)


def _get_active_file() -> Optional[str]:
    """Get the currently active auth file name."""
    active_dir = Path(ACTIVE_AUTH_DIR)
    if not active_dir.exists():
        return None
    json_files = list(active_dir.glob("*.json"))
    if json_files:
        return sorted(json_files)[0].name
    return None


def _list_saved_files() -> list[AuthFileInfo]:
    """List all saved auth files."""
    saved_dir = Path(SAVED_AUTH_DIR)
    active_file = _get_active_file()
    files: list[AuthFileInfo] = []

    if saved_dir.exists():
        for f in sorted(saved_dir.glob("*.json")):
            files.append(
                AuthFileInfo(
                    name=f.name,
                    path=str(f),
                    size_bytes=f.stat().st_size,
                    is_active=(f.name == active_file),
                )
            )
    return files


@router.get("/files")
async def list_auth_files() -> JSONResponse:
    """列出所有保存的认证文件。"""
    _ensure_dirs()
    files = _list_saved_files()
    active = _get_active_file()
    return JSONResponse(
        content=AuthFilesResponse(
            saved_files=[f.model_dump() for f in files],  # type: ignore[misc]
            active_file=active,
        ).model_dump()
    )


@router.get("/active")
async def get_active_auth() -> JSONResponse:
    """获取当前激活的认证文件。"""
    _ensure_dirs()
    active = _get_active_file()
    return JSONResponse(content={"active_file": active})


@router.post("/activate")
async def activate_auth_file(request: ActivateRequest) -> JSONResponse:
    """激活指定的认证文件。"""
    _ensure_dirs()
    filename = request.filename

    # Find source file
    source_path: Optional[Path] = None
    for search_dir in [SAVED_AUTH_DIR, ACTIVE_AUTH_DIR]:
        candidate = Path(search_dir) / filename
        if candidate.exists() and candidate.is_file():
            source_path = candidate
            break

    if not source_path:
        raise HTTPException(status_code=404, detail=f"认证文件 '{filename}' 未找到")

    # Clear existing active files
    active_dir = Path(ACTIVE_AUTH_DIR)
    for existing in active_dir.glob("*.json"):
        existing.unlink()

    # Copy to active directory
    dest_path = active_dir / filename
    shutil.copy2(source_path, dest_path)

    return JSONResponse(
        content={
            "success": True,
            "message": f"认证文件 '{filename}' 已激活",
            "active_file": filename,
        }
    )


@router.delete("/deactivate")
async def deactivate_auth() -> JSONResponse:
    """移除当前激活的认证。"""
    _ensure_dirs()
    active_dir = Path(ACTIVE_AUTH_DIR)
    removed_count = 0

    for f in active_dir.glob("*.json"):
        f.unlink()
        removed_count += 1

    return JSONResponse(
        content={
            "success": True,
            "message": f"已移除 {removed_count} 个认证文件",
            "active_file": None,
        }
    )
