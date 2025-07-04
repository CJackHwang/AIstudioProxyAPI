#!/usr/bin/env python3
# launch_camoufox.py
import sys
import subprocess
import time
import re
import os
import signal
import atexit
import argparse
import select
import traceback
import json
import threading
import queue
import logging
import logging.handlers
import socket
import platform
import shutil

# --- 新的导入 ---
from dotenv import load_dotenv

# 提前加载 .env 文件，以确保后续导入的模块能获取到正确的环境变量
load_dotenv()

import uvicorn
from server import app # 从 server.py 导入 FastAPI app 对象
# -----------------

# 尝试导入 launch_server (用于内部启动模式，模拟 Camoufox 行为)
try:
    from camoufox.server import launch_server
    from camoufox import DefaultAddons # 假设 DefaultAddons 包含 AntiFingerprint
except ImportError:
    if '--internal-launch' in sys.argv or any(arg.startswith('--internal-') for arg in sys.argv): # 更广泛地检查内部参数
        print("❌ 致命错误：内部启动模式需要 'camoufox.server.launch_server' 和 'camoufox.DefaultAddons' 但无法导入。", file=sys.stderr)
        print("   这通常意味着 'camoufox' 包未正确安装或不在 PYTHONPATH 中。", file=sys.stderr)
        sys.exit(1)
    else:
        launch_server = None
        DefaultAddons = None

# --- 配置常量 ---
PYTHON_EXECUTABLE = sys.executable
ENDPOINT_CAPTURE_TIMEOUT = int(os.environ.get('ENDPOINT_CAPTURE_TIMEOUT', '45'))  # 秒 (from dev)
DEFAULT_SERVER_PORT = int(os.environ.get('DEFAULT_FASTAPI_PORT', '2048'))  # FastAPI 服务器端口
DEFAULT_CAMOUFOX_PORT = int(os.environ.get('DEFAULT_CAMOUFOX_PORT', '9222'))  # Camoufox 调试端口 (如果内部启动需要)
DEFAULT_STREAM_PORT = int(os.environ.get('STREAM_PORT', '3120'))  # 流式代理服务器端口
DEFAULT_HELPER_ENDPOINT = os.environ.get('GUI_DEFAULT_HELPER_ENDPOINT', '')  # 外部 Helper 端点
DEFAULT_AUTH_SAVE_TIMEOUT = int(os.environ.get('AUTH_SAVE_TIMEOUT', '30'))  # 认证保存超时时间
DEFAULT_SERVER_LOG_LEVEL = os.environ.get('SERVER_LOG_LEVEL', 'INFO')  # 服务器日志级别
AUTH_PROFILES_DIR = os.path.join(os.path.dirname(__file__), "auth_profiles")
ACTIVE_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "active")
SAVED_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "saved")
HTTP_PROXY = os.environ.get('HTTP_PROXY', '')
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', '')
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LAUNCHER_LOG_FILE_PATH = os.path.join(LOG_DIR, 'launch_app.log')

# --- 全局进程句柄 ---
camoufox_proc = None

# --- 日志记录器实例 ---
logger = logging.getLogger("CamoufoxLauncher")

# --- WebSocket 端点正则表达式 ---
ws_regex = re.compile(r"(ws://\S+)")


# --- 线程安全的输出队列处理函数 (_enqueue_output) (from dev - more robust error handling) ---
def _enqueue_output(stream, stream_name, output_queue, process_pid_for_log="<未知PID>"):
    log_prefix = f"[读取线程-{stream_name}-PID:{process_pid_for_log}]"
    try:
        for line_bytes in iter(stream.readline, b''):
            if not line_bytes:
                break
            try:
                line_str = line_bytes.decode('utf-8', errors='replace')
                output_queue.put((stream_name, line_str))
            except Exception as decode_err:
                logger.warning(f"{log_prefix} 解码错误: {decode_err}。原始数据 (前100字节): {line_bytes[:100]}")
                output_queue.put((stream_name, f"[解码错误: {decode_err}] {line_bytes[:100]}...\n"))
    except ValueError:
        logger.debug(f"{log_prefix} ValueError (流可能已关闭)。")
    except Exception as e:
        logger.error(f"{log_prefix} 读取流时发生意外错误: {e}", exc_info=True)
    finally:
        output_queue.put((stream_name, None))
        if hasattr(stream, 'close') and not stream.closed:
            try:
                stream.close()
            except Exception:
                pass
        logger.debug(f"{log_prefix} 线程退出。")

