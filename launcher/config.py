import argparse
import os
import sys
from typing import Dict, Optional

from launcher.utils import get_proxy_from_gsettings

# --- 配置常量 ---
PYTHON_EXECUTABLE = sys.executable
ENDPOINT_CAPTURE_TIMEOUT = int(
    os.environ.get("ENDPOINT_CAPTURE_TIMEOUT", "45")
)  # 秒 (from dev)
DEFAULT_SERVER_PORT = int(
    os.environ.get("DEFAULT_FASTAPI_PORT", "2048")
)  # FastAPI 服务器端口
DEFAULT_CAMOUFOX_PORT = int(
    os.environ.get("DEFAULT_CAMOUFOX_PORT", "9222")
)  # Camoufox 调试端口 (如果内部启动需要)
DEFAULT_STREAM_PORT = int(os.environ.get("STREAM_PORT", "3120"))  # 流式代理服务器端口
DEFAULT_HELPER_ENDPOINT = os.environ.get(
    "GUI_DEFAULT_HELPER_ENDPOINT", ""
)  # 外部 Helper 端点
DEFAULT_AUTH_SAVE_TIMEOUT = int(
    os.environ.get("AUTH_SAVE_TIMEOUT", "30")
)  # 认证保存超时时间
DEFAULT_SERVER_LOG_LEVEL = os.environ.get("SERVER_LOG_LEVEL", "INFO")  # 服务器日志级别
AUTH_PROFILES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "auth_profiles"
)
ACTIVE_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "active")
SAVED_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "saved")
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LAUNCHER_LOG_FILE_PATH = os.path.join(LOG_DIR, "launch_app.log")
DIRECT_LAUNCH = os.environ.get("DIRECT_LAUNCH", False)

# --- WebSocket 端点正则表达式 ---
import re

ws_regex = re.compile(r"(ws://\S+)")


