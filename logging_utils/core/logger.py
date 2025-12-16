"""
Core Logger Module
"""

import logging
import sys
from contextlib import contextmanager
from typing import Any, Generator, Optional

from colorama import init as colorama_init

from logging_utils.core.context import (
    request_id_var,
    source_var,
)
from logging_utils.core.rendering import (
    GridFormatter,
    _burst_buffer,
    format_object,
)

# =============================================================================
# Logging Filters
# =============================================================================


class BrowserNoiseFilter(logging.Filter):
    """Filter out benign browser noise (AbortError, CORS, Google logging, SSL)."""

    # Patterns to filter out
    NOISE_PATTERNS = [
        "AbortError: The operation was aborted",  # Playwright navigation cancellation
        "Cross-Origin Request Blocked",  # CORS errors (usually harmless)
        "play.google.com/log",  # Google's internal logging endpoint
        "APPLICATION_DATA_AFTER_CLOSE_NOTIFY",  # SSL shutdown warning (harmless)
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to drop the log record, True to keep it."""
        message = record.getMessage()
        for pattern in self.NOISE_PATTERNS:
            if pattern in message:
                return False
        return True


# Legacy alias for backwards compatibility
AbortErrorFilter = BrowserNoiseFilter


# =============================================================================
# Context Managers
# =============================================================================


@contextmanager
def log_context(
    name: str,
    logger: Optional[logging.Logger] = None,
    source: Optional[str] = None,
    silent: bool = False,
) -> Generator[None, None, None]:
    """
    Context manager for source switching (simplified - no tree tracking).

    Usage:
        with log_context("Processing request", logger):
            logger.info("Step 1")

    With silent=True, no header is logged:
        with log_context("", logger, silent=True):
            logger.info("Some work")
    """
    if logger is None:
        logger = logging.getLogger()

    # Handle optional source change
    source_token = None
    if source is not None:
        source_token = source_var.set(source)

    # Log the context entry (unless silent)
    if not silent and name:
        logger.info(name)

    try:
        yield
    finally:
        # Restore previous source
        if source_token is not None:
            source_var.reset(source_token)


@contextmanager
def request_context(
    request_id: str, source: str = "WORKR"
) -> Generator[None, None, None]:
    """
    Context manager for request lifecycle.

    Sets request ID and source for all logs within the context.

    Usage:
        with request_context("akvdate", source="WORKR"):
            logger.info("Processing...")
    """
    # Set context variables
    id_token = request_id_var.set(request_id)
    source_token = source_var.set(source)

    try:
        yield
    finally:
        # Reset context variables
        request_id_var.reset(id_token)
        source_var.reset(source_token)


# =============================================================================
# Convenience Functions
# =============================================================================


def set_source(source: str) -> None:
    """Set the source identifier for subsequent logs."""
    source_var.set(source)


def set_request_id(request_id: str) -> None:
    """Set the request ID for subsequent logs."""
    request_id_var.set(request_id)


def get_source() -> str:
    """Get the current source identifier."""
    try:
        return source_var.get()
    except LookupError:
        return "SYS"


def get_request_id() -> str:
    """Get the current request ID."""
    try:
        return request_id_var.get()
    except LookupError:
        return "       "


def flush_burst_buffer() -> None:
    """Flush any remaining burst-suppressed messages."""
    result = _burst_buffer.flush()
    if result:
        print(result)


def log_object(
    logger: logging.Logger, obj: Any, label: str = "Data", level: int = logging.INFO
) -> None:
    """
    Log an object with YAML-style formatting.

    Args:
        logger: Logger instance to use
        obj: Object to dump (dict, list, etc.)
        label: Label for the data block
        level: Logging level to use
    """
    logger.log(level, f"{label}:")
    formatted = format_object(obj, indent=1)
    for line in formatted.split("\n"):
        if line.strip():
            logger.log(level, line)


# =============================================================================
# Logger Setup
# =============================================================================


def setup_grid_logging(
    level: int = logging.DEBUG,
    show_tree: bool = True,
    colorize: bool = True,
    burst_suppression: bool = True,
    logger_name: Optional[str] = None,
) -> logging.Logger:
    """
    Configure the logging system with grid formatting.

    Args:
        level: Logging level (default: DEBUG)
        show_tree: Whether to show tree structure (default: True)
        colorize: Whether to apply colors (default: True)
        burst_suppression: Whether to suppress duplicate messages (default: True)
        logger_name: Optional logger name (default: root logger)

    Returns:
        Configured logger instance
    """
    # Initialize colorama
    colorama_init(autoreset=False)

    # Get logger
    if logger_name:
        logger = logging.getLogger(logger_name)
    else:
        logger = logging.getLogger()

    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Apply grid formatter
    formatter = GridFormatter(
        show_tree=show_tree, colorize=colorize, burst_suppression=burst_suppression
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger
