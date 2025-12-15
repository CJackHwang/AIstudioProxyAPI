"""
Grid-Based Professional Logging System v2.0
============================================
A verbose but clean logging system with:
- Fixed-width grid layout for perfect column alignment
- Semantic syntax highlighting for values and tokens
- Burst suppression (deduplication) for repeated messages
- Progress indicators that update on the same line
- Thread-safe context variables for request tracking

Author: AI Studio Proxy API
License: MIT
(Refactored: logic moved to logging_utils.core submodules)
"""

from logging_utils.core.constants import (
    SOURCE_MAP,
    Colors,
    Columns,
)
from logging_utils.core.context import (
    request_id_var,
    source_var,
)
from logging_utils.core.logger import (
    AbortErrorFilter,
    BrowserNoiseFilter,
    flush_burst_buffer,
    get_request_id,
    get_source,
    log_context,
    log_object,
    request_context,
    set_request_id,
    set_source,
    setup_grid_logging,
)
from logging_utils.core.rendering import (
    BurstBuffer,
    GridFormatter,
    JSONFormatter,
    PlainGridFormatter,
    ProgressLine,
    SemanticHighlighter,
    _burst_buffer,
    _format_value,
    format_object,
    normalize_source,
)

__all__ = [
    "Colors",
    "Columns",
    "SOURCE_MAP",
    "request_id_var",
    "source_var",
    "SemanticHighlighter",
    "BurstBuffer",
    "_burst_buffer",
    "_format_value",
    "GridFormatter",
    "JSONFormatter",
    "PlainGridFormatter",
    "format_object",
    "log_object",
    "ProgressLine",
    "set_source",
    "set_request_id",
    "get_source",
    "get_request_id",
    "flush_burst_buffer",
    "setup_grid_logging",
    "BrowserNoiseFilter",
    "AbortErrorFilter",
    "log_context",
    "request_context",
    "normalize_source",
]


if __name__ == "__main__":
    import logging
    import random
    import string

    # Setup logging
    logger = setup_grid_logging(level=logging.DEBUG)

    print()
    print("=" * 70)
    print(" GRID LOGGING SYSTEM v2.0 - DEMONSTRATION")
    print("=" * 70)
    print()

    # Generate a random request ID (like your existing system)
    req_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=7))

    # =========================================================================
    # Test 1: Basic logging with source switching
    # =========================================================================

    set_request_id(req_id)
    set_source("API")

    logger.info("Received /v1/chat/completions request (Stream=True)")

    set_source("WORKR")
    logger.info("Processing request logic")
    logger.info("Dequeued request from queue")

    # Use log_context for source switching
    with log_context("UI State Validation", logger):
        logger.info("Temperature matches (0.0). No update needed.")
        logger.info("Max tokens: 8192, Top-P: 0.95")

    with log_context("Model Switching", logger, source="BROWR"):
        logger.info("Current model: 'gemini-1.5-flash'")
        logger.info("Target model: 'gemini-2.0-flash-exp'")
        logger.info("Model switch completed in 1.2s")

    # =========================================================================
    # Test 2: Burst suppression
    # =========================================================================

    print()
    print("-" * 70)
    print(" BURST SUPPRESSION DEMO")
    print("-" * 70)
    print()

    set_source("PROXY")
    set_request_id("       ")

    # Simulate repeated messages
    for _ in range(5):
        logger.info("Sniff HTTPS requests to: aistudio.google.com:443")

    logger.info("Different message - this triggers flush")

    for _ in range(3):
        logger.error("[UPSTREAM ERROR] 429 Too Many Requests")

    logger.warning("Another different message")

    # =========================================================================
    # Test 3: Semantic highlighting
    # =========================================================================

    print()
    print("-" * 70)
    print(" SEMANTIC HIGHLIGHTING DEMO")
    print("-" * 70)
    print()

    set_source("SYS")

    logger.info("Processing True and False values with None")
    logger.info("Temperature: 0.95, max_tokens: 2048, top_p: 0.9")
    logger.info("Loaded model 'gemini-2.0-flash-exp' successfully")
    logger.info("URL: https://aistudio.google.com/prompts")
    logger.warning("Warning: Rate limit approaching")
    logger.error("Error: Connection failed after 3 retries")
    logger.info("Success: Request completed in 150ms")

    # =========================================================================
    # Test 4: Object dumping
    # =========================================================================

    print()
    print("-" * 70)
    print(" OBJECT DUMP DEMO")
    print("-" * 70)
    print()

    data = {
        "model": "gemini-2.0-flash-exp",
        "temperature": 0.7,
        "stream": True,
        "messages": [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ],
    }
    log_object(logger, data, "Request Parameters")

    print()
    print("=" * 70)
    print(" DEMONSTRATION COMPLETE")
    print("=" * 70)
    print()

    # Flush any remaining burst buffer
    flush_burst_buffer()
