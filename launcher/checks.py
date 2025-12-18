import logging
import os
import sys
from typing import Dict, List, Optional

from launcher.config import ACTIVE_AUTH_DIR, SAVED_AUTH_DIR

logger = logging.getLogger("CamoufoxLauncher")


def ensure_auth_dirs_exist() -> None:
    try:
        os.makedirs(ACTIVE_AUTH_DIR, exist_ok=True)
        logger.debug(f"活动认证目录就绪: {ACTIVE_AUTH_DIR}")
        os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
        logger.debug(f"已保存认证目录就绪: {SAVED_AUTH_DIR}")
    except Exception as e:
        logger.error(f"创建认证目录失败: {e}", exc_info=True)
        sys.exit(1)


def check_dependencies(
    launch_server: Optional[bool], DefaultAddons: Optional[bool]
) -> None:
    logger.debug("[Init] 步骤 1: 检查依赖项...")
    required_modules: Dict[str, str] = {}
    if launch_server is not None and DefaultAddons is not None:
        required_modules["camoufox"] = "camoufox (for server and addons)"
    elif launch_server is not None:
        required_modules["camoufox_server"] = "camoufox.server"
        logger.warning(
            "  'camoufox.server' 已导入，但 'camoufox.DefaultAddons' 未导入。排除插件功能可能受限。"
        )
    missing_py_modules: List[str] = []
    dependencies_ok = True
    if required_modules:
        for module_name, install_package_name in required_modules.items():
            try:
                __import__(module_name)
                logger.debug(f"模块 '{module_name}' 已找到。")
            except ImportError:
                logger.error(
                    f"  模块 '{module_name}' (包: '{install_package_name}') 未找到。"
                )
                missing_py_modules.append(install_package_name)
                dependencies_ok = False
    else:
        # 检查是否是内部启动模式，如果是，则 camoufox 必须可导入
        is_any_internal_arg = any(arg.startswith("--internal-") for arg in sys.argv)
        if is_any_internal_arg and (launch_server is None or DefaultAddons is None):
            logger.error(
                "  内部启动模式 (--internal-*) 需要 'camoufox' 包，但未能导入。"
            )
            dependencies_ok = False
        elif not is_any_internal_arg:
            logger.debug(
                "未请求内部启动模式，且未导入 camoufox.server，跳过对 'camoufox' Python 包的检查。"
            )

    try:
        from server import app as server_app_check

        if server_app_check:
            logger.debug("[Init] 成功从 server.py 导入 app 对象")
    except ImportError as e_import_server:
        logger.error(
            f"  无法从 'server.py' 导入 'app' 对象: {e_import_server}", exc_info=True
        )
        logger.error("请确保 'server.py' 文件存在且没有导入错误。")
        dependencies_ok = False

    if not dependencies_ok:
        logger.error("-------------------------------------------------")
        logger.error("依赖项检查失败！")
        if missing_py_modules:
            logger.error(f"缺少的 Python 库: {', '.join(missing_py_modules)}")
            logger.error(
                f"   请尝试使用 pip 安装: pip install {' '.join(missing_py_modules)}"
            )
        logger.error("-------------------------------------------------")
        sys.exit(1)
    else:
        logger.debug("[Init] 所有依赖项检查通过")