def determine_proxy_configuration(
    internal_camoufox_proxy_arg: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    统一的代理配置确定函数
    按优先级顺序：命令行参数 > 环境变量 > 系统设置

    Args:
        internal_camoufox_proxy_arg: --internal-camoufox-proxy 命令行参数值

    Returns:
        dict: 包含代理配置信息的字典
        {
            'camoufox_proxy': str or None,  # Camoufox浏览器使用的代理
            'stream_proxy': str or None,    # 流式代理服务使用的上游代理
            'source': str                   # 代理来源说明
        }
    """
    result = {"camoufox_proxy": None, "stream_proxy": None, "source": "无代理"}

    # 1. 优先使用命令行参数
    if internal_camoufox_proxy_arg is not None:
        if internal_camoufox_proxy_arg.strip():  # 非空字符串
            result["camoufox_proxy"] = internal_camoufox_proxy_arg.strip()
            result["stream_proxy"] = internal_camoufox_proxy_arg.strip()
            result["source"] = (
                f"命令行参数 --internal-camoufox-proxy: {internal_camoufox_proxy_arg.strip()}"
            )
        else:  # 空字符串，明确禁用代理
            result["source"] = "命令行参数 --internal-camoufox-proxy='' (明确禁用代理)"
        return result

    # 2. 尝试环境变量 UNIFIED_PROXY_CONFIG (优先级高于 HTTP_PROXY/HTTPS_PROXY)
    unified_proxy = os.environ.get("UNIFIED_PROXY_CONFIG")
    if unified_proxy:
        result["camoufox_proxy"] = unified_proxy
        result["stream_proxy"] = unified_proxy
        result["source"] = f"环境变量 UNIFIED_PROXY_CONFIG: {unified_proxy}"
        return result

    # 3. 尝试环境变量 HTTP_PROXY
    http_proxy = os.environ.get("HTTP_PROXY")
    if http_proxy:
        result["camoufox_proxy"] = http_proxy
        result["stream_proxy"] = http_proxy
        result["source"] = f"环境变量 HTTP_PROXY: {http_proxy}"
        return result

    # 4. 尝试环境变量 HTTPS_PROXY
    https_proxy = os.environ.get("HTTPS_PROXY")
    if https_proxy:
        result["camoufox_proxy"] = https_proxy
        result["stream_proxy"] = https_proxy
        result["source"] = f"环境变量 HTTPS_PROXY: {https_proxy}"
        return result

    # 5. 尝试系统代理设置 (仅限 Linux)
    if sys.platform.startswith("linux"):
        gsettings_proxy = get_proxy_from_gsettings()
        if gsettings_proxy:
            result["camoufox_proxy"] = gsettings_proxy
            result["stream_proxy"] = gsettings_proxy
            result["source"] = f"gsettings 系统代理: {gsettings_proxy}"
            return result

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Camoufox 浏览器模拟与 FastAPI 代理服务器的启动器。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # 内部参数 (from dev)
    parser.add_argument(
        "--internal-launch-mode",
        type=str,
        choices=["debug", "headless", "virtual_headless"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--internal-auth-file", type=str, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--internal-camoufox-port",
        type=int,
        default=DEFAULT_CAMOUFOX_PORT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--internal-camoufox-proxy", type=str, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--internal-camoufox-os", type=str, default="random", help=argparse.SUPPRESS
    )

    # 用户可见参数 (merged from dev and helper)
    parser.add_argument(
        "--server-port",
        type=int,
        default=DEFAULT_SERVER_PORT,
        help=f"FastAPI 服务器监听的端口号 (默认: {DEFAULT_SERVER_PORT})",
    )
    parser.add_argument(
        "--stream-port",
        type=int,
        default=DEFAULT_STREAM_PORT,  # 从 .env 文件读取默认值
        help=(
            f"流式代理服务器使用端口"
            f"提供来禁用此功能 --stream-port=0 . 默认: {DEFAULT_STREAM_PORT}"
        ),
    )
    parser.add_argument(
        "--helper",
        type=str,
        default=DEFAULT_HELPER_ENDPOINT,  # 使用默认值
        help=(
            f"Helper 服务器的 getStreamResponse 端点地址 (例如: http://127.0.0.1:3121/getStreamResponse). "
            f"提供空字符串 (例如: --helper='') 来禁用此功能. 默认: {DEFAULT_HELPER_ENDPOINT}"
        ),
    )
    parser.add_argument(
        "--camoufox-debug-port",  # from dev
        type=int,
        default=DEFAULT_CAMOUFOX_PORT,
        help=f"内部 Camoufox 实例监听的调试端口号 (默认: {DEFAULT_CAMOUFOX_PORT})",
    )
    mode_selection_group = (
        parser.add_mutually_exclusive_group()
    )  # from dev (more options)
    mode_selection_group.add_argument(
        "--debug",
        action="store_true",
        help="启动调试模式 (浏览器界面可见，允许交互式认证)",
    )
    mode_selection_group.add_argument(
        "--headless",
        action="store_true",
        help="启动无头模式 (浏览器无界面，需要预先保存的认证文件)",
    )
    mode_selection_group.add_argument(
        "--virtual-display",
        action="store_true",
        help="启动无头模式并使用虚拟显示 (Xvfb, 仅限 Linux)",
    )  # from dev

    # --camoufox-os 参数已移除，将由脚本内部自动检测系统并设置
    parser.add_argument(  # from dev
        "--active-auth-json",
        type=str,
        default=None,
        help="[无头模式/调试模式可选] 指定要使用的活动认证JSON文件的路径 (在 auth_profiles/active/ 或 auth_profiles/saved/ 中，或绝对路径)。"
        "如果未提供，无头模式将使用 active/ 目录中最新的JSON文件，调试模式将提示选择或不使用。",
    )
    parser.add_argument(  # from dev
        "--auto-save-auth",
        action="store_true",
        help="[调试模式] 在登录成功后，如果之前未加载认证文件，则自动提示并保存新的认证状态。",
    )
    parser.add_argument(
        "--save-auth-as",
        type=str,
        default=None,
        help="[调试模式] 指定保存新认证文件的文件名 (不含.json后缀)。",
    )
    parser.add_argument(  # from dev
        "--auth-save-timeout",
        type=int,
        default=DEFAULT_AUTH_SAVE_TIMEOUT,
        help=f"[调试模式] 自动保存认证或输入认证文件名的等待超时时间 (秒)。默认: {DEFAULT_AUTH_SAVE_TIMEOUT}",
    )
    parser.add_argument(
        "--exit-on-auth-save",
        action="store_true",
        help="[调试模式] 在通过UI成功保存新的认证文件后，自动关闭启动器和所有相关进程。",
    )
    # 日志相关参数 (from dev)
    parser.add_argument(
        "--server-log-level",
        type=str,
        default=DEFAULT_SERVER_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"server.py 的日志级别。默认: {DEFAULT_SERVER_LOG_LEVEL}",
    )
    parser.add_argument(
        "--server-redirect-print",
        action="store_true",
        help="将 server.py 中的 print 输出重定向到其日志系统。默认不重定向以便调试模式下的 input() 提示可见。",
    )
    parser.add_argument(
        "--debug-logs",
        action="store_true",
        help="启用 server.py 内部的 DEBUG 级别详细日志 (环境变量 DEBUG_LOGS_ENABLED)。",
    )
    parser.add_argument(
        "--trace-logs",
        action="store_true",
        help="启用 server.py 内部的 TRACE 级别更详细日志 (环境变量 TRACE_LOGS_ENABLED)。",
    )

    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="跳过前端资源构建检查 (适用于没有 Node.js/npm 的环境，或使用预构建资源)。",
    )

    return parser.parse_args()
