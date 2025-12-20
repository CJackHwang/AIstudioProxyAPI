"""
Debug utilities for comprehensive error snapshots and logging.

This module provides enhanced debugging capabilities with:
- Date-based directory structure (errors_py/YYYY-MM-DD/)
- Multiple artifact types (screenshot, DOM dump, console logs, network state)
- Human-readable Texas timestamps
- Complete metadata capture

Purpose: Fix headless mode debugging and client disconnect issues
"""

import asyncio
import json
import logging
import os
import traceback
from asyncio import Lock, Queue
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, Union

from playwright.async_api import Locator
from playwright.async_api import Page as AsyncPage


class SupportsSizeQuery(Protocol):
    """Protocol for queue-like objects that support qsize()."""

    def qsize(self) -> int:
        """Return the approximate size of the queue."""
        ...


class SupportsLockQuery(Protocol):
    """Protocol for lock-like objects that support locked()."""

    def locked(self) -> bool:
        """Return True if the lock is currently held."""
        ...


logger = logging.getLogger("AIStudioProxyServer")


def get_local_timestamp() -> Tuple[str, str]:
    """
    Get current timestamp in both ISO format and human-readable local time.

    Uses the system's local timezone automatically.

    Returns:
        Tuple[str, str]: (iso_format, human_readable_format)
        Example: ("2025-12-20T00:53:35.440", "2025-12-20 00:53:35.440 JST")
    """
    # Get current local time
    local_now = datetime.now().astimezone()

    # ISO format (without timezone suffix for directory naming)
    iso_format = local_now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    # Human-readable format with timezone abbreviation
    human_format = (
        local_now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " " + local_now.strftime("%Z")
    )

    return iso_format, human_format


# Keep alias for backwards compatibility
get_texas_timestamp = get_local_timestamp


async def capture_dom_structure(page: AsyncPage) -> str:
    """
    Capture human-readable DOM tree structure.

    Unlike raw HTML, this provides a clean, indented tree view showing:
    - Element hierarchy
    - IDs and classes
    - Important attributes (disabled, value, etc.)

    Args:
        page: Playwright page instance

    Returns:
        str: Human-readable DOM tree structure
    """
    try:
        dom_tree = await page.evaluate("""() => {
            function getTreeStructure(element, indent = '', depth = 0, maxDepth = 15) {
                // Prevent infinite recursion
                if (depth > maxDepth) {
                    return indent + '... (max depth reached)\\n';
                }

                let result = indent + element.tagName;

                // Add ID
                if (element.id) {
                    result += `#${element.id}`;
                }

                // Add classes
                if (element.className && typeof element.className === 'string') {
                    const classes = element.className.trim().split(/\\s+/).filter(c => c);
                    if (classes.length > 0) {
                        result += '.' + classes.join('.');
                    }
                }

                // Add important attributes
                const importantAttrs = ['aria-label', 'type', 'role', 'data-test-id'];
                for (const attr of importantAttrs) {
                    const val = element.getAttribute(attr);
                    if (val) {
                        result += ` [${attr}="${val}"]`;
                    }
                }

                // Add state attributes
                if (element.disabled !== undefined) {
                    result += ` [disabled=${element.disabled}]`;
                }
                if (element.hasAttribute('aria-disabled')) {
                    result += ` [aria-disabled=${element.getAttribute('aria-disabled')}]`;
                }

                // Add value for input elements (truncated)
                if (element.value && typeof element.value === 'string') {
                    const truncated = element.value.substring(0, 50);
                    const suffix = element.value.length > 50 ? '...' : '';
                    result += ` value="${truncated}${suffix}"`;
                }

                result += '\\n';

                // Recurse for children
                for (let child of element.children) {
                    result += getTreeStructure(child, indent + '  ', depth + 1, maxDepth);
                }

                return result;
            }

            return getTreeStructure(document.body);
        }""")

        return dom_tree
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Failed to capture DOM structure: {e}")
        return f"Error capturing DOM structure: {str(e)}\n"


