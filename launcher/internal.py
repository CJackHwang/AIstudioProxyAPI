import os
import sys
import traceback

from launcher.config import determine_proxy_configuration


def run_internal_camoufox(args, launch_server, DefaultAddons):
    if not launch_server or not DefaultAddons:
        print(
            "致命错误 (--internal-launch-mode): camoufox.server.launch_server 或 camoufox.DefaultAddons 不可用。脚本无法继续。",
            file=sys.stderr,
        )
        sys.exit(1)

    internal_mode_arg = args.internal_launch_mode
    auth_file = args.internal_auth_file
    camoufox_port_internal = args.internal_camoufox_port
    # 使用统一的代理配置确定逻辑
    proxy_config = determine_proxy_configuration(args.internal_camoufox_proxy)
    actual_proxy_to_use = proxy_config["camoufox_proxy"]
    print(f"--- [内部Camoufox启动] 代理配置: {proxy_config['source']} ---", flush=True)

    camoufox_proxy_internal = actual_proxy_to_use  # 更新此变量以供后续使用
    camoufox_os_internal = args.internal_camoufox_os

    print(
        f"--- [内部Camoufox启动] 模式: {internal_mode_arg}, 认证文件: {os.path.basename(auth_file) if auth_file else '无'}, "
        f"Camoufox端口: {camoufox_port_internal}, 代理: {camoufox_proxy_internal or '无'}, 模拟OS: {camoufox_os_internal} ---",
        flush=True,
    )
    print(
        "--- [内部Camoufox启动] 正在调用 camoufox.server.launch_server ... ---",
        flush=True,
    )

    try:
        launch_args_for_internal_camoufox = {
            "port": camoufox_port_internal,
            "addons": [],
            # "proxy": camoufox_proxy_internal, # 已移除
            "exclude_addons": [DefaultAddons.UBO],  # Assuming DefaultAddons.UBO exists
            "window": (1440, 900),
        }

        # 正确添加代理的方式
        if camoufox_proxy_internal:  # 如果代理字符串存在且不为空
            launch_args_for_internal_camoufox["proxy"] = {
                "server": camoufox_proxy_internal
            }
        # 如果 camoufox_proxy_internal 是 None 或空字符串，"proxy" 键就不会被添加。
        if auth_file:
            launch_args_for_internal_camoufox["storage_state"] = auth_file

        if "," in camoufox_os_internal:
            camoufox_os_list_internal = [
                s.strip().lower() for s in camoufox_os_internal.split(",")
            ]
            valid_os_values = ["windows", "macos", "linux"]
            if not all(val in valid_os_values for val in camoufox_os_list_internal):
                print(
                    f"内部Camoufox启动错误: camoufox_os_internal 列表中包含无效值: {camoufox_os_list_internal}",
                    file=sys.stderr,
                )
                sys.exit(1)
            launch_args_for_internal_camoufox["os"] = camoufox_os_list_internal
        elif camoufox_os_internal.lower() in ["windows", "macos", "linux"]:
            launch_args_for_internal_camoufox["os"] = camoufox_os_internal.lower()
        elif camoufox_os_internal.lower() != "random":
            print(
                f"内部Camoufox启动错误: camoufox_os_internal 值无效: '{camoufox_os_internal}'",
                file=sys.stderr,
            )
            sys.exit(1)

        print(
            f"传递给 launch_server 的参数: {launch_args_for_internal_camoufox}",
            flush=True,
        )

        if internal_mode_arg == "headless":
            launch_server(headless=True, **launch_args_for_internal_camoufox)
        elif internal_mode_arg == "virtual_headless":
            launch_server(headless="virtual", **launch_args_for_internal_camoufox)
        elif internal_mode_arg == "debug":
            launch_server(headless=False, **launch_args_for_internal_camoufox)

        print(
            f"--- [内部Camoufox启动] camoufox.server.launch_server ({internal_mode_arg}模式) 调用已完成/阻塞。脚本将等待其结束。 ---",
            flush=True,
        )
    except Exception as e_internal_launch_final:
        print(
            f"错误 (--internal-launch-mode): 执行 camoufox.server.launch_server 时发生异常: {e_internal_launch_final}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
