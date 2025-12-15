# 日志设置功能
# Grid logging system v2.0
from .core.error_handler import (
    install_asyncio_handler_on_loop,
    log_error,
    setup_global_exception_handlers,
)
from .grid_logger import (
    # Source mapping
    SOURCE_MAP,
    # Classes
    AbortErrorFilter,
    BrowserNoiseFilter,
    BurstBuffer,
    Colors,
    Columns,
    GridFormatter,
    # JSON formatter for structured logging
    JSONFormatter,
    PlainGridFormatter,
    ProgressLine,
    SemanticHighlighter,
    # Utility functions
    flush_burst_buffer,
    format_object,
    get_request_id,
    get_source,
    # Context managers
    log_context,
    log_object,
    normalize_source,
    request_context,
    # Context variables
    request_id_var,
    set_request_id,
    set_source,
    setup_grid_logging,
    source_var,
)
from .setup import restore_original_streams, setup_server_logging

__all__ = [
    # Legacy setup
    "setup_server_logging",
    "restore_original_streams",
    # Grid logger
    "setup_grid_logging",
    "GridFormatter",
    "PlainGridFormatter",
    "AbortErrorFilter",
    "BrowserNoiseFilter",
    "Colors",
    "Columns",
    "SemanticHighlighter",
    "ProgressLine",
    "BurstBuffer",
    # Context managers
    "log_context",
    "request_context",
    # Context variables
    "request_id_var",
    "source_var",
    # Source mapping
    "SOURCE_MAP",
    "normalize_source",
    # Utility functions
    "set_source",
    "set_request_id",
    "get_source",
    "get_request_id",
    "format_object",
    "log_object",
    "flush_burst_buffer",
    # JSON formatter
    "JSONFormatter",
    # Error handling utilities
    "log_error",
    "setup_global_exception_handlers",
    "install_asyncio_handler_on_loop",
]