async def capture_system_context(
    req_id: str = "unknown", error_name: str = "unknown"
) -> Dict[str, Any]:
    """
    Captures the current system global state for debugging context.

    This function gathers critical system metrics, application state (locks, queues),
    and configuration details to help diagnose issues like client disconnects
    or headless mode failures.

    Args:
        req_id: Request ID associated with the context
        error_name: Name of the error triggering the capture

    Returns:
        Dict containing comprehensive system context
    """
    # Import server locally to avoid circular dependency
    import platform
    import sys

    import server

    iso_time, texas_time = get_texas_timestamp()

    # Helper to safely get queue size
    def get_qsize(q: Optional[Union[Queue[Any], SupportsSizeQuery]]) -> int:
        try:
            return q.qsize() if q else -1
        except (NotImplementedError, AttributeError):
            return -1  # Some queue types (like multiprocessing.Queue on macOS) might not support qsize

    # Helper to safely check lock state
    def is_locked(lock: Optional[Union[Lock, SupportsLockQuery]]) -> bool:
        try:
            return lock.locked() if lock else False
        except AttributeError:
            return False

    # Helper to sanitize proxy settings
    def _sanitize_proxy(settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not settings:
            return None
        safe_settings = settings.copy()
        server_val = safe_settings.get("server")
        if isinstance(server_val, str) and "@" in server_val:
            # Redact credentials in http://user:pass@host format
            try:
                parts = server_val.split("@")
                scheme_creds = parts[0].split("://")
                if len(scheme_creds) == 2:
                    safe_settings["server"] = f"{scheme_creds[0]}://***:***@{parts[1]}"
            except Exception:
                safe_settings["server"] = "REDACTED"
        return safe_settings

    context: Dict[str, Any] = {
        "meta": {
            "timestamp_iso": iso_time,
            "timestamp_texas": texas_time,
            "req_id": req_id,
            "error_name": error_name,
        },
        "system": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "pid": os.getpid(),
        },
        "application_state": {
            "flags": {
                "is_playwright_ready": server.is_playwright_ready,
                "is_browser_connected": server.is_browser_connected,
                "is_page_ready": server.is_page_ready,
                "is_initializing": server.is_initializing,
            },
            "queues": {
                "request_queue_size": get_qsize(server.request_queue),
                "stream_queue_active": server.STREAM_QUEUE is not None,
            },
            "locks": {
                "processing_lock_locked": is_locked(server.processing_lock),
                "model_switching_lock_locked": is_locked(server.model_switching_lock),
            },
            "active_model": {
                "current_id": server.current_ai_studio_model_id,
                "excluded_count": len(server.excluded_model_ids),
            },
        },
        "browser_state": {
            "connected": (
                server.browser_instance.is_connected()
                if server.browser_instance
                else False
            ),
            "page_available": (
                not server.page_instance.is_closed() if server.page_instance else False
            ),
        },
        "configuration": {
            "launch_args": {
                "headless": os.environ.get("HEADLESS", "unknown"),
                "debug_logs": os.environ.get("DEBUG_LOGS_ENABLED", "unknown"),
            },
            "proxy_settings": _sanitize_proxy(server.PLAYWRIGHT_PROXY_SETTINGS),
        },
        "recent_activity": {
            "console_logs_count": len(server.console_logs),
            "network_requests_count": len(server.network_log.get("requests", [])),
        },
    }

    # Add snippets of recent logs (last 5)
    if server.console_logs:
        context["recent_activity"]["last_console_logs"] = server.console_logs[-5:]

        # Filter for errors/warnings
        console_errors = [
            log
            for log in server.console_logs
            if str(log.get("type", "")).lower() in ("error", "warning")
        ]
        if console_errors:
            context["recent_activity"]["recent_console_errors"] = console_errors[-5:]

    # Add failed network requests summary
    if server.network_log and "responses" in server.network_log:
        failed_responses = [
            resp
            for resp in server.network_log["responses"]
            if isinstance(resp.get("status"), int) and resp.get("status") >= 400
        ]
        if failed_responses:
            context["recent_activity"]["failed_network_responses"] = failed_responses[
                -5:
            ]

    # Add current page details if available
    if server.page_instance and not server.page_instance.is_closed():
        try:
            context["browser_state"]["current_url"] = server.page_instance.url
        except Exception:
            context["browser_state"]["current_url"] = "error_getting_url"

    return context


