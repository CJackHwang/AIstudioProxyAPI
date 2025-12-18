# -*- coding: utf-8 -*-
"""
Centralized Error Handling Utilities
=====================================
Provides consistent error logging, global exception handlers, and
optional error snapshot integration for robust debugging.
"""

import asyncio
import logging
import threading
from typing import Optional

from .context import request_id_var, source_var


def log_error(
    logger: logging.Logger,
    message: str,
    exception: Optional[BaseException] = None,
    *,
    save_snapshot: bool = False,
    req_id: str = "",
    exc_info: bool = True,
) -> None:
    """
    Centralized error logging with automatic stack trace capture.

    This function ensures consistent error logging across the codebase:
    - Always includes exc_info for full stack traces
    - Optionally saves error snapshots for debugging
    - Integrates with request context for tracing

    Args:
        logger: Logger instance to use
        message: Error message to log
        exception: Optional exception object (used for snapshot)
        save_snapshot: Whether to save an error snapshot (screenshot, DOM, etc.)
        req_id: Optional request ID override (uses context var if empty)
        exc_info: Whether to include exception info (default True)

    Usage:
        try:
            risky_operation()
        except Exception as e:
            log_error(logger, f"Operation failed: {e}", e, save_snapshot=True)
    """
    # Get request ID from context if not provided
    if not req_id:
        try:
            req_id = request_id_var.get()
        except LookupError:
            req_id = "unknown"

    # Log with exc_info for full stack trace
    logger.error(message, exc_info=exc_info)

    # Save error snapshot if requested
    if save_snapshot:
        try:
            # Lazy import to avoid circular dependencies
            from browser_utils.debug_utils import save_error_snapshot_enhanced

            # Generate error name from message (first 30 chars, sanitized)
            error_name = (
                message[:30].replace(" ", "_").replace(":", "").replace("/", "_")
            )
            # This is async, but we're in sync context - schedule it
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    save_error_snapshot_enhanced(
                        error_name=error_name,
                        error_exception=exception
                        if isinstance(exception, Exception)
                        else None,
                        error_stage="log_error",
                    )
                )
            except RuntimeError:
                # No running event loop - can't save async snapshot
                logger.debug("[Snapshot] 无法保存错误快照: 无运行事件循环")
        except ImportError:
            # debug_utils not available (e.g., in tests or standalone mode)
            pass
        except Exception as snapshot_err:
            # Don't let snapshot failures break the main error handling
            logger.debug(f"[Snapshot] 保存错误快照失败: {snapshot_err}")


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """
    Global asyncio exception handler for uncaught exceptions in tasks.

    This catches exceptions that would otherwise be silently ignored when:
    - A Task raises an exception but is never awaited
    - A callback raises an exception

    Args:
        loop: The event loop that caught the exception
        context: Exception context dict with 'message', 'exception', etc.
    """
    # Skip logging during Python shutdown to avoid ImportError crashes
    import sys

    if sys.meta_path is None or sys.modules is None:
        return

    # Also check if logging module is still available
    try:
        import logging as _check

        del _check
    except (ImportError, TypeError):
        return

    logger = logging.getLogger("AIStudioProxyServer")

    # Extract exception info
    exception = context.get("exception")
    message = context.get("message", "Unhandled exception in asyncio task")

    # Get additional context
    task = context.get("task")
    future = context.get("future")

    # Build detailed error message
    error_parts = [f"[ASYNCIO EXCEPTION] {message}"]

    if task is not None:
        error_parts.append(
            f"Task: {task.get_name() if hasattr(task, 'get_name') else repr(task)}"
        )

    if future is not None and future is not task:
        error_parts.append(f"Future: {repr(future)}")

    # Get source from context if available
    try:
        source = source_var.get()
        error_parts.append(f"Source: {source}")
    except LookupError:
        pass

    try:
        req_id = request_id_var.get()
        if req_id.strip():
            error_parts.append(f"Request ID: {req_id}")
    except LookupError:
        pass

    full_message = " | ".join(error_parts)

    if exception is not None:
        # Log with full traceback
        logger.error(
            full_message, exc_info=(type(exception), exception, exception.__traceback__)
        )
    else:
        logger.error(full_message)


def _threading_exception_handler(args: threading.ExceptHookArgs) -> None:
    """
    Global threading exception handler for uncaught exceptions in threads.

    Args:
        args: ExceptHookArgs containing exc_type, exc_value, exc_traceback, thread
    """
    logger = logging.getLogger("AIStudioProxyServer")

    thread_name = args.thread.name if args.thread else "unknown"

    error_message = f"[THREAD EXCEPTION] Uncaught exception in thread '{thread_name}'"

    if args.exc_value is not None:
        logger.error(
            error_message,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    else:
        logger.error(error_message)


def setup_global_exception_handlers(
    *, install_asyncio: bool = True, install_threading: bool = True
) -> None:
    """
    Install global exception handlers for asyncio and threading.

    This ensures that uncaught exceptions in background tasks and threads
    are properly logged instead of being silently ignored.

    Should be called once during application startup.

    Args:
        install_asyncio: Install asyncio exception handler
        install_threading: Install threading exception handler

    Usage:
        # In application startup
        setup_global_exception_handlers()
    """
    logger = logging.getLogger("AIStudioProxyServer")

    if install_asyncio:
        try:
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(_asyncio_exception_handler)
            logger.debug("[Init] 全局异常处理器已安装 (Asyncio)")
        except RuntimeError:
            # No running event loop yet - will be installed when loop starts
            # This is common during module import
            pass

    if install_threading:
        # Python 3.8+
        if hasattr(threading, "excepthook"):
            threading.excepthook = _threading_exception_handler
            logger.debug("[Init] 全局异常处理器已安装 (Threading)")


def install_asyncio_handler_on_loop(loop: asyncio.AbstractEventLoop) -> None:
    """
    Install the asyncio exception handler on a specific event loop.

    Use this when you need to install the handler after the loop is created.

    Args:
        loop: The event loop to install the handler on
    """
    loop.set_exception_handler(_asyncio_exception_handler)
