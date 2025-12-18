"""
Rendering Logic for Grid Logger
"""

import logging
import re
import sys
import threading
import time
from datetime import datetime
from typing import Any, List, Optional, Tuple

from colorama import Fore, Style

from .constants import SOURCE_MAP, Colors, Columns
from .context import (
    request_id_var,
    source_var,
)


def normalize_source(source: str) -> str:
    """Normalize source name to fixed 5-letter code."""
    key = source.lower().replace(" ", "_").replace("-", "_")
    if key in SOURCE_MAP:
        return SOURCE_MAP[key]
    # Try partial match
    for map_key, map_val in SOURCE_MAP.items():
        if map_key in key or key in map_key:
            return map_val
    # Default: first 5 chars, uppercase, padded
    return source[:5].upper().ljust(5)


# =============================================================================
# Semantic Highlighter (Enhanced)
# =============================================================================


class SemanticHighlighter:
    """Applies semantic coloring to log message content."""

    # Compiled regex patterns for efficiency
    TAG_PATTERN = re.compile(r"^\[([A-Z]{2,10})\]\s*")
    STRING_PATTERN = re.compile(r"'([^']*)'|\"([^\"]*)\"")
    BOOLEAN_PATTERN = re.compile(r"\b(True|False|None)\b")
    NUMBER_PATTERN = re.compile(r"\b(\d+\.?\d*(?:ms|s|kb|mb|gb|KB|MB|GB|%|px)?)\b")
    HEX_PATTERN = re.compile(r"\b(0x[0-9a-fA-F]+)\b")
    URL_PATTERN = re.compile(
        r"(https?://[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s]*)?)"
    )
    # Key phrases to bold
    PHRASE_ERROR = re.compile(r"\b(Error|ERROR|error)\b")
    PHRASE_FAILED = re.compile(r"\b(Failed|FAILED|failed|Failure|failure)\b")
    PHRASE_SUCCESS = re.compile(
        r"\b(Success|SUCCESS|success|Successful|successful|Complete|complete|Completed|completed)\b"
    )
    PHRASE_WARNING = re.compile(r"\b(Warning|WARNING|warning)\b")
    # Status phrases - Success patterns (Green)
    PHRASE_MATCHES = re.compile(r"\((Matches page|Cached|Matches)\)")
    # Status phrases - Action patterns (Yellow)
    PHRASE_UPDATING = re.compile(r"\((Updating|Toggling|Loading)\.\.\.\)")
    # Model IDs (gemini-*, claude-*, etc.)
    MODEL_ID_PATTERN = re.compile(
        r"\b(gemini-[\w.-]+|claude-[\w.-]+|gpt-[\w.-]+|veo-[\w.-]+)\b"
    )
    # Request IDs (7-char alphanumeric)
    REQ_ID_PATTERN = re.compile(r"\b([a-z0-9]{7})\b")

    @classmethod
    def highlight(cls, text: str, colorize: bool = True) -> str:
        """Apply semantic highlighting to text."""
        if not colorize:
            return text

        result = text

        # Handle tags at the start (e.g., [UI], [NET], [SYS])
        tag_match = cls.TAG_PATTERN.match(result)
        if tag_match:
            full_tag = tag_match.group(0)
            tag_name = tag_match.group(1)
            # Use source color if available, otherwise use TAG color
            normalized = normalize_source(tag_name)
            tag_color = Colors.SOURCES.get(normalized, Colors.TAG)
            colored_tag = f"{tag_color}[{tag_name}]{Colors.RESET} "
            result = colored_tag + result[len(full_tag) :]

        # Highlight URLs first (before strings, to avoid conflict)
        def replace_url(match: re.Match[str]) -> str:
            return f"{Colors.URL}{Style.DIM}{match.group(1)}{Colors.RESET}"

        result = cls.URL_PATTERN.sub(replace_url, result)

        # Highlight model IDs
        def replace_model_id(match: re.Match[str]) -> str:
            return f"{Colors.STRING}{match.group(1)}{Colors.RESET}"

        result = cls.MODEL_ID_PATTERN.sub(replace_model_id, result)

        # Highlight quoted strings
        def replace_string(match: re.Match[str]) -> str:
            # Match group 1 is single-quote, group 2 is double-quote
            content = match.group(1) if match.group(1) else match.group(2)
            quote = "'" if match.group(1) else '"'
            return f"{Colors.STRING}{quote}{content}{quote}{Colors.RESET}"

        result = cls.STRING_PATTERN.sub(replace_string, result)

        # Highlight booleans with distinct colors
        def replace_boolean(match: re.Match[str]) -> str:
            val = match.group(1)
            if val == "True":
                return f"{Colors.BOOLEAN_TRUE}{val}{Colors.RESET}"
            elif val == "False":
                return f"{Colors.BOOLEAN_FALSE}{val}{Colors.RESET}"
            else:  # None
                return f"{Colors.BOOLEAN_NONE}{val}{Colors.RESET}"

        result = cls.BOOLEAN_PATTERN.sub(replace_boolean, result)

        # Highlight numbers (avoid matching inside ANSI codes)
        def replace_number(match: re.Match[str]) -> str:
            return f"{Colors.NUMBER}{match.group(1)}{Colors.RESET}"

        result = cls.NUMBER_PATTERN.sub(replace_number, result)

        # Highlight hex numbers
        def replace_hex(match: re.Match[str]) -> str:
            return f"{Colors.NUMBER}{match.group(1)}{Colors.RESET}"

        result = cls.HEX_PATTERN.sub(replace_hex, result)

        # Bold key phrases
        def replace_error(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_ERROR}{match.group(1)}{Colors.RESET}"

        result = cls.PHRASE_ERROR.sub(replace_error, result)

        def replace_failed(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_FAILED}{match.group(1)}{Colors.RESET}"

        result = cls.PHRASE_FAILED.sub(replace_failed, result)

        def replace_success(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_SUCCESS}{match.group(1)}{Colors.RESET}"

        result = cls.PHRASE_SUCCESS.sub(replace_success, result)

        def replace_warning(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_WARNING}{match.group(1)}{Colors.RESET}"

        result = cls.PHRASE_WARNING.sub(replace_warning, result)

        # Highlight status phrases - Success (Green)
        def replace_matches(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_SUCCESS}{match.group(0)}{Colors.RESET}"

        result = cls.PHRASE_MATCHES.sub(replace_matches, result)

        # Highlight status phrases - Action (Yellow)
        def replace_updating(match: re.Match[str]) -> str:
            return f"{Colors.PHRASE_WARNING}{match.group(0)}{Colors.RESET}"

        result = cls.PHRASE_UPDATING.sub(replace_updating, result)

        return result


