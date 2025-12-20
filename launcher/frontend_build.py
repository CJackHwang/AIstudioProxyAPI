"""
Frontend build utilities for the launcher.

Provides automatic detection and rebuild of stale frontend assets.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("CamoufoxLauncher")

# Paths relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "static" / "frontend"
_FRONTEND_SRC = _FRONTEND_DIR / "src"
_FRONTEND_DIST = _FRONTEND_DIR / "dist"


def _get_latest_mtime(
    directory: Path, extensions: tuple[str, ...] = (".ts", ".tsx", ".css")
) -> float:
    """Get the latest modification time of source files in a directory."""
    latest_mtime = 0.0
    if not directory.exists():
        return latest_mtime

    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix in extensions:
            try:
                mtime = file_path.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
            except OSError:
                pass
    return latest_mtime


def _get_dist_mtime() -> float:
    """Get the modification time of the dist/index.html."""
    index_html = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        try:
            return index_html.stat().st_mtime
        except OSError:
            pass
    return 0.0


def is_frontend_stale() -> bool:
    """检查前端是否需要重新构建。"""
    if not _FRONTEND_DIST.exists():
        return True

    src_mtime = _get_latest_mtime(_FRONTEND_SRC)
    dist_mtime = _get_dist_mtime()

    if src_mtime == 0.0:
        # No source files found, don't rebuild
        return False

    return src_mtime > dist_mtime


def check_npm_available() -> bool:
    """检查 npm 是否可用。"""
    return shutil.which("npm") is not None


def rebuild_frontend() -> bool:
    """
    重新构建前端。

    Returns:
        True if build succeeded, False otherwise.
    """
    if not _FRONTEND_DIR.exists():
        logger.warning(f"前端目录不存在: {_FRONTEND_DIR}")
        return False

    if not check_npm_available():
        logger.warning("npm 未安装，跳过前端重建")
        return False

    # Check if node_modules exists
    if not (_FRONTEND_DIR / "node_modules").exists():
        logger.info("[Build] 正在安装前端依赖...")
        try:
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(_FRONTEND_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.error(f"npm install 失败: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("npm install 超时")
            return False
        except Exception as e:
            logger.error(f"npm install 出错: {e}")
            return False

    logger.info("[Build] 正在构建前端...")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(_FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("[Build] 前端构建成功")
            return True
        else:
            # TypeScript errors go to stdout, other errors to stderr
            error_output = result.stdout.strip() or result.stderr.strip()
            if error_output:
                # Truncate long error messages for readability
                if len(error_output) > 500:
                    error_output = error_output[:500] + "\n... (truncated)"
                logger.error(f"前端构建失败:\n{error_output}")
            else:
                logger.error(f"前端构建失败 (exit code: {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        logger.error("前端构建超时")
        return False
    except Exception as e:
        logger.error(f"前端构建出错: {e}")
        return False


def ensure_frontend_built(skip_build: bool = False) -> None:
    """
    确保前端已构建且为最新。

    如果源文件比 dist 更新，则自动重建。

    Args:
        skip_build: 如果为 True，跳过所有构建检查。
                   也可以通过设置环境变量 SKIP_FRONTEND_BUILD=1 来跳过。
    """
    import os

    # Check for skip flag from argument or environment
    if skip_build or os.environ.get("SKIP_FRONTEND_BUILD", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("[Build] 跳过前端构建检查 (SKIP_FRONTEND_BUILD)")
        return

    if not _FRONTEND_SRC.exists():
        logger.debug("[Build] 未找到前端源目录，跳过构建检查")
        return

    if is_frontend_stale():
        logger.info("[Build] 检测到前端源文件更新，正在重建...")
        rebuild_frontend()
    else:
        logger.info("[Build] 前端已是最新")
