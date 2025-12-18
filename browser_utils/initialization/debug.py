# --- browser_utils/initialization/debug.py ---
import logging

from playwright.async_api import Page as AsyncPage

logger = logging.getLogger("AIStudioProxyServer")


def setup_debug_listeners(page: AsyncPage) -> None:
    """
    Setup console and network logging listeners for comprehensive error snapshots.

    This function attaches event listeners to capture:
    - Browser console messages (log, warning, error, etc.)
    - Network requests and responses

    Args:
        page: Playwright page instance to attach listeners to
    """
    from datetime import datetime, timezone

    import server

    def handle_console(msg):
        """Handle console messages from the browser."""
        try:
            # Extract location info if available
            location_str = ""
            if msg.location:
                url = msg.location.get("url", "")
                line = msg.location.get("lineNumber", 0)
                if url or line:
                    location_str = f"{url}:{line}"

            server.console_logs.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": msg.type,
                    "text": msg.text,
                    "location": location_str,
                }
            )

            # Log errors to our logger as well
            if msg.type == "error":
                logger.warning(f"[Browser Console Error] {msg.text}")

        except Exception as e:
            logger.error(f"Failed to capture console message: {e}")

    def handle_request(request):
        """Handle network requests."""
        try:
            # Only log relevant requests (skip static assets, images, etc.)
            url_lower = request.url.lower()
            if any(
                ext in url_lower
                for ext in [".png", ".jpg", ".jpeg", ".gif", ".css", ".woff", ".woff2"]
            ):
                return  # Skip static assets

            server.network_log["requests"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "url": request.url,
                    "method": request.method,
                    "resource_type": request.resource_type,
                }
            )
        except Exception as e:
            logger.error(f"Failed to capture network request: {e}")

    def handle_response(response):
        """Handle network responses."""
        try:
            # Only log relevant responses
            url_lower = response.url.lower()
            if any(
                ext in url_lower
                for ext in [".png", ".jpg", ".jpeg", ".gif", ".css", ".woff", ".woff2"]
            ):
                return  # Skip static assets

            server.network_log["responses"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                }
            )
        except Exception as e:
            logger.error(f"Failed to capture network response: {e}")

    # Attach listeners
    page.on("console", handle_console)
    page.on("request", handle_request)
    page.on("response", handle_response)

    logger.debug("Debug listeners (console + network) attached to page")