# =============================================================================
# Burst Suppression State (Thread-safe)
# =============================================================================


class BurstBuffer:
    """
    Thread-safe buffer for burst suppression.

    Tracks duplicate log messages and suppresses them, appending
    a count like (x3) when a different message arrives.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_key: Optional[str] = None
        self._last_formatted: Optional[str] = None
        self._count: int = 0

    def process(
        self, key: str, formatted_line: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Process a log entry for burst suppression.

        Args:
            key: Unique key for the log (source + message)
            formatted_line: The fully formatted log line

        Returns:
            Tuple of (line_to_print_now, deferred_line_if_any)
            - If same as last: returns (None, None) - suppressed
            - If different: returns (last_with_count_if_needed, current_line)
        """
        with self._lock:
            if self._last_key is None:
                # First message
                self._last_key = key
                self._last_formatted = formatted_line
                self._count = 1
                return (formatted_line, None)

            if key == self._last_key:
                # Duplicate - suppress and increment counter
                self._count += 1
                return (None, None)
            else:
                # Different message - flush previous with count
                prev_line = self._last_formatted
                prev_count = self._count

                # Update to new message
                self._last_key = key
                self._last_formatted = formatted_line
                self._count = 1

                if prev_count > 1 and prev_line:
                    # Create a dim footnote line instead of appending count
                    # Extract timestamp/level/source/id columns from prev_line to align properly
                    # Format: "                  └─ (Repeated N times)"
                    indent = (
                        " " * 31
                    )  # Align with message column (timestamp + level + source + id + spaces)
                    count_line = f"{indent}{Colors.TREE}\u2514\u2500 {Colors.BURST_COUNT}(Repeated {prev_count} times){Colors.RESET}"
                    # Return previous line (without count), count line, and current line
                    return (f"{prev_line}\n{count_line}", formatted_line)
                else:
                    # Previous was single, just print current
                    return (formatted_line, None)

    def flush(self) -> Optional[str]:
        """Flush any remaining buffered message."""
        with self._lock:
            if self._last_formatted and self._count > 1:
                # Create footnote line for repeated message
                indent = " " * 31
                count_line = f"{indent}{Colors.TREE}\u2514\u2500 {Colors.BURST_COUNT}(Repeated {self._count} times){Colors.RESET}"
                result = f"{self._last_formatted}\n{count_line}"
                self._last_key = None
                self._last_formatted = None
                self._count = 0
                return result
            # Don't return anything if count <= 1 (no repetition to report)
            self._last_key = None
            self._last_formatted = None
            self._count = 0
            return None


