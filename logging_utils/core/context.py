"""
Logging Context Variables
"""

from contextvars import ContextVar

# =============================================================================
# Context Variables (Thread-safe request tracking)
# =============================================================================

# Request ID for the current context (e.g., 'akvdate')
request_id_var: ContextVar[str] = ContextVar("request_id", default="       ")

# Source identifier for the current context (e.g., 'SERVER', 'PROXY')
source_var: ContextVar[str] = ContextVar("source", default="SYS")