# --- 设置本启动器脚本的日志系统 (setup_launcher_logging) (from dev - clears log on start) ---
def setup_launcher_logging(log_level=logging.INFO):
    os.makedirs(LOG_DIR, exist_ok=True)
    file_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s')
    console_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(log_level)
    logger.propagate = False
    if os.path.exists(LAUNCHER_LOG_FILE_PATH):
        try:
            os.remove(LAUNCHER_LOG_FILE_PATH)
        except OSError:
            pass
    file_handler = logging.handlers.RotatingFileHandler(
        LAUNCHER_LOG_FILE_PATH, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8', mode='w'
    )
    file_handler.setFormatter(file_log_formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(console_log_formatter)
    logger.addHandler(stream_handler)
    logger.info("=" * 30 + " Camoufox启动器日志系统已初始化 " + "=" * 30)
    logger.info(f"日志级别设置为: {logging.getLevelName(logger.getEffectiveLevel())}")
    logger.info(f"日志文件路径: {LAUNCHER_LOG_FILE_PATH}")

# --- 确保认证文件目录存在 (ensure_auth_dirs_exist) ---
def ensure_auth_dirs_exist():
    logger.info("正在检查并确保认证文件目录存在...")
    try:
        os.makedirs(ACTIVE_AUTH_DIR, exist_ok=True)
        logger.info(f"  ✓ 活动认证目录就绪: {ACTIVE_AUTH_DIR}")
        os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
        logger.info(f"  ✓ 已保存认证目录就绪: {SAVED_AUTH_DIR}")
    except Exception as e:
        logger.error(f"  ❌ 创建认证目录失败: {e}", exc_info=True)
        sys.exit(1)

# --- 清理函数 (在脚本退出时执行) (from dev - more detailed logging and checks) ---
def cleanup():
    global camoufox_proc
    logger.info("--- 开始执行清理程序 (launch_camoufox.py) ---")
    if camoufox_proc and camoufox_proc.poll() is None:
        pid = camoufox_proc.pid
        logger.info(f"正在终止 Camoufox 内部子进程 (PID: {pid})...")
        try:
            if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                try:
                    pgid = os.getpgid(pid)
                    logger.info(f"  向 Camoufox 进程组 (PGID: {pgid}) 发送 SIGTERM 信号...")
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    logger.info(f"  Camoufox 进程组 (PID: {pid}) 未找到，尝试直接终止进程...")
                    camoufox_proc.terminate()
            else:
                if sys.platform == "win32":
                    logger.info(f"进程树 (PID: {pid}) 发送终止请求")
                    subprocess.call(['taskkill', '/T', '/PID', str(pid)])
                else:
                    logger.info(f"  向 Camoufox (PID: {pid}) 发送 SIGTERM 信号...")
                    camoufox_proc.terminate()
            camoufox_proc.wait(timeout=5)
            logger.info(f"  ✓ Camoufox (PID: {pid}) 已通过 SIGTERM 成功终止。")
        except subprocess.TimeoutExpired:
            logger.warning(f"  ⚠️ Camoufox (PID: {pid}) SIGTERM 超时。正在发送 SIGKILL 强制终止...")
            if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                try:
                    pgid = os.getpgid(pid)
                    logger.info(f"  向 Camoufox 进程组 (PGID: {pgid}) 发送 SIGKILL 信号...")
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    logger.info(f"  Camoufox 进程组 (PID: {pid}) 在 SIGKILL 时未找到，尝试直接强制终止...")
                    camoufox_proc.kill()
            else:
                if sys.platform == "win32":
                    logger.info(f"  强制杀死 Camoufox 进程树 (PID: {pid})")
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
                else:
                    camoufox_proc.kill()
            try:
                camoufox_proc.wait(timeout=2)
                logger.info(f"  ✓ Camoufox (PID: {pid}) 已通过 SIGKILL 成功终止。")
            except Exception as e_kill:
                logger.error(f"  ❌ 等待 Camoufox (PID: {pid}) SIGKILL 完成时出错: {e_kill}")
        except Exception as e_term:
            logger.error(f"  ❌ 终止 Camoufox (PID: {pid}) 时发生错误: {e_term}", exc_info=True)
        finally:
            if hasattr(camoufox_proc, 'stdout') and camoufox_proc.stdout and not camoufox_proc.stdout.closed:
                camoufox_proc.stdout.close()
            if hasattr(camoufox_proc, 'stderr') and camoufox_proc.stderr and not camoufox_proc.stderr.closed:
                camoufox_proc.stderr.close()
        camoufox_proc = None
    elif camoufox_proc:
        logger.info(f"Camoufox 内部子进程 (PID: {camoufox_proc.pid if hasattr(camoufox_proc, 'pid') else 'N/A'}) 先前已自行结束，退出码: {camoufox_proc.poll()}。")
        camoufox_proc = None
    else:
        logger.info("Camoufox 内部子进程未运行或已清理。")
    logger.info("--- 清理程序执行完毕 (launch_camoufox.py) ---")

atexit.register(cleanup)
def signal_handler(sig, frame):
    logger.info(f"接收到信号 {signal.Signals(sig).name} ({sig})。正在启动退出程序...")
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- 检查依赖项 (check_dependencies) (from dev - more comprehensive) ---
def check_dependencies():
    logger.info("--- 步骤 1: 检查依赖项 ---")
    required_modules = {}
    if launch_server is not None and DefaultAddons is not None:
        required_modules["camoufox"] = "camoufox (for server and addons)"
    elif launch_server is not None:
        required_modules["camoufox_server"] = "camoufox.server"
        logger.warning("  ⚠️ 'camoufox.server' 已导入，但 'camoufox.DefaultAddons' 未导入。排除插件功能可能受限。")
    missing_py_modules = []
    dependencies_ok = True
    if required_modules:
        logger.info("正在检查 Python 模块:")
        for module_name, install_package_name in required_modules.items():
            try:
                __import__(module_name)
                logger.info(f"  ✓ 模块 '{module_name}' 已找到。")
            except ImportError:
                logger.error(f"  ❌ 模块 '{module_name}' (包: '{install_package_name}') 未找到。")
                missing_py_modules.append(install_package_name)
                dependencies_ok = False
    else:
        # 检查是否是内部启动模式，如果是，则 camoufox 必须可导入
        is_any_internal_arg = any(arg.startswith('--internal-') for arg in sys.argv)
        if is_any_internal_arg and (launch_server is None or DefaultAddons is None):
            logger.error(f"  ❌ 内部启动模式 (--internal-*) 需要 'camoufox' 包，但未能导入。")
            dependencies_ok = False
        elif not is_any_internal_arg:
             logger.info("未请求内部启动模式，且未导入 camoufox.server，跳过对 'camoufox' Python 包的检查。")


    try:
        from server import app as server_app_check
        if server_app_check:
             logger.info(f"  ✓ 成功从 'server.py' 导入 'app' 对象。")
    except ImportError as e_import_server:
        logger.error(f"  ❌ 无法从 'server.py' 导入 'app' 对象: {e_import_server}")
        logger.error(f"     请确保 'server.py' 文件存在且没有导入错误。")
        dependencies_ok = False

    if not dependencies_ok:
        logger.error("-------------------------------------------------")
        logger.error("❌ 依赖项检查失败！")
        if missing_py_modules:
            logger.error(f"   缺少的 Python 库: {', '.join(missing_py_modules)}")
            logger.error(f"   请尝试使用 pip 安装: pip install {' '.join(missing_py_modules)}")
        logger.error("-------------------------------------------------")
        sys.exit(1)
    else:
        logger.info("✅ 所有启动器依赖项检查通过。")

# --- 端口检查和清理函数 (from dev - more robust) ---
def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return False
        except OSError:
            return True
        except Exception as e:
            logger.warning(f"检查端口 {port} (主机 {host}) 时发生未知错误: {e}")
            return True

def find_pids_on_port(port: int) -> list[int]:
    pids = []
    system_platform = platform.system()
    command = ""
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            command = f"lsof -ti :{port} -sTCP:LISTEN"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode == 0 and stdout:
                pids = [int(pid) for pid in stdout.strip().split('\n') if pid.isdigit()]
            elif process.returncode != 0 and ("command not found" in stderr.lower() or "未找到命令" in stderr):
                logger.error(f"命令 'lsof' 未找到。请确保已安装。")
            elif process.returncode not in [0, 1]: # lsof 在未找到时返回1
                logger.warning(f"执行 lsof 命令失败 (返回码 {process.returncode}): {stderr.strip()}")
        elif system_platform == "Windows":
            command = f'netstat -ano -p TCP | findstr "LISTENING" | findstr ":{port} "'
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode == 0 and stdout:
                for line in stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 4 and parts[0].upper() == 'TCP' and f":{port}" in parts[1]:
                        if parts[-1].isdigit(): pids.append(int(parts[-1]))
                pids = list(set(pids)) # 去重
            elif process.returncode not in [0, 1]: # findstr 在未找到时返回1
                logger.warning(f"执行 netstat/findstr 命令失败 (返回码 {process.returncode}): {stderr.strip()}")
        else:
            logger.warning(f"不支持的操作系统 '{system_platform}' 用于查找占用端口的进程。")
    except FileNotFoundError:
        cmd_name = command.split()[0] if command else "相关工具"
        logger.error(f"命令 '{cmd_name}' 未找到。")
    except subprocess.TimeoutExpired:
        logger.error(f"执行命令 '{command}' 超时。")
    except Exception as e:
        logger.error(f"查找占用端口 {port} 的进程时出错: {e}", exc_info=True)
    return pids

def kill_process_interactive(pid: int) -> bool:
    system_platform = platform.system()
    success = False
    logger.info(f"  尝试终止进程 PID: {pid}...")
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            result_term = subprocess.run(f"kill {pid}", shell=True, capture_output=True, text=True, timeout=3, check=False)
            if result_term.returncode == 0:
                logger.info(f"    ✓ PID {pid} 已发送 SIGTERM 信号。")
                success = True
            else:
                logger.warning(f"    PID {pid} SIGTERM 失败: {result_term.stderr.strip() or result_term.stdout.strip()}. 尝试 SIGKILL...")
                result_kill = subprocess.run(f"kill -9 {pid}", shell=True, capture_output=True, text=True, timeout=3, check=False)
                if result_kill.returncode == 0:
                    logger.info(f"    ✓ PID {pid} 已发送 SIGKILL 信号。")
                    success = True
                else:
                    logger.error(f"    ✗ PID {pid} SIGKILL 失败: {result_kill.stderr.strip() or result_kill.stdout.strip()}.")
        elif system_platform == "Windows":
            command_desc = f"taskkill /PID {pid} /T /F"
            result = subprocess.run(command_desc, shell=True, capture_output=True, text=True, timeout=5, check=False)
            output = result.stdout.strip()
            error_output = result.stderr.strip()
            if result.returncode == 0 and ("SUCCESS" in output.upper() or "成功" in output):
                logger.info(f"    ✓ PID {pid} 已通过 taskkill /F 终止。")
                success = True
            elif "could not find process" in error_output.lower() or "找不到" in error_output: # 进程可能已自行退出
                logger.info(f"    PID {pid} 执行 taskkill 时未找到 (可能已退出)。")
                success = True # 视为成功，因为目标是端口可用
            else:
                logger.error(f"    ✗ PID {pid} taskkill /F 失败: {(error_output + ' ' + output).strip()}.")
        else:
            logger.warning(f"    不支持的操作系统 '{system_platform}' 用于终止进程。")
    except Exception as e:
        logger.error(f"    终止 PID {pid} 时发生意外错误: {e}", exc_info=True)
    return success

# --- 带超时的用户输入函数 (from dev - more robust Windows implementation) ---
def input_with_timeout(prompt_message: str, timeout_seconds: int = 30) -> str:
    print(prompt_message, end='', flush=True)
    if sys.platform == "win32":
        user_input_container = [None]
        def get_input_in_thread():
            try:
                user_input_container[0] = sys.stdin.readline().strip()
            except Exception:
                user_input_container[0] = "" # 出错时返回空字符串
        input_thread = threading.Thread(target=get_input_in_thread, daemon=True)
        input_thread.start()
        input_thread.join(timeout=timeout_seconds)
        if input_thread.is_alive():
            print("\n输入超时。将使用默认值。", flush=True)
            return ""
        return user_input_container[0] if user_input_container[0] is not None else ""
    else: # Linux/macOS
        readable_fds, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
        if readable_fds:
            return sys.stdin.readline().strip()
        else:
            print("\n输入超时。将使用默认值。", flush=True)
            return ""

def get_proxy_from_gsettings():
    """
    Retrieves the proxy settings from GSettings on Linux systems.
    Returns a proxy string like "http://host:port" or None.
    """
    def _run_gsettings_command(command_parts: list[str]) -> str | None:
        """Helper function to run gsettings command and return cleaned string output."""
        try:
            process_result = subprocess.run(
                command_parts,
                capture_output=True,
                text=True,
                check=False, # Do not raise CalledProcessError for non-zero exit codes
                timeout=1  # Timeout for the subprocess call
            )
            if process_result.returncode == 0:
                value = process_result.stdout.strip()
                if value.startswith("'") and value.endswith("'"): # Remove surrounding single quotes
                    value = value[1:-1]
                
                # If after stripping quotes, value is empty, or it's a gsettings "empty" representation
                if not value or value == "''" or value == "@as []" or value == "[]":
                    return None
                return value
            else:
                return None
        except subprocess.TimeoutExpired:
            return None
        except Exception: # Broad exception as per pseudocode
            return None

    proxy_mode = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy", "mode"])

    if proxy_mode == "manual":
        # Try HTTP proxy first
        http_host = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.http", "host"])
        http_port_str = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.http", "port"])

        if http_host and http_port_str:
            try:
                http_port = int(http_port_str)
                if http_port > 0:
                    return f"http://{http_host}:{http_port}"
            except ValueError:
                pass  # Continue to HTTPS

        # Try HTTPS proxy if HTTP not found or invalid
        https_host = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.https", "host"])
        https_port_str = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.https", "port"])

        if https_host and https_port_str:
            try:
                https_port = int(https_port_str)
                if https_port > 0:
                    # Note: Even for HTTPS proxy settings, the scheme for Playwright/requests is usually http://
                    return f"http://{https_host}:{https_port}"
            except ValueError:
                pass
    
    return None


def determine_proxy_configuration(internal_camoufox_proxy_arg=None):
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
    result = {
        'camoufox_proxy': None,
        'stream_proxy': None,
        'source': '无代理'
    }

    # 1. 优先使用命令行参数
    if internal_camoufox_proxy_arg is not None:
        if internal_camoufox_proxy_arg.strip():  # 非空字符串
            result['camoufox_proxy'] = internal_camoufox_proxy_arg.strip()
            result['stream_proxy'] = internal_camoufox_proxy_arg.strip()
            result['source'] = f"命令行参数 --internal-camoufox-proxy: {internal_camoufox_proxy_arg.strip()}"
        else:  # 空字符串，明确禁用代理
            result['source'] = "命令行参数 --internal-camoufox-proxy='' (明确禁用代理)"
        return result

    # 2. 尝试环境变量 UNIFIED_PROXY_CONFIG (优先级高于 HTTP_PROXY/HTTPS_PROXY)
    unified_proxy = os.environ.get("UNIFIED_PROXY_CONFIG")
    if unified_proxy:
        result['camoufox_proxy'] = unified_proxy
        result['stream_proxy'] = unified_proxy
        result['source'] = f"环境变量 UNIFIED_PROXY_CONFIG: {unified_proxy}"
        return result

    # 3. 尝试环境变量 HTTP_PROXY
    http_proxy = os.environ.get("HTTP_PROXY")
    if http_proxy:
        result['camoufox_proxy'] = http_proxy
        result['stream_proxy'] = http_proxy
        result['source'] = f"环境变量 HTTP_PROXY: {http_proxy}"
        return result

    # 4. 尝试环境变量 HTTPS_PROXY
    https_proxy = os.environ.get("HTTPS_PROXY")
    if https_proxy:
        result['camoufox_proxy'] = https_proxy
        result['stream_proxy'] = https_proxy
        result['source'] = f"环境变量 HTTPS_PROXY: {https_proxy}"
        return result

    # 5. 尝试系统代理设置 (仅限 Linux)
    if sys.platform.startswith('linux'):
        gsettings_proxy = get_proxy_from_gsettings()
        if gsettings_proxy:
            result['camoufox_proxy'] = gsettings_proxy
            result['stream_proxy'] = gsettings_proxy
            result['source'] = f"gsettings 系统代理: {gsettings_proxy}"
            return result

    return result


# --- 主执行逻辑 ---
if __name__ == "__main__":
    # 检查是否是内部启动调用，如果是，则不配置 launcher 的日志
    is_internal_call = any(arg.startswith('--internal-') for arg in sys.argv)
    if not is_internal_call:
        setup_launcher_logging(log_level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Camoufox 浏览器模拟与 FastAPI 代理服务器的启动器。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # 内部参数 (from dev)
    parser.add_argument('--internal-launch-mode', type=str, choices=['debug', 'headless', 'virtual_headless'], help=argparse.SUPPRESS)
    parser.add_argument('--internal-auth-file', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-port', type=int, default=DEFAULT_CAMOUFOX_PORT, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-proxy', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-os', type=str, default="random", help=argparse.SUPPRESS)


    # 用户可见参数 (merged from dev and helper)
    parser.add_argument("--server-port", type=int, default=DEFAULT_SERVER_PORT, help=f"FastAPI 服务器监听的端口号 (默认: {DEFAULT_SERVER_PORT})")
    parser.add_argument(
        "--stream-port",
        type=int,
        default=DEFAULT_STREAM_PORT, # 从 .env 文件读取默认值
        help=(
            f"流式代理服务器使用端口"
            f"提供来禁用此功能 --stream-port=0 . 默认: {DEFAULT_STREAM_PORT}"
        )
    )
    parser.add_argument(
        "--helper",
        type=str,
        default=DEFAULT_HELPER_ENDPOINT, # 使用默认值
        help=(
            f"Helper 服务器的 getStreamResponse 端点地址 (例如: http://127.0.0.1:3121/getStreamResponse). "
            f"提供空字符串 (例如: --helper='') 来禁用此功能. 默认: {DEFAULT_HELPER_ENDPOINT}"
        )
    )
    parser.add_argument(
        "--camoufox-debug-port", # from dev
        type=int,
        default=DEFAULT_CAMOUFOX_PORT,
        help=f"内部 Camoufox 实例监听的调试端口号 (默认: {DEFAULT_CAMOUFOX_PORT})"
    )
    mode_selection_group = parser.add_mutually_exclusive_group() # from dev (more options)
    mode_selection_group.add_argument("--debug", action="store_true", help="启动调试模式 (浏览器界面可见，允许交互式认证)")
    mode_selection_group.add_argument("--headless", action="store_true", help="启动无头模式 (浏览器无界面，需要预先保存的认证文件)")
    mode_selection_group.add_argument("--virtual-display", action="store_true", help="启动无头模式并使用虚拟显示 (Xvfb, 仅限 Linux)") # from dev
    
    # --camoufox-os 参数已移除，将由脚本内部自动检测系统并设置
    parser.add_argument( # from dev
        "--active-auth-json", type=str, default=None,
        help="[无头模式/调试模式可选] 指定要使用的活动认证JSON文件的路径 (在 auth_profiles/active/ 或 auth_profiles/saved/ 中，或绝对路径)。"
             "如果未提供，无头模式将使用 active/ 目录中最新的JSON文件，调试模式将提示选择或不使用。"
    )
    parser.add_argument( # from dev
        "--auto-save-auth", action='store_true',
        help="[调试模式] 在登录成功后，如果之前未加载认证文件，则自动提示并保存新的认证状态。"
    )
    parser.add_argument( # from dev
        "--auth-save-timeout", type=int, default=DEFAULT_AUTH_SAVE_TIMEOUT,
        help=f"[调试模式] 自动保存认证或输入认证文件名的等待超时时间 (秒)。默认: {DEFAULT_AUTH_SAVE_TIMEOUT}"
    )
    # 日志相关参数 (from dev)
    parser.add_argument(
        "--server-log-level", type=str, default=DEFAULT_SERVER_LOG_LEVEL, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"server.py 的日志级别。默认: {DEFAULT_SERVER_LOG_LEVEL}"
    )
    parser.add_argument(
        "--server-redirect-print", action='store_true',
        help="将 server.py 中的 print 输出重定向到其日志系统。默认不重定向以便调试模式下的 input() 提示可见。"
    )
    parser.add_argument("--debug-logs", action='store_true', help="启用 server.py 内部的 DEBUG 级别详细日志 (环境变量 DEBUG_LOGS_ENABLED)。")
    parser.add_argument("--trace-logs", action='store_true', help="启用 server.py 内部的 TRACE 级别更详细日志 (环境变量 TRACE_LOGS_ENABLED)。")

    args = parser.parse_args()

    # --- 自动检测当前系统并设置 Camoufox OS 模拟 ---
    # 这个变量将用于后续的 Camoufox 内部启动和 HOST_OS_FOR_SHORTCUT 设置
    current_system_for_camoufox = platform.system()
    if current_system_for_camoufox == "Linux":
        simulated_os_for_camoufox = "linux"
    elif current_system_for_camoufox == "Windows":
        simulated_os_for_camoufox = "windows"
    elif current_system_for_camoufox == "Darwin": # macOS
        simulated_os_for_camoufox = "macos"
    else:
        simulated_os_for_camoufox = "linux" # 未知系统的默认回退值
        logger.warning(f"无法识别当前系统 '{current_system_for_camoufox}'。Camoufox OS 模拟将默认设置为: {simulated_os_for_camoufox}")
    logger.info(f"根据当前系统 '{current_system_for_camoufox}'，Camoufox OS 模拟已自动设置为: {simulated_os_for_camoufox}")

    # --- 处理内部 Camoufox 启动逻辑 (如果脚本被自身作为子进程调用) (from dev) ---
    if args.internal_launch_mode:
        if not launch_server or not DefaultAddons:
            print("❌ 致命错误 (--internal-launch-mode): camoufox.server.launch_server 或 camoufox.DefaultAddons 不可用。脚本无法继续。", file=sys.stderr)
            sys.exit(1)

        internal_mode_arg = args.internal_launch_mode
        auth_file = args.internal_auth_file
        camoufox_port_internal = args.internal_camoufox_port
        # 使用统一的代理配置确定逻辑
        proxy_config = determine_proxy_configuration(args.internal_camoufox_proxy)
        actual_proxy_to_use = proxy_config['camoufox_proxy']
        print(f"--- [内部Camoufox启动] 代理配置: {proxy_config['source']} ---", flush=True)
        
        camoufox_proxy_internal = actual_proxy_to_use # 更新此变量以供后续使用
        camoufox_os_internal = args.internal_camoufox_os


        print(f"--- [内部Camoufox启动] 模式: {internal_mode_arg}, 认证文件: {os.path.basename(auth_file) if auth_file else '无'}, "
              f"Camoufox端口: {camoufox_port_internal}, 代理: {camoufox_proxy_internal or '无'}, 模拟OS: {camoufox_os_internal} ---", flush=True)
        print(f"--- [内部Camoufox启动] 正在调用 camoufox.server.launch_server ... ---", flush=True)
        
        try:
            launch_args_for_internal_camoufox = {
                "port": camoufox_port_internal,
                "addons": [],
                # "proxy": camoufox_proxy_internal, # 已移除
                "exclude_addons": [DefaultAddons.UBO], # Assuming DefaultAddons.UBO exists
            }

            # 无头模式修复：设置固定屏幕配置解决 browserforge 兼容性问题
            if internal_mode_arg in ['headless', 'virtual_headless']:
                try:
                    from browserforge.fingerprints import Screen
                    launch_args_for_internal_camoufox["screen"] = Screen(
                        max_width=1920, min_width=1920,
                        max_height=1080, min_height=1080
                    )
                    print(f"--- [内部Camoufox启动] ✅ 设置固定屏幕配置: 1920x1080 ---", flush=True)
                except Exception as screen_err:
                    print(f"--- [内部Camoufox启动] ⚠️  设置屏幕配置失败: {screen_err} ---", flush=True)

            # 正确添加代理的方式
            if camoufox_proxy_internal: # 如果代理字符串存在且不为空
                launch_args_for_internal_camoufox["proxy"] = {"server": camoufox_proxy_internal}
            # 如果 camoufox_proxy_internal 是 None 或空字符串，"proxy" 键就不会被添加。
            if auth_file:
                launch_args_for_internal_camoufox["storage_state"] = auth_file
            
            if "," in camoufox_os_internal:
                camoufox_os_list_internal = [s.strip().lower() for s in camoufox_os_internal.split(',')]
                valid_os_values = ["windows", "macos", "linux"]
                if not all(val in valid_os_values for val in camoufox_os_list_internal):
                    print(f"❌ 内部Camoufox启动错误: camoufox_os_internal 列表中包含无效值: {camoufox_os_list_internal}", file=sys.stderr)
                    sys.exit(1)
                launch_args_for_internal_camoufox['os'] = camoufox_os_list_internal
            elif camoufox_os_internal.lower() in ["windows", "macos", "linux"]:
                launch_args_for_internal_camoufox['os'] = camoufox_os_internal.lower()
            elif camoufox_os_internal.lower() != "random": 
                print(f"❌ 内部Camoufox启动错误: camoufox_os_internal 值无效: '{camoufox_os_internal}'", file=sys.stderr)
                sys.exit(1)
            
            print(f"  传递给 launch_server 的参数: {launch_args_for_internal_camoufox}", flush=True)

            if internal_mode_arg == 'headless':
                launch_server(headless=True, **launch_args_for_internal_camoufox)
            elif internal_mode_arg == 'virtual_headless':
                launch_server(headless="virtual", **launch_args_for_internal_camoufox)
            elif internal_mode_arg == 'debug':
                launch_server(headless=False, **launch_args_for_internal_camoufox)
            
            print(f"--- [内部Camoufox启动] camoufox.server.launch_server ({internal_mode_arg}模式) 调用已完成/阻塞。脚本将等待其结束。 ---", flush=True)
        except Exception as e_internal_launch_final:
            print(f"❌ 错误 (--internal-launch-mode): 执行 camoufox.server.launch_server 时发生异常: {e_internal_launch_final}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        sys.exit(0) 

    # --- 主启动器逻辑 ---
    logger.info("🚀 Camoufox 启动器开始运行 🚀")
    logger.info("=================================================")
    ensure_auth_dirs_exist()
    check_dependencies()
    logger.info("=================================================")
    
    deprecated_auth_state_path = os.path.join(os.path.dirname(__file__), "auth_state.json")
    if os.path.exists(deprecated_auth_state_path):
        logger.warning(f"检测到已弃用的认证文件: {deprecated_auth_state_path}。此文件不再被直接使用。")
        logger.warning("请使用调试模式生成新的认证文件，并按需管理 'auth_profiles' 目录中的文件。")

    final_launch_mode = None # from dev
    if args.debug:
        final_launch_mode = 'debug'
    elif args.headless:
        final_launch_mode = 'headless'
    elif args.virtual_display: # from dev
        final_launch_mode = 'virtual_headless'
        if platform.system() != "Linux":
            logger.warning("⚠️ --virtual-display 模式主要为 Linux 设计。在非 Linux 系统上，其行为可能与标准无头模式相同或导致 Camoufox 内部错误。")
    else:
        # 读取 .env 文件中的 LAUNCH_MODE 配置作为默认值
        env_launch_mode = os.environ.get('LAUNCH_MODE', '').lower()
        default_mode_from_env = None
        default_interactive_choice = '1'  # 默认选择无头模式

        # 将 .env 中的 LAUNCH_MODE 映射到交互式选择
        if env_launch_mode == 'headless':
            default_mode_from_env = 'headless'
            default_interactive_choice = '1'
        elif env_launch_mode == 'debug' or env_launch_mode == 'normal':
            default_mode_from_env = 'debug'
            default_interactive_choice = '2'
        elif env_launch_mode == 'virtual_display' or env_launch_mode == 'virtual_headless':
            default_mode_from_env = 'virtual_headless'
            default_interactive_choice = '3' if platform.system() == "Linux" else '1'

        logger.info("--- 请选择启动模式 (未通过命令行参数指定) ---")
        if env_launch_mode and default_mode_from_env:
            logger.info(f"  从 .env 文件读取到默认启动模式: {env_launch_mode} -> {default_mode_from_env}")

        prompt_options_text = "[1] 无头模式, [2] 调试模式"
        valid_choices = {'1': 'headless', '2': 'debug'}

        if platform.system() == "Linux": # from dev
            prompt_options_text += ", [3] 无头模式 (虚拟显示 Xvfb)"
            valid_choices['3'] = 'virtual_headless'

        # 构建提示信息，显示当前默认选择
        default_mode_name = valid_choices.get(default_interactive_choice, 'headless')
        user_mode_choice = input_with_timeout(
            f"  请输入启动模式 ({prompt_options_text}; 默认: {default_interactive_choice} {default_mode_name}模式，{15}秒超时): ", 15
        ) or default_interactive_choice

        if user_mode_choice in valid_choices:
            final_launch_mode = valid_choices[user_mode_choice]
        else:
            final_launch_mode = default_mode_from_env or 'headless' # 使用 .env 默认值或回退到无头模式
            logger.info(f"无效输入 '{user_mode_choice}' 或超时，使用默认启动模式: {final_launch_mode}模式")
    logger.info(f"最终选择的启动模式: {final_launch_mode.replace('_', ' ')}模式")
    logger.info("-------------------------------------------------")

    if final_launch_mode == 'virtual_headless' and platform.system() == "Linux": # from dev
        logger.info("--- 检查 Xvfb (虚拟显示) 依赖 ---")
        if not shutil.which("Xvfb"):
            logger.error("  ❌ Xvfb 未找到。虚拟显示模式需要 Xvfb。请安装 (例如: sudo apt-get install xvfb) 后重试。")
            sys.exit(1)
        logger.info("  ✓ Xvfb 已找到。")

    server_target_port = args.server_port
    logger.info(f"--- 步骤 2: 检查 FastAPI 服务器目标端口 ({server_target_port}) 是否被占用 ---")
    port_is_available = False
    uvicorn_bind_host = "0.0.0.0" # from dev (was 127.0.0.1 in helper)
    if is_port_in_use(server_target_port, host=uvicorn_bind_host):
        logger.warning(f"  ❌ 端口 {server_target_port} (主机 {uvicorn_bind_host}) 当前被占用。")
        pids_on_port = find_pids_on_port(server_target_port)
        if pids_on_port:
            logger.warning(f"     识别到以下进程 PID 可能占用了端口 {server_target_port}: {pids_on_port}")
            if final_launch_mode == 'debug': 
                sys.stderr.flush()
                # Using input_with_timeout for consistency, though timeout might not be strictly needed here
                choice = input_with_timeout(f"     是否尝试终止这些进程？ (y/n, 输入 n 将继续并可能导致启动失败, 15s超时): ", 15).strip().lower()
                if choice == 'y':
                    logger.info("     用户选择尝试终止进程...")
                    all_killed = all(kill_process_interactive(pid) for pid in pids_on_port)
                    time.sleep(2) 
                    if not is_port_in_use(server_target_port, host=uvicorn_bind_host):
                        logger.info(f"     ✅ 端口 {server_target_port} (主机 {uvicorn_bind_host}) 现在可用。")
                        port_is_available = True
                    else:
                        logger.error(f"     ❌ 尝试终止后，端口 {server_target_port} (主机 {uvicorn_bind_host}) 仍然被占用。")
                else:
                    logger.info("     用户选择不自动终止或超时。将继续尝试启动服务器。")
            else: 
                 logger.error(f"     无头模式下，不会尝试自动终止占用端口的进程。服务器启动可能会失败。")
        else:
            logger.warning(f"     未能自动识别占用端口 {server_target_port} 的进程。服务器启动可能会失败。")
        
        if not port_is_available:
            logger.warning(f"--- 端口 {server_target_port} 仍可能被占用。继续启动服务器，它将自行处理端口绑定。 ---")
    else:
        logger.info(f"  ✅ 端口 {server_target_port} (主机 {uvicorn_bind_host}) 当前可用。")
        port_is_available = True


    logger.info("--- 步骤 3: 准备并启动 Camoufox 内部进程 ---")
    captured_ws_endpoint = None
    effective_active_auth_json_path = None # from dev

    if args.active_auth_json:
        logger.info(f"  尝试使用 --active-auth-json 参数提供的路径: '{args.active_auth_json}'")
        candidate_path = os.path.expanduser(args.active_auth_json)
        
        # 尝试解析路径:
        # 1. 作为绝对路径
        if os.path.isabs(candidate_path) and os.path.exists(candidate_path) and os.path.isfile(candidate_path):
            effective_active_auth_json_path = candidate_path
        else:
            # 2. 作为相对于当前工作目录的路径
            path_rel_to_cwd = os.path.abspath(candidate_path)
            if os.path.exists(path_rel_to_cwd) and os.path.isfile(path_rel_to_cwd):
                effective_active_auth_json_path = path_rel_to_cwd
            else:
                # 3. 作为相对于脚本目录的路径
                path_rel_to_script = os.path.join(os.path.dirname(__file__), candidate_path)
                if os.path.exists(path_rel_to_script) and os.path.isfile(path_rel_to_script):
                    effective_active_auth_json_path = path_rel_to_script
                # 4. 如果它只是一个文件名，则在 ACTIVE_AUTH_DIR 然后 SAVED_AUTH_DIR 中检查
                elif not os.path.sep in candidate_path: # 这是一个简单的文件名
                    path_in_active = os.path.join(ACTIVE_AUTH_DIR, candidate_path)
                    if os.path.exists(path_in_active) and os.path.isfile(path_in_active):
                        effective_active_auth_json_path = path_in_active
                    else:
                        path_in_saved = os.path.join(SAVED_AUTH_DIR, candidate_path)
                        if os.path.exists(path_in_saved) and os.path.isfile(path_in_saved):
                            effective_active_auth_json_path = path_in_saved
        
        if effective_active_auth_json_path:
            logger.info(f"  将使用通过 --active-auth-json 解析的认证文件: {effective_active_auth_json_path}")
        else:
            logger.error(f"❌ 指定的认证文件 (--active-auth-json='{args.active_auth_json}') 未找到或不是一个文件。")
            sys.exit(1)
    else:
        # --active-auth-json 未提供。
        if final_launch_mode == 'debug':
            # 对于调试模式，一律扫描全目录并提示用户选择，不自动使用任何文件
            logger.info(f"  调试模式: 扫描全目录并提示用户从可用认证文件中选择...")
        else:
            # 对于无头模式，检查 active/ 目录中的默认认证文件
            logger.info(f"  --active-auth-json 未提供。检查 '{ACTIVE_AUTH_DIR}' 中的默认认证文件...")
            try:
                if os.path.exists(ACTIVE_AUTH_DIR):
                    active_json_files = sorted([
                        f for f in os.listdir(ACTIVE_AUTH_DIR)
                        if f.lower().endswith('.json') and os.path.isfile(os.path.join(ACTIVE_AUTH_DIR, f))
                    ])
                    if active_json_files:
                        effective_active_auth_json_path = os.path.join(ACTIVE_AUTH_DIR, active_json_files[0])
                        logger.info(f"  将使用 '{ACTIVE_AUTH_DIR}' 中按名称排序的第一个JSON文件: {os.path.basename(effective_active_auth_json_path)}")
                    else:
                        logger.info(f"  目录 '{ACTIVE_AUTH_DIR}' 为空或不包含JSON文件。")
                else:
                    logger.info(f"  目录 '{ACTIVE_AUTH_DIR}' 不存在。")
            except Exception as e_scan_active:
                logger.warning(f"  扫描 '{ACTIVE_AUTH_DIR}' 时发生错误: {e_scan_active}", exc_info=True)

        # 处理 debug 模式的用户选择逻辑
        if final_launch_mode == 'debug':
            # 对于调试模式，一律扫描全目录并提示用户选择
            available_profiles = []
            # 首先扫描 ACTIVE_AUTH_DIR，然后是 SAVED_AUTH_DIR
            for profile_dir_path_str, dir_label in [(ACTIVE_AUTH_DIR, "active"), (SAVED_AUTH_DIR, "saved")]:
                if os.path.exists(profile_dir_path_str):
                    try:
                        # 在每个目录中对文件名进行排序
                        filenames = sorted([
                            f for f in os.listdir(profile_dir_path_str)
                            if f.lower().endswith(".json") and os.path.isfile(os.path.join(profile_dir_path_str, f))
                        ])
                        for filename in filenames:
                            full_path = os.path.join(profile_dir_path_str, filename)
                            available_profiles.append({"name": f"{dir_label}/{filename}", "path": full_path})
                    except OSError as e:
                        logger.warning(f"   ⚠️ 警告: 无法读取目录 '{profile_dir_path_str}': {e}")

            if available_profiles:
                # 对可用配置文件列表进行排序，以确保一致的显示顺序
                available_profiles.sort(key=lambda x: x['name'])
                print('-'*60 + "\n   找到以下可用的认证文件:", flush=True)
                for i, profile in enumerate(available_profiles): print(f"     {i+1}: {profile['name']}", flush=True)
                print("     N: 不加载任何文件 (使用浏览器当前状态)\n" + '-'*60, flush=True)
                choice = input_with_timeout(f"   请选择要加载的认证文件编号 (输入 N 或直接回车则不加载, {args.auth_save_timeout}s超时): ", args.auth_save_timeout)
                if choice.strip().lower() not in ['n', '']:
                    try:
                        choice_index = int(choice.strip()) - 1
                        if 0 <= choice_index < len(available_profiles):
                            selected_profile = available_profiles[choice_index]
                            effective_active_auth_json_path = selected_profile["path"]
                            logger.info(f"   已选择加载认证文件: {selected_profile['name']}")
                            print(f"   已选择加载: {selected_profile['name']}", flush=True)
                        else:
                            logger.info("   无效的选择编号或超时。将不加载认证文件。")
                            print("   无效的选择编号或超时。将不加载认证文件。", flush=True)
                    except ValueError:
                        logger.info("   无效的输入。将不加载认证文件。")
                        print("   无效的输入。将不加载认证文件。", flush=True)
                else:
                    logger.info("   好的，不加载认证文件或超时。")
                    print("   好的，不加载认证文件或超时。", flush=True)
                print('-'*60, flush=True)
            else:
                logger.info("   未找到认证文件。将使用浏览器当前状态。")
                print("   未找到认证文件。将使用浏览器当前状态。", flush=True)
        elif not effective_active_auth_json_path:
            # 对于无头模式，如果 --active-auth-json 未提供且 active/ 为空，则报错
            logger.error(f"  ❌ {final_launch_mode} 模式错误: --active-auth-json 未提供，且活动认证目录 '{ACTIVE_AUTH_DIR}' 中未找到任何 '.json' 认证文件。请先在调试模式下保存一个或通过参数指定。")
            sys.exit(1)

    # 构建 Camoufox 内部启动命令 (from dev)
    camoufox_internal_cmd_args = [
        PYTHON_EXECUTABLE, '-u', __file__, 
        '--internal-launch-mode', final_launch_mode
    ]
    if effective_active_auth_json_path:
        camoufox_internal_cmd_args.extend(['--internal-auth-file', effective_active_auth_json_path])
    
    camoufox_internal_cmd_args.extend(['--internal-camoufox-os', simulated_os_for_camoufox])
    camoufox_internal_cmd_args.extend(['--internal-camoufox-port', str(args.camoufox_debug_port)])

    # 修复：传递代理参数到内部Camoufox进程
    if args.internal_camoufox_proxy is not None:
        camoufox_internal_cmd_args.extend(['--internal-camoufox-proxy', args.internal_camoufox_proxy])

    camoufox_popen_kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'env': os.environ.copy()}
    camoufox_popen_kwargs['env']['PYTHONIOENCODING'] = 'utf-8' 
    if sys.platform != "win32" and final_launch_mode != 'debug': 
        camoufox_popen_kwargs['start_new_session'] = True
    elif sys.platform == "win32" and (final_launch_mode == 'headless' or final_launch_mode == 'virtual_headless'):
         camoufox_popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW


    try:
        logger.info(f"  将执行 Camoufox 内部启动命令: {' '.join(camoufox_internal_cmd_args)}")
        camoufox_proc = subprocess.Popen(camoufox_internal_cmd_args, **camoufox_popen_kwargs)
        logger.info(f"  Camoufox 内部进程已启动 (PID: {camoufox_proc.pid})。正在等待 WebSocket 端点输出 (最长 {ENDPOINT_CAPTURE_TIMEOUT} 秒)...")
        
        camoufox_output_q = queue.Queue()
        camoufox_stdout_reader = threading.Thread(target=_enqueue_output, args=(camoufox_proc.stdout, "stdout", camoufox_output_q, camoufox_proc.pid), daemon=True)
        camoufox_stderr_reader = threading.Thread(target=_enqueue_output, args=(camoufox_proc.stderr, "stderr", camoufox_output_q, camoufox_proc.pid), daemon=True)
        camoufox_stdout_reader.start()
        camoufox_stderr_reader.start()

        ws_capture_start_time = time.time()
        camoufox_ended_streams_count = 0
        while time.time() - ws_capture_start_time < ENDPOINT_CAPTURE_TIMEOUT:
            if camoufox_proc.poll() is not None:
                logger.error(f"  Camoufox 内部进程 (PID: {camoufox_proc.pid}) 在等待 WebSocket 端点期间已意外退出，退出码: {camoufox_proc.poll()}。")
                break
            try:
                stream_name, line_from_camoufox = camoufox_output_q.get(timeout=0.2)
                if line_from_camoufox is None: 
                    camoufox_ended_streams_count += 1
                    logger.debug(f"  [InternalCamoufox-{stream_name}-PID:{camoufox_proc.pid}] 输出流已关闭 (EOF)。")
                    if camoufox_ended_streams_count >= 2: 
                        logger.info(f"  Camoufox 内部进程 (PID: {camoufox_proc.pid}) 的所有输出流均已关闭。")
                        break
                    continue
                
                log_line_content = f"[InternalCamoufox-{stream_name}-PID:{camoufox_proc.pid}]: {line_from_camoufox.rstrip()}"
                if stream_name == "stderr" or "ERROR" in line_from_camoufox.upper() or "❌" in line_from_camoufox:
                    logger.warning(log_line_content)
                else:
                    logger.info(log_line_content)

                ws_match = ws_regex.search(line_from_camoufox)
                if ws_match:
                    captured_ws_endpoint = ws_match.group(1)
                    logger.info(f"  ✅ 成功从 Camoufox 内部进程捕获到 WebSocket 端点: {captured_ws_endpoint[:40]}...")
                    break 
            except queue.Empty:
                continue
        
        if camoufox_stdout_reader.is_alive(): camoufox_stdout_reader.join(timeout=1.0)
        if camoufox_stderr_reader.is_alive(): camoufox_stderr_reader.join(timeout=1.0)

        if not captured_ws_endpoint and (camoufox_proc and camoufox_proc.poll() is None):
            logger.error(f"  ❌ 未能在 {ENDPOINT_CAPTURE_TIMEOUT} 秒内从 Camoufox 内部进程 (PID: {camoufox_proc.pid}) 捕获到 WebSocket 端点。")
            logger.error("  Camoufox 内部进程仍在运行，但未输出预期的 WebSocket 端点。请检查其日志或行为。")
            cleanup() 
            sys.exit(1)
        elif not captured_ws_endpoint and (camoufox_proc and camoufox_proc.poll() is not None):
            logger.error(f"  ❌ Camoufox 内部进程已退出，且未能捕获到 WebSocket 端点。")
            sys.exit(1)
        elif not captured_ws_endpoint: 
            logger.error(f"  ❌ 未能捕获到 WebSocket 端点。")
            sys.exit(1)

    except Exception as e_launch_camoufox_internal:
        logger.critical(f"  ❌ 在内部启动 Camoufox 或捕获其 WebSocket 端点时发生致命错误: {e_launch_camoufox_internal}", exc_info=True)
        cleanup()
        sys.exit(1)

    # --- Helper mode logic (New implementation) ---
    if args.helper: # 如果 args.helper 不是空字符串 (即 helper 功能已通过默认值或用户指定启用)
        logger.info(f"  Helper 模式已启用，端点: {args.helper}")
        os.environ['HELPER_ENDPOINT'] = args.helper # 设置端点环境变量

        if effective_active_auth_json_path:
            logger.info(f"    尝试从认证文件 '{os.path.basename(effective_active_auth_json_path)}' 提取 SAPISID...")
            sapisid = ""
            try:
                with open(effective_active_auth_json_path, 'r', encoding='utf-8') as file:
                    auth_file_data = json.load(file)
                    if "cookies" in auth_file_data and isinstance(auth_file_data["cookies"], list):
                        for cookie in auth_file_data["cookies"]:
                            if isinstance(cookie, dict) and cookie.get("name") == "SAPISID" and cookie.get("domain") == ".google.com":
                                sapisid = cookie.get("value", "")
                                break
            except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"    ⚠️ 无法从认证文件 '{os.path.basename(effective_active_auth_json_path)}' 加载或解析SAPISID: {e}")
            except Exception as e_sapisid_extraction:
                logger.warning(f"    ⚠️ 提取SAPISID时发生未知错误: {e_sapisid_extraction}")

            if sapisid:
                logger.info(f"    ✅ 成功加载 SAPISID。将设置 HELPER_SAPISID 环境变量。")
                os.environ['HELPER_SAPISID'] = sapisid
            else:
                logger.warning(f"    ⚠️ 未能从认证文件 '{os.path.basename(effective_active_auth_json_path)}' 中找到有效的 SAPISID。HELPER_SAPISID 将不会被设置。")
                if 'HELPER_SAPISID' in os.environ: # 清理，以防万一
                    del os.environ['HELPER_SAPISID']
        else: # args.helper 有值 (Helper 模式启用), 但没有认证文件
            logger.warning(f"    ⚠️ Helper 模式已启用，但没有有效的认证文件来提取 SAPISID。HELPER_SAPISID 将不会被设置。")
            if 'HELPER_SAPISID' in os.environ: # 清理
                del os.environ['HELPER_SAPISID']
    else: # args.helper 是空字符串 (用户通过 --helper='' 禁用了 helper)
        logger.info("  Helper 模式已通过 --helper='' 禁用。")
        # 清理相关的环境变量
        if 'HELPER_ENDPOINT' in os.environ:
            del os.environ['HELPER_ENDPOINT']
        if 'HELPER_SAPISID' in os.environ:
            del os.environ['HELPER_SAPISID']

    # --- 步骤 4: 设置环境变量并准备启动 FastAPI/Uvicorn 服务器 (from dev) ---
    logger.info("--- 步骤 4: 设置环境变量并准备启动 FastAPI/Uvicorn 服务器 ---")
    
    if captured_ws_endpoint:
        os.environ['CAMOUFOX_WS_ENDPOINT'] = captured_ws_endpoint
    else: 
        logger.error("  严重逻辑错误: WebSocket 端点未捕获，但程序仍在继续。")
        sys.exit(1)

    os.environ['LAUNCH_MODE'] = final_launch_mode
    os.environ['SERVER_LOG_LEVEL'] = args.server_log_level.upper()
    os.environ['SERVER_REDIRECT_PRINT'] = str(args.server_redirect_print).lower()
    os.environ['DEBUG_LOGS_ENABLED'] = str(args.debug_logs).lower()
    os.environ['TRACE_LOGS_ENABLED'] = str(args.trace_logs).lower()
    if effective_active_auth_json_path:
        os.environ['ACTIVE_AUTH_JSON_PATH'] = effective_active_auth_json_path
    os.environ['AUTO_SAVE_AUTH'] = str(args.auto_save_auth).lower()
    os.environ['AUTH_SAVE_TIMEOUT'] = str(args.auth_save_timeout)
    os.environ['SERVER_PORT_INFO'] = str(args.server_port)
    os.environ['STREAM_PORT'] = str(args.stream_port)

    # 设置统一的代理配置环境变量
    proxy_config = determine_proxy_configuration(args.internal_camoufox_proxy)
    if proxy_config['stream_proxy']:
        os.environ['UNIFIED_PROXY_CONFIG'] = proxy_config['stream_proxy']
        logger.info(f"  设置统一代理配置: {proxy_config['source']}")
    elif 'UNIFIED_PROXY_CONFIG' in os.environ:
        del os.environ['UNIFIED_PROXY_CONFIG']

    host_os_for_shortcut_env = None
    camoufox_os_param_lower = simulated_os_for_camoufox.lower()
    if camoufox_os_param_lower == "macos": host_os_for_shortcut_env = "Darwin"
    elif camoufox_os_param_lower == "windows": host_os_for_shortcut_env = "Windows"
    elif camoufox_os_param_lower == "linux": host_os_for_shortcut_env = "Linux"
    if host_os_for_shortcut_env:
        os.environ['HOST_OS_FOR_SHORTCUT'] = host_os_for_shortcut_env
    elif 'HOST_OS_FOR_SHORTCUT' in os.environ: 
        del os.environ['HOST_OS_FOR_SHORTCUT']
    
    logger.info(f"  为 server.app 设置的环境变量:")
    env_keys_to_log = [
        'CAMOUFOX_WS_ENDPOINT', 'LAUNCH_MODE', 'SERVER_LOG_LEVEL',
        'SERVER_REDIRECT_PRINT', 'DEBUG_LOGS_ENABLED', 'TRACE_LOGS_ENABLED',
        'ACTIVE_AUTH_JSON_PATH', 'AUTO_SAVE_AUTH', 'AUTH_SAVE_TIMEOUT',
        'SERVER_PORT_INFO', 'HOST_OS_FOR_SHORTCUT',
        'HELPER_ENDPOINT', 'HELPER_SAPISID', 'STREAM_PORT',
        'UNIFIED_PROXY_CONFIG'  # 新增统一代理配置
    ]
    for key in env_keys_to_log:
        if key in os.environ:
            val_to_log = os.environ[key]
            if key == 'CAMOUFOX_WS_ENDPOINT' and len(val_to_log) > 40: val_to_log = val_to_log[:40] + "..."
            if key == 'ACTIVE_AUTH_JSON_PATH': val_to_log = os.path.basename(val_to_log)
            logger.info(f"    {key}={val_to_log}")
        else:
            logger.info(f"    {key}= (未设置)")


    # --- 步骤 5: 启动 FastAPI/Uvicorn 服务器 (from dev) ---
    logger.info(f"--- 步骤 5: 启动集成的 FastAPI 服务器 (监听端口: {args.server_port}) ---")
    try:
        uvicorn.run(
            app,
            host="0.0.0.0", # Bind to all interfaces
            port=args.server_port,
            log_config=None # server.py will handle its own logging based on env vars
        )
        logger.info("Uvicorn 服务器已停止。")
    except SystemExit as e_sysexit:
        logger.info(f"Uvicorn 或其子系统通过 sys.exit({e_sysexit.code}) 退出。")
    except Exception as e_uvicorn:
        logger.critical(f"❌ 运行 Uvicorn 时发生致命错误: {e_uvicorn}", exc_info=True)
        sys.exit(1) # Ensure launcher exits if Uvicorn fails critically
    
    logger.info("🚀 Camoufox 启动器主逻辑执行完毕 🚀")