# Global burst buffer instance
_burst_buffer = BurstBuffer()


# =============================================================================
# Grid Formatter
# =============================================================================


class GridFormatter(logging.Formatter):
    """
    Fixed-width grid formatter with semantic highlighting and burst suppression.

    Format: TIME | LVL | SOURCE | ID | MESSAGE

    Example output:
    22:47:51.690 INF API   y74ebn9 Received /v1/chat/completions request
    22:47:51.692 INF WORKR y74ebn9 Processing request logic...
    22:47:51.695 INF PROXY         Sniff HTTPS requests (x5)
    """

    def __init__(
        self,
        colorize: bool = True,
        burst_suppression: bool = True,
        show_tree: bool = True,  # Deprecated, kept for compatibility
    ):
        super().__init__()
        self.colorize = colorize
        self.burst_suppression = burst_suppression

    def format(self, record: logging.LogRecord) -> str:
        """Format log record into grid layout."""
        # Skip during Python shutdown to avoid ImportError
        if sys.meta_path is None:
            return record.getMessage()

        # Extract context variables with defaults
        try:
            req_id = request_id_var.get()
        except LookupError:
            req_id = "       "

        try:
            source = source_var.get()
        except LookupError:
            source = "SYS"

        # Normalize source to 5-letter code
        source_normalized = normalize_source(source)

        # Column 1: Time (HH:MM:SS.mmm) - no date
        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}"
        if self.colorize:
            time_col = f"{Colors.TIME}{timestamp}{Colors.RESET}"
        else:
            time_col = timestamp

        # Column 2: Level (3 chars)
        level_abbrev = Colors.LEVEL_ABBREV.get(
            record.levelname, record.levelname[:3].upper()
        )
        if self.colorize:
            level_color = Colors.LEVELS.get(record.levelname, Fore.WHITE)
            level_col = f"{level_color}{level_abbrev}{Colors.RESET}"
        else:
            level_col = level_abbrev

        # Column 3: Source (fixed 5-char width)
        if self.colorize:
            source_color = Colors.SOURCES.get(source_normalized, Fore.WHITE)
            source_col = f"{source_color}{source_normalized}{Colors.RESET}"
        else:
            source_col = source_normalized

        # Column 4: Request ID (fixed 7-char width)
        id_display = req_id[: Columns.ID].ljust(Columns.ID)
        if self.colorize:
            id_col = f"{Colors.REQUEST_ID}{id_display}{Colors.RESET}"
        else:
            id_col = id_display

        # Column 6: Message with semantic highlighting
        message = record.getMessage()

        # Skip separator lines (dashed lines)
        if message.strip().startswith("---") or message.strip().startswith("==="):
            # Skip separator lines entirely
            return ""

        if self.colorize:
            message = SemanticHighlighter.highlight(message)

        # Combine all columns
        line = f"{time_col} {level_col} {source_col} {id_col} {message}"

        # Apply burst suppression
        if self.burst_suppression:
            # Create key from source + original message (pre-highlight)
            burst_key = f"{source_normalized}:{record.getMessage()}"
            prev_line, current_line = _burst_buffer.process(burst_key, line)

            if prev_line is None and current_line is None:
                # Suppressed - return empty string (won't be printed)
                return ""
            elif current_line is None:
                # Just the previous (with count if needed)
                return prev_line or ""
            elif prev_line:
                # Both lines - print previous then current
                return f"{prev_line}\n{current_line}"
            else:
                # Just current
                return current_line

        return line