async def capture_playwright_state(
    page: AsyncPage, locators: Optional[Dict[str, Locator]] = None
) -> Dict[str, Any]:
    """
    Capture current Playwright page and element states.

    Args:
        page: Playwright page instance
        locators: Optional dict of named locators to inspect
                 Example: {"submit_button": loc, "input_field": loc}

    Returns:
        Dict containing page state and locator states
    """
    state: Dict[str, Any] = {
        "page": {
            "url": page.url,
            "title": "",
            "viewport": page.viewport_size,
        },
        "locators": {},
        "storage": {
            "cookies_count": 0,
            "localStorage_keys": [],
        },
    }

    try:
        state["page"]["title"] = await page.title()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Failed to get page title: {e}")
        state["page"]["title"] = f"Error: {e}"

    # Capture locator states
    if locators:
        for name, locator in locators.items():
            loc_state: Dict[str, Any] = {
                "exists": False,
                "count": 0,
                "visible": False,
                "enabled": False,
                "value": None,
            }

            try:
                loc_state["count"] = await locator.count()
                loc_state["exists"] = loc_state["count"] > 0

                if loc_state["exists"]:
                    # Check visibility with short timeout
                    try:
                        loc_state["visible"] = await locator.is_visible(timeout=1000)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        loc_state["visible"] = False

                    # Check enabled state
                    try:
                        loc_state["enabled"] = await locator.is_enabled(timeout=1000)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        loc_state["enabled"] = False

                    # Try to get value (for input elements)
                    try:
                        value = await locator.input_value(timeout=1000)
                        if value:
                            # Truncate long values
                            loc_state["value"] = (
                                value[:100] + "..." if len(value) > 100 else value
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass  # Not an input element or error

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Failed to capture state for locator '{name}': {e}")
                loc_state["error"] = str(e)

            state["locators"][name] = loc_state

    # Capture storage info
    try:
        cookies = await page.context.cookies()
        state["storage"]["cookies_count"] = len(cookies)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Failed to get cookies: {e}")

    try:
        localStorage_keys = await page.evaluate("() => Object.keys(localStorage)")
        state["storage"]["localStorage_keys"] = localStorage_keys
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Failed to get localStorage keys: {e}")

    return state


async def save_comprehensive_snapshot(
    page: AsyncPage,
    error_name: str,
    req_id: str,
    error_stage: str = "",
    additional_context: Optional[Dict[str, Any]] = None,
    locators: Optional[Dict[str, Locator]] = None,
    error_exception: Optional[Exception] = None,
) -> str:
    """
    Save comprehensive error snapshot with all debugging artifacts.

    Directory structure:
        errors_py/YYYY-MM-DD/HH-MM-SS_reqid_errorname/
            ├── screenshot.png
            ├── dom_dump.html
            ├── dom_structure.txt
            ├── console_logs.txt
            ├── network_requests.json
            ├── playwright_state.json
            └── metadata.json

    Args:
        page: Playwright page instance
        error_name: Base error name (e.g., "stream_post_button_check_disconnect")
        req_id: Request ID
        error_stage: Description of error stage (e.g., "流式响应后按钮状态检查")
        additional_context: Extra context to include in metadata
        locators: Dict of named locators to capture states for
        error_exception: Exception object (if available)

    Returns:
        str: Path to snapshot directory
    """
    # Set request context for grid logging
    from logging_utils import set_request_id

    set_request_id(req_id if req_id else "DEBUG")

    # Check page availability
    if not page or page.is_closed():
        logger.warning(f"Cannot save snapshot ({error_name}), page is unavailable.")
        return ""

    logger.info(f"Saving comprehensive error snapshot ({error_name})...")

    # Get timestamps
    iso_timestamp, human_timestamp = get_texas_timestamp()
    time_component = iso_timestamp.split("T")[1].replace(":", "-").replace(".", "-")

    # Create date-based directory structure
    date_str = iso_timestamp.split("T")[0]  # YYYY-MM-DD
    base_error_dir = Path(__file__).parent.parent / "errors_py"
    date_dir = base_error_dir / date_str
    snapshot_dir_name = f"{time_component}_{req_id}_{error_name}"
    snapshot_dir = date_dir / snapshot_dir_name

    try:
        # Create directory structure
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created snapshot directory: {snapshot_dir}")

        # === 1. Screenshot ===
        screenshot_path = snapshot_dir / "screenshot.png"
        try:
            await page.screenshot(
                path=str(screenshot_path), full_page=True, timeout=15000
            )
            logger.info("Screenshot saved")
        except asyncio.CancelledError:
            raise
        except Exception as ss_err:
            logger.error(f"Screenshot failed: {ss_err}")

        # === 2. HTML Dump ===
        html_path = snapshot_dir / "dom_dump.html"
        try:
            content = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("HTML dump saved")
        except asyncio.CancelledError:
            raise
        except Exception as html_err:
            logger.error(f"HTML dump failed: {html_err}")

        # === 3. DOM Structure (Human-Readable) ===
        dom_structure_path = snapshot_dir / "dom_structure.txt"
        try:
            dom_tree = await capture_dom_structure(page)
            with open(dom_structure_path, "w", encoding="utf-8") as f:
                f.write(dom_tree)
            logger.info("DOM structure saved")
        except asyncio.CancelledError:
            raise
        except Exception as dom_err:
            logger.error(f"DOM structure failed: {dom_err}")

        # === 4. Console Logs ===
        console_logs_path = snapshot_dir / "console_logs.txt"
        try:
            # Get console logs from global state
            from server import console_logs

            if console_logs:
                with open(console_logs_path, "w", encoding="utf-8") as f:
                    f.write("=== Browser Console Logs ===\n\n")
                    for log_entry in console_logs:
                        timestamp = log_entry.get("timestamp", "N/A")
                        log_type = log_entry.get("type", "log")
                        text = log_entry.get("text", "")
                        location = log_entry.get("location", "")

                        f.write(f"[{timestamp}] [{log_type.upper()}] {text}\n")
                        if location:
                            f.write(f"  Location: {location}\n")
                        f.write("\n")

                logger.info(f"Console logs saved ({len(console_logs)} entries)")
            else:
                with open(console_logs_path, "w", encoding="utf-8") as f:
                    f.write("No console logs captured.\n")
                logger.info("No console logs available")
        except Exception as console_err:
            logger.error(f"Console logs failed: {console_err}")

        # === 5. Network Requests ===
        network_path = snapshot_dir / "network_requests.json"
        try:
            from server import network_log

            with open(network_path, "w", encoding="utf-8") as f:
                json.dump(network_log, f, indent=2, ensure_ascii=False)

            req_count = len(network_log.get("requests", []))
            resp_count = len(network_log.get("responses", []))
            logger.info(f"Network log saved ({req_count} reqs, {resp_count} resps)")
        except Exception as net_err:
            logger.error(f"Network log failed: {net_err}")

        # === 6. Playwright State ===
        playwright_state_path = snapshot_dir / "playwright_state.json"
        try:
            pw_state = await capture_playwright_state(page, locators)
            with open(playwright_state_path, "w", encoding="utf-8") as f:
                json.dump(pw_state, f, indent=2, ensure_ascii=False)
            logger.info("Playwright state saved")
        except asyncio.CancelledError:
            raise
        except Exception as pw_err:
            logger.error(f"Playwright state failed: {pw_err}")

        # === 7. System Context (LLM Context) ===
        context_path = snapshot_dir / "llm.json"
        try:
            system_context = await capture_system_context(req_id, error_name)
            with open(context_path, "w", encoding="utf-8") as f:
                json.dump(system_context, f, indent=2, ensure_ascii=False)
            logger.info("LLM context saved")
        except asyncio.CancelledError:
            raise
        except Exception as ctx_err:
            logger.error(f"LLM context failed: {ctx_err}")

        # === 8. Metadata ===
        metadata_path = snapshot_dir / "metadata.json"
        try:
            # Build metadata
            metadata = {
                "req_id": req_id,
                "error_name": error_name,
                "error_stage": error_stage,
                "timestamp": {
                    "iso": iso_timestamp,
                    "human": human_timestamp,
                },
                "headless_mode": os.environ.get("HEADLESS", "true").lower() == "true",
                "launch_mode": os.environ.get("LAUNCH_MODE", "unknown"),
                "environment": {
                    "RESPONSE_COMPLETION_TIMEOUT": os.environ.get(
                        "RESPONSE_COMPLETION_TIMEOUT", "300000"
                    ),
                    "DEBUG_LOGS_ENABLED": os.environ.get(
                        "DEBUG_LOGS_ENABLED", "false"
                    ).lower()
                    == "true",
                    "DEFAULT_MODEL": os.environ.get("DEFAULT_MODEL", "unknown"),
                },
            }

            # Add exception info if available
            if error_exception:
                metadata["exception"] = {
                    "type": type(error_exception).__name__,
                    "message": str(error_exception),
                    "traceback": traceback.format_exc(),
                }

            # Add additional context
            if additional_context:
                metadata["additional_context"] = additional_context

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info("Metadata saved")
        except Exception as meta_err:
            logger.error(f"Metadata failed: {meta_err}")

        # === 9. Human-Readable SUMMARY.txt ===
        summary_path = snapshot_dir / "SUMMARY.txt"
        try:
            summary_lines = [
                "=" * 70,
                "ERROR SNAPSHOT SUMMARY",
                "=" * 70,
                "",
                f"Timestamp: {human_timestamp}",
                f"Request ID: {req_id}",
                f"Error Name: {error_name}",
                f"Error Stage: {error_stage or 'N/A'}",
                "Snapshot Type: COMPREHENSIVE",
                "",
            ]

            # Exception info
            if error_exception:
                summary_lines.extend(
                    [
                        "-" * 70,
                        "EXCEPTION",
                        "-" * 70,
                        f"Type: {type(error_exception).__name__}",
                        f"Message: {error_exception}",
                        "",
                    ]
                )

            # Application state summary
            summary_lines.extend(
                [
                    "-" * 70,
                    "QUICK REFERENCE",
                    "-" * 70,
                    f"Headless Mode: {os.environ.get('HEADLESS', 'true')}",
                    f"Default Model: {os.environ.get('DEFAULT_MODEL', 'unknown')}",
                    "",
                    "-" * 70,
                    "FILES IN THIS SNAPSHOT",
                    "-" * 70,
                    "  SUMMARY.txt        - This file (start here!)",
                    "  screenshot.png     - Full page screenshot",
                    "  dom_dump.html      - Complete HTML source",
                    "  dom_structure.txt  - Human-readable DOM tree",
                    "  console_logs.txt   - Browser console output",
                    "  network_requests.json - Network activity",
                    "  playwright_state.json - Page/locator states",
                    "  llm.json           - System context for AI analysis",
                    "  metadata.json      - Full error details",
                    "",
                    "-" * 70,
                    "DEBUGGING TIPS",
                    "-" * 70,
                    "1. Check screenshot.png for visual state",
                    "2. Search dom_structure.txt for element issues",
                    "3. Review console_logs.txt for JS errors",
                    "4. Check network_requests.json for API failures",
                    "",
                    "=" * 70,
                ]
            )

            with open(summary_path, "w", encoding="utf-8") as f:
                f.write("\n".join(summary_lines))
            logger.info("SUMMARY.txt saved")
        except Exception as summary_err:
            logger.error(f"SUMMARY.txt failed: {summary_err}")

        logger.info(f"Comprehensive snapshot complete: {snapshot_dir.name}")
        return str(snapshot_dir)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Failed to create snapshot directory: {e}", exc_info=True)
        return ""


async def save_error_snapshot_enhanced(
    error_name: str = "error",
    error_exception: Optional[Exception] = None,
    error_stage: str = "",
    additional_context: Optional[Dict[str, Any]] = None,
    locators: Optional[Dict[str, Locator]] = None,
) -> None:
    """
    Enhanced error snapshot function supporting rich context capture.

    This function bridges the simple interface with the comprehensive snapshot system,
    allowing callers to pass exception objects and locator states for debugging.

    Args:
        error_name: Error name with optional req_id suffix (e.g., "clear_chat_error_hbfu521")
        error_exception: The exception that triggered the snapshot (optional)
        error_stage: Description of the error stage (optional)
        additional_context: Extra context dict to include in metadata (optional)
        locators: Dict of named locators to capture states for (optional)
    """
    import server

    # Parse req_id from error_name if present (format: "error_name_req_id")
    name_parts = error_name.split("_")
    req_id = (
        name_parts[-1]
        if len(name_parts) > 1 and len(name_parts[-1]) == 7
        else "unknown"
    )
    base_error_name = error_name if req_id == "unknown" else "_".join(name_parts[:-1])

    page_to_snapshot = server.page_instance

    if (
        not hasattr(server, "browser_instance")
        or not server.browser_instance
        or not server.browser_instance.is_connected()
        or not page_to_snapshot
        or page_to_snapshot.is_closed()
    ):
        logger.warning(
            f"[{req_id}] 浏览器/页面不可用 ({base_error_name})，保存最小化快照..."
        )
        # Fallback to minimal snapshot
        from browser_utils.operations_modules.errors import save_minimal_snapshot

        await save_minimal_snapshot(
            error_name=base_error_name,
            req_id=req_id,
            error_exception=error_exception,
            additional_context=additional_context,
        )
        return

    # Merge additional context with exception info
    merged_context = additional_context.copy() if additional_context else {}

    # Add exception details to context if provided
    if error_exception:
        merged_context["exception_type"] = type(error_exception).__name__
        merged_context["exception_message"] = str(error_exception)
        # Include args if available (some exceptions store useful info here)
        if hasattr(error_exception, "args") and error_exception.args:
            merged_context["exception_args"] = [
                str(a) for a in error_exception.args[:3]
            ]

    # Call comprehensive snapshot with all context
    await save_comprehensive_snapshot(
        page=page_to_snapshot,
        error_name=base_error_name,
        req_id=req_id,
        error_stage=error_stage or "Enhanced snapshot call",
        additional_context=merged_context if merged_context else None,
        locators=locators,
        error_exception=error_exception,
    )
