import atexit
import json
import logging
import os
import platform
import re
import shutil
import signal
import sys
import threading
import time
from typing import Optional

import uvicorn

from launcher.checks import check_dependencies, ensure_auth_dirs_exist
from launcher.config import (
    ACTIVE_AUTH_DIR,
    DIRECT_LAUNCH,
    SAVED_AUTH_DIR,
    determine_proxy_configuration,
    parse_args,
)
from launcher.internal import run_internal_camoufox
from launcher.logging_setup import setup_launcher_logging
from launcher.process import CamoufoxProcessManager
from launcher.utils import (
    find_pids_on_port,
    input_with_timeout,
    is_port_in_use,
    kill_process_interactive,
)

# 尝试导入 launch_server (用于内部启动模式，模拟 Camoufox 行为)
try:
    from camoufox import DefaultAddons  # 假设 DefaultAddons 包含 AntiFingerprint
    from camoufox.server import launch_server
except ImportError:
    launch_server = None
    DefaultAddons = None

# 导入 server app
try:
    from server import app
except ImportError:
    app = None

logger = logging.getLogger("CamoufoxLauncher")


class Launcher:  # pragma: no cover
    def __init__(self):
        self.args = parse_args()
        self.camoufox_manager = CamoufoxProcessManager()
        atexit.register(self.camoufox_manager.cleanup)
        self.final_launch_mode: str = "headless"  # Default, will be determined later
        self.effective_active_auth_json_path: Optional[str] = None
        self.simulated_os_for_camoufox = "linux"

    def run(self):
        # 检查是否是内部启动调用
        # 注意：不能只检查 startswith("--internal-")，因为 --internal-camoufox-proxy 是主进程参数
        is_internal_call = self.args.internal_launch_mode is not None

        if is_internal_call:
            # 处理内部 Camoufox 启动逻辑
            if self.args.internal_launch_mode:
                run_internal_camoufox(self.args, launch_server, DefaultAddons)
            return

        # 主启动器逻辑 - 读取环境变量中的日志级别
        log_level_str = os.environ.get("SERVER_LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        setup_launcher_logging(log_level=log_level)
        logger.info("[系统] 启动器开始运行")
        ensure_auth_dirs_exist()
        check_dependencies(launch_server is not None, DefaultAddons is not None)

        # 自动检查并重建前端（如果源文件有更新）
        from launcher.frontend_build import ensure_frontend_built

        ensure_frontend_built(skip_build=self.args.skip_frontend_build)

        self._check_deprecated_auth_file()
        self._determine_launch_mode()
        if not DIRECT_LAUNCH:
            self._handle_auth_file_selection()
        self._check_xvfb()
        self._check_server_port()

        logger.debug("[Init] 步骤 3: 准备并启动 Camoufox...")
        self._resolve_auth_file_path()

        # 自动检测当前系统并设置 Camoufox OS 模拟
        current_system_for_camoufox = platform.system()
        if current_system_for_camoufox == "Linux":
            self.simulated_os_for_camoufox = "linux"
        elif current_system_for_camoufox == "Windows":
            self.simulated_os_for_camoufox = "windows"
        elif current_system_for_camoufox == "Darwin":  # macOS
            self.simulated_os_for_camoufox = "macos"
        else:
            logger.warning(
                f"无法识别当前系统 '{current_system_for_camoufox}'。Camoufox OS 模拟将默认设置为: {self.simulated_os_for_camoufox}"
            )

        # Consolidated startup summary (replaces 5 verbose lines)
        mode_str = self.final_launch_mode.replace("_", " ").capitalize()
        auth_name = (
            os.path.basename(self.effective_active_auth_json_path)
            if self.effective_active_auth_json_path
            else "None"
        )
        logger.info(
            f"[系统] 配置就绪 | 端口: {self.args.server_port} | 模式: {mode_str} | Auth: {auth_name}"
        )

        captured_ws_endpoint = self.camoufox_manager.start(
            self.final_launch_mode,
            self.effective_active_auth_json_path,
            self.simulated_os_for_camoufox,
            self.args,
        )

        self._setup_helper_mode()
        self._setup_environment_variables(captured_ws_endpoint)
        self._start_server()

        logger.info("Camoufox 启动器主逻辑执行完毕")

    def _check_deprecated_auth_file(self):
        deprecated_auth_state_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "auth_state.json"
        )
        if os.path.exists(deprecated_auth_state_path):
            logger.warning(
                f"检测到已弃用的认证文件: {deprecated_auth_state_path}。此文件不再被直接使用。"
            )
            logger.warning(
                "请使用调试模式生成新的认证文件，并按需管理 'auth_profiles' 目录中的文件。"
            )

    def _determine_launch_mode(self):
        if self.args.debug:
            self.final_launch_mode = "debug"
        elif self.args.headless:
            self.final_launch_mode = "headless"
        elif self.args.virtual_display:
            self.final_launch_mode = "virtual_headless"
            if platform.system() != "Linux":
                logger.warning(
                    "--virtual-display 模式主要为 Linux 设计。在非 Linux 系统上，其行为可能与标准无头模式相同或导致 Camoufox 内部错误。"
                )
        else:
            # 读取 .env 文件中的 LAUNCH_MODE 配置作为默认值
            env_launch_mode = os.environ.get("LAUNCH_MODE", "").lower()
            default_mode_from_env = None
            default_interactive_choice = "1"  # 默认选择无头模式

            # 将 .env 中的 LAUNCH_MODE 映射到交互式选择
            if env_launch_mode == "headless":
                default_mode_from_env = "headless"
                default_interactive_choice = "1"
            elif env_launch_mode == "debug" or env_launch_mode == "normal":
                default_mode_from_env = "debug"
                default_interactive_choice = "2"
            elif (
                env_launch_mode == "virtual_display"
                or env_launch_mode == "virtual_headless"
            ):
                default_mode_from_env = "virtual_headless"
                default_interactive_choice = (
                    "3" if platform.system() == "Linux" else "1"
                )

            if DIRECT_LAUNCH:
                self.final_launch_mode = default_mode_from_env or "headless"
                return

            logger.info("--- 请选择启动模式 (未通过命令行参数指定) ---")
            if env_launch_mode and default_mode_from_env:
                logger.info(
                    f"  从 .env 文件读取到默认启动模式: {env_launch_mode} -> {default_mode_from_env}"
                )

            prompt_options_text = "[1] 无头模式, [2] 调试模式"
            valid_choices = {"1": "headless", "2": "debug"}

            if platform.system() == "Linux":
                prompt_options_text += ", [3] 无头模式 (虚拟显示 Xvfb)"
                valid_choices["3"] = "virtual_headless"

            # 构建提示信息，显示当前默认选择
            default_mode_name = valid_choices.get(
                default_interactive_choice, "headless"
            )
            user_mode_choice = (
                input_with_timeout(
                    f"  请输入启动模式 ({prompt_options_text}; 默认: {default_interactive_choice} {default_mode_name}模式，{15}秒超时): ",
                    15,
                )
                or default_interactive_choice
            )

            if user_mode_choice in valid_choices:
                self.final_launch_mode = valid_choices[user_mode_choice]
            else:
                self.final_launch_mode = (
                    default_mode_from_env or "headless"
                )  # 使用 .env 默认值或回退到无头模式
                logger.info(
                    f"无效输入 '{user_mode_choice}' 或超时，使用默认启动模式: {self.final_launch_mode}模式"
                )
        logger.debug(
            f"最终选择的启动模式: {self.final_launch_mode.replace('_', ' ')}模式"
        )

    def _handle_auth_file_selection(self):
        if self.final_launch_mode == "debug" and not self.args.active_auth_json:
            create_new_auth_choice = (
                input_with_timeout(
                    "  是否要创建并保存新的认证文件? (y/n; 默认: n, 15s超时): ", 15
                )
                .strip()
                .lower()
            )
            if create_new_auth_choice == "y":
                new_auth_filename = ""
                while not new_auth_filename:
                    new_auth_filename_input = input_with_timeout(
                        "  请输入要保存的文件名 (不含.json后缀, 字母/数字/-/_): ",
                        self.args.auth_save_timeout,
                    ).strip()
                    # 简单的合法性校验
                    if re.match(r"^[a-zA-Z0-9_-]+$", new_auth_filename_input):
                        new_auth_filename = new_auth_filename_input
                    elif new_auth_filename_input == "":
                        logger.info("输入为空或超时，取消创建新认证文件。")
                        break
                    else:
                        print("文件名包含无效字符，请重试。")

                if new_auth_filename:
                    self.args.auto_save_auth = True
                    self.args.save_auth_as = new_auth_filename
                    logger.info(
                        f"好的，登录成功后将自动保存认证文件为: {new_auth_filename}.json"
                    )
                    # 在这种模式下，不应该加载任何现有的认证文件
                    if self.effective_active_auth_json_path:
                        logger.info(
                            "由于将创建新的认证文件，已清除先前加载的认证文件设置。"
                        )
                        self.effective_active_auth_json_path = None
            else:
                logger.info("好的，将不创建新的认证文件。")

    def _check_xvfb(self):
        if (
            self.final_launch_mode == "virtual_headless"
            and platform.system() == "Linux"
        ):
            logger.info("--- 检查 Xvfb (虚拟显示) 依赖 ---")
            if not shutil.which("Xvfb"):
                logger.error(
                    "Xvfb 未找到。虚拟显示模式需要 Xvfb。请安装 (例如: sudo apt-get install xvfb) 后重试。"
                )
                sys.exit(1)
            logger.info("Xvfb 已找到。")

    def _check_server_port(self):
        server_target_port = self.args.server_port
        logger.info(
            f"--- 步骤 2: 检查 FastAPI 服务器目标端口 ({server_target_port}) 是否被占用 ---"
        )
        port_is_available = False
        uvicorn_bind_host = "0.0.0.0"
        if is_port_in_use(server_target_port, host=uvicorn_bind_host):
            logger.warning(
                f"端口 {server_target_port} (主机 {uvicorn_bind_host}) 当前被占用。"
            )
            pids_on_port = find_pids_on_port(server_target_port)
            if pids_on_port:
                logger.warning(
                    f"识别到以下进程 PID 可能占用了端口 {server_target_port}: {pids_on_port}"
                )
                if self.final_launch_mode == "debug":
                    sys.stderr.flush()
                    choice = (
                        input_with_timeout(
                            "     是否尝试终止这些进程？ (y/n, 输入 n 将继续并可能导致启动失败, 15s超时): ",
                            15,
                        )
                        .strip()
                        .lower()
                    )
                    if choice == "y":
                        logger.info("用户选择尝试终止进程...")
                        all(kill_process_interactive(pid) for pid in pids_on_port)
                        time.sleep(2)
                        if not is_port_in_use(
                            server_target_port, host=uvicorn_bind_host
                        ):
                            logger.info(
                                f"端口 {server_target_port} (主机 {uvicorn_bind_host}) 现在可用。"
                            )
                            port_is_available = True
                        else:
                            logger.error(
                                f"尝试终止后，端口 {server_target_port} (主机 {uvicorn_bind_host}) 仍然被占用。"
                            )
                    else:
                        logger.info("用户选择不自动终止或超时。将继续尝试启动服务器。")
                else:
                    logger.error(
                        "无头模式下，不会尝试自动终止占用端口的进程。服务器启动可能会失败。"
                    )
            else:
                logger.warning(
                    f"未能自动识别占用端口 {server_target_port} 的进程。服务器启动可能会失败。"
                )

            if not port_is_available:
                logger.warning(
                    f"--- 端口 {server_target_port} 仍可能被占用。继续启动服务器，它将自行处理端口绑定。 ---"
                )
        else:
            logger.debug(f"[系统] 服务端口 {server_target_port} 可用")
            port_is_available = True

    def _resolve_auth_file_path(self):
        if self.args.active_auth_json:
            logger.info(
                f"尝试使用 --active-auth-json 参数提供的路径: '{self.args.active_auth_json}'"
            )
            candidate_path = os.path.expanduser(self.args.active_auth_json)

            # 尝试解析路径:
            # 1. 作为绝对路径
            if (
                os.path.isabs(candidate_path)
                and os.path.exists(candidate_path)
                and os.path.isfile(candidate_path)
            ):
                self.effective_active_auth_json_path = candidate_path
            else:
                # 2. 作为相对于当前工作目录的路径
                path_rel_to_cwd = os.path.abspath(candidate_path)
                if os.path.exists(path_rel_to_cwd) and os.path.isfile(path_rel_to_cwd):
                    self.effective_active_auth_json_path = path_rel_to_cwd
                else:
                    # 3. 作为相对于脚本目录的路径
                    path_rel_to_script = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)), candidate_path
                    )
                    if os.path.exists(path_rel_to_script) and os.path.isfile(
                        path_rel_to_script
                    ):
                        self.effective_active_auth_json_path = path_rel_to_script
                    # 4. 如果它只是一个文件名，则在 ACTIVE_AUTH_DIR 然后 SAVED_AUTH_DIR 中检查
                    elif os.path.sep not in candidate_path:  # 这是一个简单的文件名
                        path_in_active = os.path.join(ACTIVE_AUTH_DIR, candidate_path)
                        if os.path.exists(path_in_active) and os.path.isfile(
                            path_in_active
                        ):
                            self.effective_active_auth_json_path = path_in_active
                        else:
                            path_in_saved = os.path.join(SAVED_AUTH_DIR, candidate_path)
                            if os.path.exists(path_in_saved) and os.path.isfile(
                                path_in_saved
                            ):
                                self.effective_active_auth_json_path = path_in_saved

            if self.effective_active_auth_json_path:
                logger.info(
                    f"将使用通过 --active-auth-json 解析的认证文件: {self.effective_active_auth_json_path}"
                )
            else:
                logger.error(
                    f"指定的认证文件 (--active-auth-json='{self.args.active_auth_json}') 未找到或不是一个文件。"
                )
                sys.exit(1)
        else:
            # --active-auth-json 未提供。
            if self.final_launch_mode == "debug":
                # 对于调试模式，一律扫描全目录并提示用户选择，不自动使用任何文件
                logger.info("调试模式: 扫描全目录并提示用户从可用认证文件中选择...")
            else:
                # 对于无头模式，检查 active/ 目录中的默认认证文件
                logger.debug(
                    f"--active-auth-json 未提供。检查 '{ACTIVE_AUTH_DIR}' 中的默认认证文件..."
                )
                try:
                    if os.path.exists(ACTIVE_AUTH_DIR):
                        active_json_files = sorted(
                            [
                                f
                                for f in os.listdir(ACTIVE_AUTH_DIR)
                                if f.lower().endswith(".json")
                                and os.path.isfile(os.path.join(ACTIVE_AUTH_DIR, f))
                            ]
                        )
                        if active_json_files:
                            self.effective_active_auth_json_path = os.path.join(
                                ACTIVE_AUTH_DIR, active_json_files[0]
                            )
                        else:
                            logger.info(
                                f"目录 '{ACTIVE_AUTH_DIR}' 为空或不包含JSON文件。"
                            )
                    else:
                        logger.info(f"目录 '{ACTIVE_AUTH_DIR}' 不存在。")
                except Exception as e_scan_active:
                    logger.warning(
                        f"扫描 '{ACTIVE_AUTH_DIR}' 时发生错误: {e_scan_active}",
                        exc_info=True,
                    )

            # 处理 debug 模式的用户选择逻辑
            if self.final_launch_mode == "debug" and not self.args.auto_save_auth:
                # 对于调试模式，一律扫描全目录并提示用户选择
                available_profiles = []
                # 首先扫描 ACTIVE_AUTH_DIR，然后是 SAVED_AUTH_DIR
                for profile_dir_path_str, dir_label in [
                    (ACTIVE_AUTH_DIR, "active"),
                    (SAVED_AUTH_DIR, "saved"),
                ]:
                    if os.path.exists(profile_dir_path_str):
                        try:
                            # 在每个目录中对文件名进行排序
                            filenames = sorted(
                                [
                                    f
                                    for f in os.listdir(profile_dir_path_str)
                                    if f.lower().endswith(".json")
                                    and os.path.isfile(
                                        os.path.join(profile_dir_path_str, f)
                                    )
                                ]
                            )
                            for filename in filenames:
                                full_path = os.path.join(profile_dir_path_str, filename)
                                available_profiles.append(
                                    {
                                        "name": f"{dir_label}/{filename}",
                                        "path": full_path,
                                    }
                                )
                        except OSError as e:
                            logger.warning(
                                f"警告: 无法读取目录 '{profile_dir_path_str}': {e}"
                            )

                if available_profiles:
                    # 对可用配置文件列表进行排序，以确保一致的显示顺序
                    available_profiles.sort(key=lambda x: x["name"])
                    if DIRECT_LAUNCH:
                        selected_profile = available_profiles[0]
                        self.effective_active_auth_json_path = selected_profile["path"]
                        logger.info(
                            f"快速启动：自动选择第一个可用认证文件: {selected_profile['name']}"
                        )
                    else:
                        print("-" * 60 + "\n找到以下可用的认证文件:", flush=True)
                        for i, profile in enumerate(available_profiles):
                            print(f"{i + 1}: {profile['name']}", flush=True)
                        print(
                            "N: 不加载任何文件 (使用浏览器当前状态)\n" + "-" * 60,
                            flush=True,
                        )
                        choice = input_with_timeout(
                            f"请选择要加载的认证文件编号 (输入 N 或直接回车则不加载, {self.args.auth_save_timeout}s超时): ",
                            self.args.auth_save_timeout,
                        )
                        if choice.strip().lower() not in ["n", ""]:
                            try:
                                choice_index = int(choice.strip()) - 1
                                if 0 <= choice_index < len(available_profiles):
                                    selected_profile = available_profiles[choice_index]
                                    self.effective_active_auth_json_path = (
                                        selected_profile["path"]
                                    )
                                    logger.info(
                                        f"已选择加载认证文件: {selected_profile['name']}"
                                    )
                                    print(
                                        f"已选择加载: {selected_profile['name']}",
                                        flush=True,
                                    )
                                else:
                                    logger.info(
                                        "无效的选择编号或超时。将不加载认证文件。"
                                    )
                                    print(
                                        "无效的选择编号或超时。将不加载认证文件。",
                                        flush=True,
                                    )
                            except ValueError:
                                logger.info("无效的输入。将不加载认证文件。")
                                print("无效的输入。将不加载认证文件。", flush=True)
                        else:
                            logger.info("好的，不加载认证文件或超时。")
                            print("好的，不加载认证文件或超时。", flush=True)
                        print("-" * 60, flush=True)
                else:
                    logger.info("未找到认证文件。将使用浏览器当前状态。")
                    print("未找到认证文件。将使用浏览器当前状态。", flush=True)
            elif (
                not self.effective_active_auth_json_path
                and not self.args.auto_save_auth
            ):
                # 对于无头模式，如果 --active-auth-json 未提供且 active/ 为空，则报错
                logger.error(
                    f"{self.final_launch_mode} 模式错误: --active-auth-json 未提供，且活动认证目录 '{ACTIVE_AUTH_DIR}' 中未找到任何 '.json' 认证文件。请先在调试模式下保存一个或通过参数指定。"
                )
                sys.exit(1)

    def _setup_helper_mode(self):
        if (
            self.args.helper
        ):  # 如果 args.helper 不是空字符串 (即 helper 功能已通过默认值或用户指定启用)
            logger.info(f"Helper 模式已启用，端点: {self.args.helper}")
            os.environ["HELPER_ENDPOINT"] = self.args.helper  # 设置端点环境变量

            if self.effective_active_auth_json_path:
                logger.info(
                    f"    尝试从认证文件 '{os.path.basename(self.effective_active_auth_json_path)}' 提取 SAPISID..."
                )
                sapisid = ""
                try:
                    with open(
                        self.effective_active_auth_json_path, "r", encoding="utf-8"
                    ) as file:
                        auth_file_data = json.load(file)
                        if "cookies" in auth_file_data and isinstance(
                            auth_file_data["cookies"], list
                        ):
                            for cookie in auth_file_data["cookies"]:
                                if (
                                    isinstance(cookie, dict)
                                    and cookie.get("name") == "SAPISID"
                                    and cookie.get("domain") == ".google.com"
                                ):
                                    sapisid = cookie.get("value", "")
                                    break
                except (
                    FileNotFoundError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                ) as e:
                    logger.warning(
                        f"    无法从认证文件 '{os.path.basename(self.effective_active_auth_json_path)}' 加载或解析SAPISID: {e}"
                    )
                except Exception as e_sapisid_extraction:
                    logger.warning(
                        f"    提取SAPISID时发生未知错误: {e_sapisid_extraction}"
                    )

                if sapisid:
                    logger.info(
                        "    成功加载 SAPISID。将设置 HELPER_SAPISID 环境变量。"
                    )
                    os.environ["HELPER_SAPISID"] = sapisid
                else:
                    logger.warning(
                        f"    未能从认证文件 '{os.path.basename(self.effective_active_auth_json_path)}' 中找到有效的 SAPISID。HELPER_SAPISID 将不会被设置。"
                    )
                    if "HELPER_SAPISID" in os.environ:  # 清理，以防万一
                        del os.environ["HELPER_SAPISID"]
            else:  # args.helper 有值 (Helper 模式启用), 但没有认证文件
                logger.warning(
                    "    Helper 模式已启用，但没有有效的认证文件来提取 SAPISID。HELPER_SAPISID 将不会被设置。"
                )
                if "HELPER_SAPISID" in os.environ:  # 清理
                    del os.environ["HELPER_SAPISID"]
        else:  # args.helper 是空字符串 (用户通过 --helper='' 禁用了 helper)
            logger.debug("[Init] Helper 模式已禁用")
            # 清理相关的环境变量
            if "HELPER_ENDPOINT" in os.environ:
                del os.environ["HELPER_ENDPOINT"]
            if "HELPER_SAPISID" in os.environ:
                del os.environ["HELPER_SAPISID"]

    def _setup_environment_variables(self, captured_ws_endpoint):
        logger.debug("[Init] 步骤 4: 设置环境变量...")

        if captured_ws_endpoint:
            os.environ["CAMOUFOX_WS_ENDPOINT"] = captured_ws_endpoint
        else:
            logger.error("严重逻辑错误: WebSocket 端点未捕获，但程序仍在继续。")
            sys.exit(1)

        os.environ["LAUNCH_MODE"] = self.final_launch_mode
        os.environ["SERVER_LOG_LEVEL"] = self.args.server_log_level.upper()
        if self.args.server_redirect_print:
            os.environ["SERVER_REDIRECT_PRINT"] = "true"
        if self.args.debug_logs:
            os.environ["DEBUG_LOGS_ENABLED"] = "true"
        if self.args.trace_logs:
            os.environ["TRACE_LOGS_ENABLED"] = "true"
        if self.effective_active_auth_json_path:
            os.environ["ACTIVE_AUTH_JSON_PATH"] = self.effective_active_auth_json_path
        if self.args.auto_save_auth:
            os.environ["AUTO_SAVE_AUTH"] = "true"
        if self.args.save_auth_as:
            os.environ["SAVE_AUTH_FILENAME"] = self.args.save_auth_as
        os.environ["AUTH_SAVE_TIMEOUT"] = str(self.args.auth_save_timeout)
        os.environ["SERVER_PORT_INFO"] = str(self.args.server_port)
        os.environ["STREAM_PORT"] = str(self.args.stream_port)

        # 设置统一的代理配置环境变量
        proxy_config = determine_proxy_configuration(self.args.internal_camoufox_proxy)
        if proxy_config["stream_proxy"]:
            os.environ["UNIFIED_PROXY_CONFIG"] = proxy_config["stream_proxy"]
            logger.info(f"设置统一代理配置: {proxy_config['source']}")
        elif "UNIFIED_PROXY_CONFIG" in os.environ:
            del os.environ["UNIFIED_PROXY_CONFIG"]

        host_os_for_shortcut_env = None
        camoufox_os_param_lower = self.simulated_os_for_camoufox.lower()
        if camoufox_os_param_lower == "macos":
            host_os_for_shortcut_env = "Darwin"
        elif camoufox_os_param_lower == "windows":
            host_os_for_shortcut_env = "Windows"
        elif camoufox_os_param_lower == "linux":
            host_os_for_shortcut_env = "Linux"
        if host_os_for_shortcut_env:
            os.environ["HOST_OS_FOR_SHORTCUT"] = host_os_for_shortcut_env
        elif "HOST_OS_FOR_SHORTCUT" in os.environ:
            del os.environ["HOST_OS_FOR_SHORTCUT"]

        logger.debug("[Init] 环境变量配置:")
        env_keys_to_log = [
            "CAMOUFOX_WS_ENDPOINT",
            "LAUNCH_MODE",
            "SERVER_LOG_LEVEL",
            "SERVER_REDIRECT_PRINT",
            "DEBUG_LOGS_ENABLED",
            "TRACE_LOGS_ENABLED",
            "ACTIVE_AUTH_JSON_PATH",
            "AUTO_SAVE_AUTH",
            "SAVE_AUTH_FILENAME",
            "AUTH_SAVE_TIMEOUT",
            "SERVER_PORT_INFO",
            "HOST_OS_FOR_SHORTCUT",
            "HELPER_ENDPOINT",
            "HELPER_SAPISID",
            "STREAM_PORT",
            "UNIFIED_PROXY_CONFIG",  # 新增统一代理配置
        ]
        for key in env_keys_to_log:
            if key in os.environ:
                val_to_log = os.environ[key]
                if key == "CAMOUFOX_WS_ENDPOINT" and len(val_to_log) > 40:
                    val_to_log = val_to_log[:40] + "..."
                if key == "ACTIVE_AUTH_JSON_PATH":
                    val_to_log = os.path.basename(val_to_log)
                logger.debug(f"{key}={val_to_log}")
            else:
                logger.debug(f"{key}= (未设置)")

    def _start_server(self):
        logger.info(
            f"--- 步骤 5: 启动集成的 FastAPI 服务器 (监听端口: {self.args.server_port}) ---"
        )

        if app is None:
            logger.error("无法导入 FastAPI app。请检查 server.py 是否存在且可导入。")
            sys.exit(1)

        if not self.args.exit_on_auth_save:
            try:
                uvicorn.run(
                    app, host="0.0.0.0", port=self.args.server_port, log_config=None
                )
                logger.info("Uvicorn 服务器已停止。")
            except SystemExit as e_sysexit:
                logger.info(f"Uvicorn 或其子系统通过 sys.exit({e_sysexit.code}) 退出。")
            except Exception as e_uvicorn:
                logger.critical(
                    f"运行 Uvicorn 时发生致命错误: {e_uvicorn}", exc_info=True
                )
                sys.exit(1)
        else:
            logger.info("--exit-on-auth-save 已启用。服务器将在认证保存后自动关闭。")

            server_config = uvicorn.Config(
                app, host="0.0.0.0", port=self.args.server_port, log_config=None
            )
            server = uvicorn.Server(server_config)

            stop_watcher = threading.Event()

            def watch_for_saved_auth_and_shutdown():
                os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
                initial_files = set(os.listdir(SAVED_AUTH_DIR))
                logger.info(f"开始监视认证保存目录: {SAVED_AUTH_DIR}")

                while not stop_watcher.is_set():
                    try:
                        current_files = set(os.listdir(SAVED_AUTH_DIR))
                        new_files = current_files - initial_files
                        if new_files:
                            logger.info(
                                f"检测到新的已保存认证文件: {', '.join(new_files)}。将在 3 秒后触发关闭..."
                            )
                            time.sleep(3)
                            server.should_exit = True
                            logger.info("已发送关闭信号给 Uvicorn 服务器。")
                            break
                        initial_files = current_files
                    except Exception as e:
                        logger.error(f"监视认证目录时发生错误: {e}", exc_info=True)

                    if stop_watcher.wait(1):
                        break
                logger.info("认证文件监视线程已停止。")

            watcher_thread = threading.Thread(target=watch_for_saved_auth_and_shutdown)

            try:
                watcher_thread.start()
                server.run()
                logger.info("Uvicorn 服务器已停止。")
            except (KeyboardInterrupt, SystemExit) as e:
                event_name = (
                    "KeyboardInterrupt"
                    if isinstance(e, KeyboardInterrupt)
                    else f"SystemExit({getattr(e, 'code', '')})"
                )
                logger.info(f"接收到 {event_name}，正在关闭...")
            except Exception as e_uvicorn:
                logger.critical(
                    f"运行 Uvicorn 时发生致命错误: {e_uvicorn}", exc_info=True
                )
                sys.exit(1)
            finally:
                stop_watcher.set()
                if watcher_thread.is_alive():
                    watcher_thread.join()


def signal_handler(sig, frame):  # pragma: no cover
    logger.info(f"接收到信号 {signal.Signals(sig).name} ({sig})。正在启动退出程序...")
    # Note: sys.exit(0) will trigger atexit handlers which can hang on multiprocessing cleanup.
    # The cleanup is handled by CamoufoxProcessManager registered via atexit in Launcher.__init__.
    # The multiprocessing module's _exit_function may hang if processes aren't properly terminated.
    # Using os._exit(0) would skip cleanup, so we keep sys.exit(0) and rely on proper cleanup.
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def cleanup():  # pragma: no cover
    # This cleanup is now handled by CamoufoxProcessManager's cleanup method
    # But we need to ensure it's called.
    # Since we don't have a global instance easily accessible here for atexit,
    # we rely on the instance created in main or similar.
    # However, atexit functions don't take arguments.
    # A better approach might be to register the cleanup method of the instance when it's created.
    pass


# We will register the cleanup in the Launcher class or main execution block if needed.
# But CamoufoxProcessManager handles its own cleanup if we call it.
# To ensure cleanup on exit, we can use a global variable for the manager or register it in __init__.