# =============================================================================
# Plain Formatter (for file/WebSocket - no ANSI codes)
# =============================================================================


class PlainGridFormatter(logging.Formatter):
    """Plain-text grid formatter for file/WebSocket logging (no ANSI codes)."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record into plain text grid layout."""
        try:
            req_id = request_id_var.get()
        except LookupError:
            req_id = "       "

        try:
            source = source_var.get()
        except LookupError:
            source = "SYS"

        source_normalized = normalize_source(source)

        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}"

        level_abbrev = Colors.LEVEL_ABBREV.get(
            record.levelname, record.levelname[:3].upper()
        )

        id_display = req_id[: Columns.ID].ljust(Columns.ID)
        message = record.getMessage()

        # Skip separator lines
        if message.strip().startswith("---") or message.strip().startswith("==="):
            return ""

        return f"{timestamp} {level_abbrev} {source_normalized} {id_display} {message}"


# =============================================================================
# Object Dumper (YAML-style)
# =============================================================================


def format_object(obj: Any, indent: int = 0, colorize: bool = True) -> str:
    """
    Format an object in YAML-style for clean logging.

    Args:
        obj: The object to format (dict, list, or primitive)
        indent: Current indentation level
        colorize: Whether to apply colors

    Returns:
        Formatted string representation
    """
    lines: List[str] = []
    prefix = "  " * indent

    if isinstance(obj, dict):
        for key, value in obj.items():  # pyright: ignore[reportUnknownVariableType]
            key_str = (
                f"{Colors.KEY}{key}{Colors.RESET}" if colorize else str(key)  # pyright: ignore[reportUnknownArgumentType]
            )
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{prefix}{key_str}:")
                lines.append(format_object(value, indent + 1, colorize))
            else:
                formatted_value = _format_value(value, colorize)
                lines.append(f"{prefix}{key_str}: {formatted_value}")
    elif isinstance(obj, list):
        for item in obj:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{prefix}-")
                lines.append(format_object(item, indent + 1, colorize))
            else:
                formatted_value = _format_value(item, colorize)
                lines.append(f"{prefix}- {formatted_value}")
    else:
        lines.append(f"{prefix}{_format_value(obj, colorize)}")

    return "\n".join(lines)


def _format_value(value: Any, colorize: bool = True) -> str:
    """Format a single value with appropriate coloring."""
    if not colorize:
        if isinstance(value, str):
            return f"'{value}'"
        return str(value)

    if isinstance(value, bool):
        if value:
            return f"{Colors.BOOLEAN_TRUE}{value}{Colors.RESET}"
        else:
            return f"{Colors.BOOLEAN_FALSE}{value}{Colors.RESET}"
    elif isinstance(value, (int, float)):
        return f"{Colors.NUMBER}{value}{Colors.RESET}"
    elif isinstance(value, str):
        # Truncate long strings
        if len(value) > 50:
            truncated = value[:47] + "..."
            return f"{Colors.STRING}'{truncated}'{Colors.RESET}"
        return f"{Colors.STRING}'{value}'{Colors.RESET}"
    elif value is None:
        return f"{Colors.BOOLEAN_NONE}None{Colors.RESET}"
    else:
        return f"{Colors.STRING}{repr(value)}{Colors.RESET}"


# =============================================================================
# Progress Indicator
# =============================================================================


