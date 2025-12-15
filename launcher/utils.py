import logging
import platform
import select
import socket
import subprocess
import sys
import threading
from typing import List, Optional

logger = logging.getLogger("CamoufoxLauncher")


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


def find_pids_on_port(port: int) -> List[int]:
    pids: List[int] = []
    system_platform = platform.system()
    command = ""
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            command = f"lsof -ti :{port} -sTCP:LISTEN"
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
            )
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode == 0 and stdout:
                pids = [int(pid) for pid in stdout.strip().split("\n") if pid.isdigit()]
            elif process.returncode != 0 and (
                "command not found" in stderr.lower() or "未找到命令" in stderr
            ):
                logger.error("命令 'lsof' 未找到。请确保已安装。")
            elif process.returncode not in [0, 1]:  # lsof 在未找到时返回1
                logger.warning(
                    f"执行 lsof 命令失败 (返回码 {process.returncode}): {stderr.strip()}"
                )
        elif system_platform == "Windows":
            command = f'netstat -ano -p TCP | findstr "LISTENING" | findstr ":{port} "'
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode == 0 and stdout:
                for line in stdout.strip().split("\n"):
                    parts = line.split()
                    if (
                        len(parts) >= 4
                        and parts[0].upper() == "TCP"
                        and f":{port}" in parts[1]
                    ):
                        if parts[-1].isdigit():
                            pids.append(int(parts[-1]))
                pids = list(set(pids))  # 去重
            elif process.returncode not in [0, 1]:  # findstr 在未找到时返回1
                logger.warning(
                    f"执行 netstat/findstr 命令失败 (返回码 {process.returncode}): {stderr.strip()}"
                )
        else:
            logger.warning(
                f"不支持的操作系统 '{system_platform}' 用于查找占用端口的进程。"
            )
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
    logger.info(f"尝试终止进程 PID: {pid}...")
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            result_term = subprocess.run(
                f"kill {pid}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result_term.returncode == 0:
                logger.info(f"PID {pid} 已发送 SIGTERM 信号。")
                success = True
            else:
                logger.warning(
                    f"    PID {pid} SIGTERM 失败: {result_term.stderr.strip() or result_term.stdout.strip()}. 尝试 SIGKILL..."
                )
                result_kill = subprocess.run(
                    f"kill -9 {pid}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if result_kill.returncode == 0:
                    logger.info(f"PID {pid} 已发送 SIGKILL 信号。")
                    success = True
                else:
                    logger.error(
                        f"    ✗ PID {pid} SIGKILL 失败: {result_kill.stderr.strip() or result_kill.stdout.strip()}."
                    )
        elif system_platform == "Windows":
            command_desc = f"taskkill /PID {pid} /T /F"
            result = subprocess.run(
                command_desc,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = result.stdout.strip()
            error_output = result.stderr.strip()
            if result.returncode == 0 and (
                "SUCCESS" in output.upper() or "成功" in output
            ):
                logger.info(f"PID {pid} 已通过 taskkill /F 终止。")
                success = True
            elif (
                "could not find process" in error_output.lower()
                or "找不到" in error_output
            ):  # 进程可能已自行退出
                logger.info(f"PID {pid} 执行 taskkill 时未找到 (可能已退出)。")
                success = True  # 视为成功，因为目标是端口可用
            else:
                # 统计错误数量而非逐个输出
                combined = (error_output + " " + output).strip()
                error_count = combined.count("ERROR:")
                if error_count > 0:
                    logger.warning(
                        f"    PID {pid} taskkill /F: (抑制 {error_count} 条错误信息)"
                    )
                else:
                    logger.warning(f"PID {pid} taskkill /F 返回非零状态")
        else:
            logger.warning(f"不支持的操作系统 '{system_platform}' 用于终止进程。")
    except Exception as e:
        logger.error(f"终止 PID {pid} 时发生意外错误: {e}", exc_info=True)
    return success


def input_with_timeout(prompt_message: str, timeout_seconds: int = 30) -> str:
    print(prompt_message, end="", flush=True)
    if sys.platform == "win32":
        user_input_container: List[Optional[str]] = [None]

        def get_input_in_thread():
            try:
                user_input_container[0] = sys.stdin.readline().strip()
            except Exception:
                user_input_container[0] = ""  # 出错时返回空字符串

        input_thread = threading.Thread(target=get_input_in_thread, daemon=True)
        input_thread.start()
        input_thread.join(timeout=timeout_seconds)
        if input_thread.is_alive():
            print("\n输入超时。将使用默认值。", flush=True)
            return ""
        return user_input_container[0] if user_input_container[0] is not None else ""
    else:  # Linux/macOS
        readable_fds, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
        if readable_fds:
            return sys.stdin.readline().strip()
        else:
            print("\n输入超时。将使用默认值。", flush=True)
            return ""


def get_proxy_from_gsettings() -> Optional[str]:
    """
    Retrieves the proxy settings from GSettings on Linux systems.
    Returns a proxy string like "http://host:port" or None.
    """

    def _run_gsettings_command(command_parts: List[str]) -> Optional[str]:
        """Helper function to run gsettings command and return cleaned string output."""
        try:
            process_result = subprocess.run(
                command_parts,
                capture_output=True,
                text=True,
                check=False,  # Do not raise CalledProcessError for non-zero exit codes
                timeout=1,  # Timeout for the subprocess call
            )
            if process_result.returncode == 0:
                value = process_result.stdout.strip()
                if value.startswith("'") and value.endswith(
                    "'"
                ):  # Remove surrounding single quotes
                    value = value[1:-1]

                # If after stripping quotes, value is empty, or it's a gsettings "empty" representation
                if not value or value == "''" or value == "@as []" or value == "[]":
                    return None
                return value
            else:
                return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:  # Broad exception as per pseudocode
            return None

    proxy_mode = _run_gsettings_command(
        ["gsettings", "get", "org.gnome.system.proxy", "mode"]
    )

    if proxy_mode == "manual":
        # Try HTTP proxy first
        http_host = _run_gsettings_command(
            ["gsettings", "get", "org.gnome.system.proxy.http", "host"]
        )
        http_port_str = _run_gsettings_command(
            ["gsettings", "get", "org.gnome.system.proxy.http", "port"]
        )

        if http_host and http_port_str:
            try:
                http_port = int(http_port_str)
                if http_port > 0:
                    return f"http://{http_host}:{http_port}"
            except ValueError:
                pass  # Continue to HTTPS

        # Try HTTPS proxy if HTTP not found or invalid
        https_host = _run_gsettings_command(
            ["gsettings", "get", "org.gnome.system.proxy.https", "host"]
        )
        https_port_str = _run_gsettings_command(
            ["gsettings", "get", "org.gnome.system.proxy.https", "port"]
        )

        if https_host and https_port_str:
            try:
                https_port = int(https_port_str)
                if https_port > 0:
                    # Note: Even for HTTPS proxy settings, the scheme for Playwright/requests is usually http://
                    return f"http://{https_host}:{https_port}"
            except ValueError:
                pass

    return None
