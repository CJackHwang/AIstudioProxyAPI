# --- browser_utils/initialization/auth.py ---
"""
认证保存模块 - 简化版

处理登录后的认证状态保存。自动保存到 SAVED_AUTH_DIR。
"""

import asyncio
import logging
import os
import time

from config import SAVED_AUTH_DIR

logger = logging.getLogger("AIStudioProxyServer")


async def wait_for_model_list_and_handle_auth_save(temp_context, launch_mode, loop):
    """等待模型列表响应并处理认证保存"""
    import server

    # 等待模型列表响应，确认登录成功
    logger.info("等待模型列表响应以确认登录成功...")
    try:
        await asyncio.wait_for(server.model_list_fetch_event.wait(), timeout=30.0)
        logger.info("检测到模型列表响应，登录确认成功！")
    except asyncio.TimeoutError:
        logger.warning("等待模型列表响应超时，但继续处理认证保存...")

    # Determine filename: env var > auto-generate
    filename = os.environ.get("SAVE_AUTH_FILENAME", "").strip()
    if not filename:
        filename = f"auth_auto_{int(time.time())}"

    await _save_auth_state(temp_context, filename)


async def _save_auth_state(temp_context, filename: str):
    """统一的认证保存函数"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)

    if not filename.endswith(".json"):
        filename += ".json"
    auth_save_path = os.path.join(SAVED_AUTH_DIR, filename)

    print("\n" + "=" * 50, flush=True)
    print("登录成功！将自动保存认证状态...", flush=True)

    try:
        await temp_context.storage_state(path=auth_save_path)
        logger.info(f"认证状态已保存到: {auth_save_path}")
        print(f"认证状态已保存到: {auth_save_path}", flush=True)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"保存认证状态失败: {e}", exc_info=True)
        print(f"保存认证状态失败: {e}", flush=True)

    print("=" * 50 + "\n", flush=True)