class ProgressLine:
    """
    Progress indicator that updates on the same line.

    Uses carriage return (\\r) to overwrite the previous output
    instead of creating new log lines.

    Usage:
        progress = ProgressLine("Waiting for stream")
        for i in range(100):
            progress.update(i + 1, 100, f"chunks: {i + 1}")
            time.sleep(0.05)
        progress.finish("Complete")
    """

    def __init__(self, message: str, source: Optional[str] = None):
        """
        Initialize progress indicator.

        Args:
            message: Base message to display
            source: Optional source override (uses context var if None)
        """
        self.message = message
        self.source = source
        self.last_update = 0.0
        self._started = False
        self._min_interval = 0.05  # Minimum time between updates (50ms)

    def update(self, current: int, total: int, extra: str = "") -> None:
        """
        Update progress on the same line.

        Args:
            current: Current progress value
            total: Total value for 100%
            extra: Additional info to display after progress bar
        """
        now = time.time()

        # Rate limit updates to avoid flickering
        if now - self.last_update < self._min_interval and current < total:
            return

        self.last_update = now
        self._started = True

        # Get context
        try:
            req_id = request_id_var.get()
        except LookupError:
            req_id = "       "

        source = self.source
        if source is None:
            try:
                source = source_var.get()
            except LookupError:
                source = "SYS"

        source_normalized = normalize_source(source)

        # Build timestamp
        timestamp = (
            datetime.now().strftime("%H:%M:%S.") + f"{int(now * 1000) % 1000:03d}"
        )

        # Calculate progress
        percentage = (current / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "#" * filled + "-" * (bar_width - filled)

        extra_text = f" {extra}" if extra else ""

        # Build the line with colors
        source_color = Colors.SOURCES.get(source_normalized, Fore.WHITE)
        line = (
            f"\r{Colors.TIME}{timestamp}{Colors.RESET} "
            f"{Colors.LEVELS['INFO']}INF{Colors.RESET} "
            f"{source_color}{source_normalized}{Colors.RESET} "
            f"{Colors.REQUEST_ID}{req_id:<{Columns.ID}}{Colors.RESET} "
            f"{Colors.MESSAGE}{self.message} [{bar}] "
            f"{Colors.NUMBER}{current}{Colors.RESET}/{Colors.NUMBER}{total}{Colors.RESET} "
            f"({Colors.NUMBER}{percentage:.0f}%{Colors.RESET}){extra_text}"
        )

        # Clear to end of line and print
        sys.stdout.write(f"{line}\033[K")
        sys.stdout.flush()

    def finish(self, message: Optional[str] = None) -> None:
        """
        Complete the progress and move to new line.

        Args:
            message: Optional completion message
        """
        if self._started:
            if message:
                sys.stdout.write(f" - {Colors.STRING}{message}{Colors.RESET}")
            sys.stdout.write("\n")
            sys.stdout.flush()


# =============================================================================
# JSON Formatter (Structured Logging)
# =============================================================================


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs as JSON lines for easy parsing by log aggregation tools
    like ELK, Datadog, CloudWatch, etc.

    Enable via JSON_LOGS=true environment variable.

    Format:
    {"timestamp": "2024-12-15T15:30:00.123Z", "level": "ERROR", "source": "API",
     "request_id": "abc1234", "message": "...", "exception": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import json
        from datetime import timezone

        # Get context variables
        try:
            req_id = request_id_var.get()
        except LookupError:
            req_id = ""

        try:
            source = source_var.get()
        except LookupError:
            source = "SYS"

        source_normalized = normalize_source(source)

        # Build timestamp in ISO 8601 format with milliseconds
        now = datetime.now(timezone.utc)
        timestamp = (
            now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}Z"
        )

        # Base log entry
        log_entry: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "source": source_normalized.strip(),
            "message": record.getMessage(),
        }

        # Add request ID if present
        if req_id and req_id.strip():
            log_entry["request_id"] = req_id.strip()

        # Add logger name
        if record.name:
            log_entry["logger"] = record.name

        # Add exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            import traceback as tb

            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": "".join(tb.format_exception(*record.exc_info)),
            }

        # Add extra fields from record
        # Common extra fields that might be useful
        for key in ("funcName", "lineno", "pathname"):
            value = getattr(record, key, None)
            if value:
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False, default=str)
