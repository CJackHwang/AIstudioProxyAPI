import base64
import json
import queue
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from api_utils.utils_ext.files import (
    _extension_for_mime,
    extract_data_url_to_local,
    save_blob_to_local,
)
from api_utils.utils_ext.helper import use_helper_get_response
from api_utils.utils_ext.stream import clear_stream_queue, use_stream_response
from api_utils.utils_ext.tokens import calculate_usage_stats, estimate_tokens
from api_utils.utils_ext.validation import validate_chat_request
from models import Message

# --- tokens.py tests ---


def test_estimate_tokens():
    """Test token estimation for empty, English, Chinese, and mixed text."""
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0  # type: ignore[arg-type]

    # English: 1 char = 0.25 tokens -> 4 chars = 1 token
    assert estimate_tokens("abcd") == 1

    # Chinese: 1 char = 0.66 tokens -> 3 chars = 2 tokens (approx)
    # Actually logic is: chinese_tokens = chars / 1.5
    # "你好" (2 chars) -> 2/1.5 = 1.33 -> 1 token
    # "你好吗" (3 chars) -> 3/1.5 = 2.0 -> 2 tokens
    assert estimate_tokens("你好吗") == 2

    # Mixed
    # "hi你好" -> 2 eng + 2 chi
    # eng: 2/4 = 0.5
    # chi: 2/1.5 = 1.33
    # total: 1.83 -> 1 token
    assert estimate_tokens("hi你好") == 1


def test_calculate_usage_stats():
    """Test token usage statistics calculation for messages and responses."""
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    response = "response"
    reasoning = "reasoning"

    stats = calculate_usage_stats(messages, response, reasoning)

    assert "prompt_tokens" in stats
    assert "completion_tokens" in stats
    assert "total_tokens" in stats
    assert stats["total_tokens"] == stats["prompt_tokens"] + stats["completion_tokens"]


# --- validation.py tests ---


def test_validate_chat_request_valid():
    """Test validation passes with valid system and user messages."""
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="user"),
    ]
    result = validate_chat_request(messages, "req1")
    assert result["error"] is None


def test_validate_chat_request_empty():
    """Test validation raises error for empty message array."""
    with pytest.raises(ValueError, match="数组缺失或为空"):
        validate_chat_request([], "req1")


def test_validate_chat_request_only_system():
    """Test validation raises error when all messages are system messages."""
    messages = [Message(role="system", content="sys")]
    with pytest.raises(ValueError, match="所有消息都是系统消息"):
        validate_chat_request(messages, "req1")


# --- files.py tests ---


def test_extension_for_mime():
    """Test file extension detection from MIME types."""
    assert _extension_for_mime("image/png") == ".png"
    assert _extension_for_mime("application/unknown") == ".unknown"
    assert _extension_for_mime("plain") == ".bin"
    assert _extension_for_mime(None) == ".bin"  # type: ignore[arg-type]


def test_extract_data_url_to_local_success():
    """Test successful extraction of data URL to local file."""
    data = b"hello world"
    b64_data = base64.b64encode(data).decode()
    data_url = f"data:text/plain;base64,{b64_data}"

    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()) as mock_file,
    ):
        path = extract_data_url_to_local(data_url, "req1")

        assert path is not None
        assert path.endswith(".txt")
        mock_file().write.assert_called_with(data)


def test_extract_data_url_to_local_invalid_format():
    """Test data URL extraction fails gracefully with invalid format."""
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        assert extract_data_url_to_local("invalid-url") is None
        mock_logger.error.assert_called()


def test_extract_data_url_to_local_bad_b64():
    """Test data URL extraction handles base64 decode errors."""
    import binascii

    with (
        patch("logging.getLogger") as mock_get_logger,
        patch("base64.b64decode", side_effect=binascii.Error("Invalid")),
    ):
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        assert extract_data_url_to_local("data:text/plain;base64,!!!") is None
        mock_logger.error.assert_called()


def test_extract_data_url_to_local_exists():
    """Test data URL extraction when file already exists."""
    data_url = "data:text/plain;base64,AAAA"
    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
    ):
        path = extract_data_url_to_local(data_url)
        assert path is not None


def test_save_blob_to_local():
    """Test saving blob data to local file with various extensions."""
    data = b"test"
    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
    ):
        # Test with mime
        path = save_blob_to_local(data, mime_type="image/png")
        assert path is not None
        assert path.endswith(".png")

        # Test with ext
        path = save_blob_to_local(data, fmt_ext=".jpg")
        assert path is not None
        assert path.endswith(".jpg")

        # Test fallback
        path = save_blob_to_local(data)
        assert path is not None
        assert path.endswith(".bin")


# --- helper.py tests ---


@pytest.mark.asyncio
async def test_use_helper_get_response_success():
    with patch("server.logger"), patch("aiohttp.ClientSession") as MockSession:

        async def mock_iter_chunked(n):
            yield b"chunk1"
            yield b"chunk2"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content.iter_chunked = MagicMock(side_effect=mock_iter_chunked)

        # session.get is NOT awaited, it returns a context manager immediately.
        # AsyncMock method would return a coroutine. So we use MagicMock for .get
        mock_session = AsyncMock()
        mock_session.get = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        # ClientSession() returns a context manager.
        # We ensure the context manager returns our mock_session
        MockSession.return_value.__aenter__.return_value = mock_session

        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_use_helper_get_response_error():
    with (
        patch("server.logger") as mock_logger,
        patch("aiohttp.ClientSession") as MockSession,
    ):
        mock_resp = AsyncMock()
        mock_resp.status = 500

        mock_session = AsyncMock()
        mock_session.get = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        MockSession.return_value.__aenter__.return_value = mock_session

        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_use_helper_get_response_exception():
    with (
        patch("server.logger") as mock_logger,
        patch("aiohttp.ClientSession", side_effect=Exception("Network Error")),
    ):
        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.error.assert_called()


# --- stream.py tests ---


@pytest.mark.asyncio
async def test_use_stream_response_success():
    # Setup queue data
    q_data = [
        json.dumps({"body": "chunk1", "done": False}),
        json.dumps({"body": "chunk2", "done": True}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data + [queue.Empty()]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0]["body"] == "chunk1"
        assert chunks[1]["done"] is True


@pytest.mark.asyncio
async def test_use_stream_response_queue_none():
    with patch("server.STREAM_QUEUE", None), patch("server.logger") as mock_logger:
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.warning.assert_called_with("STREAM_QUEUE is None, 无法使用流响应")


@pytest.mark.asyncio
async def test_use_stream_response_timeout():
    # Simulate queue empty until timeout
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = queue.Empty

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger"),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should yield timeout error
        assert len(chunks) == 1
        assert chunks[0]["reason"] == "internal_timeout"
        assert chunks[0]["done"] is True
        # Should have slept around 299 times (300 retries, sleep after each fail except last check)
        assert mock_sleep.call_count >= 299


@pytest.mark.asyncio
async def test_use_stream_response_mixed_types():
    # Test non-JSON string and dictionary data
    q_data = [
        "not-json",  # Should trigger JSONDecodeError path
        {"body": "dict-body", "done": False},  # Dictionary directly
        json.dumps({"body": "final", "done": True}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0] == "not-json"
        assert chunks[1]["body"] == "dict-body"
        assert chunks[2]["done"] is True


@pytest.mark.asyncio
async def test_use_stream_response_ignore_stale_done():
    # First item is done=True with no content (stale), should be ignored
    # Second item is real content
    # Third item is real done
    q_data = [
        json.dumps({"done": True, "body": "", "reason": ""}),
        json.dumps({"body": "real content", "done": False}),
        json.dumps({"done": True, "body": "", "reason": ""}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should contain 2 items: real content and final done. Stale done ignored.
        assert len(chunks) == 2
        assert chunks[0]["body"] == "real content"
        assert chunks[1]["done"] is True


@pytest.mark.asyncio
async def test_clear_stream_queue():
    mock_queue = MagicMock()
    # 2 items then Empty
    mock_queue.get_nowait.side_effect = ["item1", "item2", queue.Empty]

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
        patch("asyncio.to_thread", side_effect=mock_queue.get_nowait),
    ):
        await clear_stream_queue()

        # Should have called get_nowait 3 times via to_thread
        # Verify debug log for queue cleared
        debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("队列已清空" in c or "[Stream]" in c for c in debug_calls)


@pytest.mark.asyncio
async def test_clear_stream_queue_none():
    with patch("server.STREAM_QUEUE", None), patch("server.logger") as mock_logger:
        await clear_stream_queue()
        mock_logger.debug.assert_called_with("[Stream] 队列未初始化或已禁用，跳过清空")


"""
Extended tests for api_utils/utils_ext/stream.py - Edge case coverage.

Focus: Cover uncovered error paths, exception handling, and edge cases.
Strategy: Test None signal, error detection, dict stale data, exceptions.
"""

from models.exceptions import QuotaExceededError, UpstreamError


@pytest.mark.asyncio
async def test_use_stream_response_none_signal():
    """
    测试场景: 接收到 None 作为流结束信号
    预期: 正常结束,不返回任何内容 (lines 28-30)
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [None]  # None 是结束信号

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 0  # None 信号不产生任何输出


@pytest.mark.asyncio
async def test_use_stream_response_quota_exceeded_error():
    """
    测试场景: 接收到 quota 错误信号 (status 429)
    预期: 抛出 QuotaExceededError (lines 44-65)
    """
    error_data = json.dumps(
        {"error": True, "status": 429, "message": "Quota exceeded for this project"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(QuotaExceededError) as exc_info:
            async for chunk in use_stream_response("req1"):
                pass

        assert "AI Studio quota exceeded" in str(exc_info.value)
        assert exc_info.value.req_id == "req1"


@pytest.mark.asyncio
async def test_use_stream_response_quota_error_by_message():
    """
    测试场景: 错误信息包含 "quota" 关键字
    预期: 抛出 QuotaExceededError (lines 58-65)
    """
    error_data = json.dumps(
        {"error": True, "status": 500, "message": "Your project quota has been reached"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(QuotaExceededError):
            async for chunk in use_stream_response("req1"):
                pass


@pytest.mark.asyncio
async def test_use_stream_response_upstream_error():
    """
    测试场景: 接收到非 quota 的上游错误 (status 500)
    预期: 抛出 UpstreamError (lines 66-74)
    """
    error_data = json.dumps(
        {"error": True, "status": 500, "message": "Internal server error"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(UpstreamError) as exc_info:
            async for chunk in use_stream_response("req1"):
                pass

        assert "AI Studio error" in str(exc_info.value)
        # status_code is stored in context dict, not direct attribute
        assert exc_info.value.context.get("status_code") == 500


@pytest.mark.asyncio
async def test_use_stream_response_dict_with_stale_done():
    """
    测试场景: 字典格式数据,第一个是 stale done (无内容)
    预期: Yields stale done, continues instead of breaking (lines 116-129)
    Note: Dict format ALWAYS yields first (line 109), then checks stale.
    """
    q_data = [
        {"done": True, "body": "", "reason": ""},  # Stale done (dict format)
        {"body": "real content", "done": False},  # Real data
        {"done": True, "body": "final", "reason": ""},  # Real done
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Dict always yields first, so all 3 chunks yielded
        # But stale detection prevents breaking on first done
        assert len(chunks) == 3
        assert chunks[0]["done"] is True  # Stale done yielded
        assert chunks[1]["body"] == "real content"
        assert chunks[2]["done"] is True  # Real done

        # Verify stale warning was logged (line 124)
        warning_calls = [
            c for c in mock_logger.warning.call_args_list if "STALE DATA" in str(c)
        ]
        assert len(warning_calls) > 0


@pytest.mark.asyncio
async def test_use_stream_response_timeout_after_data():
    """
    测试场景: 接收部分数据后超时
    预期: 记录警告并返回超时信号 (line 144)
    """
    q_data = [
        json.dumps({"body": "some data", "done": False}),
    ] + [queue.Empty] * 301  # 先收到数据,然后一直空

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should have data chunk + timeout chunk
        assert len(chunks) == 2
        assert chunks[0]["body"] == "some data"
        assert chunks[1]["reason"] == "internal_timeout"

        # Verify warning was logged (line 144)
        warning_calls = [
            c
            for c in mock_logger.warning.call_args_list
            if "空读取次数达到上限" in str(c)
        ]
        assert len(warning_calls) > 0


@pytest.mark.asyncio
async def test_use_stream_response_generic_exception():
    """
    测试场景: 在处理过程中发生异常
    预期: 记录错误并重新抛出 (lines 156-158)
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = RuntimeError("Unexpected error")

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        with pytest.raises(RuntimeError, match="Unexpected error"):
            async for chunk in use_stream_response("req1"):
                pass

        # Verify error was logged (line 157)
        error_calls = [
            c for c in mock_logger.error.call_args_list if "使用流响应时出错" in str(c)
        ]
        assert len(error_calls) > 0


@pytest.mark.asyncio
async def test_clear_stream_queue_exception_during_clear():
    """
    测试场景: 清空队列时发生异常
    预期: 记录错误并停止清空 (lines 189-194)
    """
    mock_queue = MagicMock()
    # Get 2 items, then raise exception
    mock_queue.get_nowait.side_effect = ["item1", "item2", RuntimeError("Queue error")]

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        await clear_stream_queue()

        # Should have gotten 2 items before exception
        assert mock_queue.get_nowait.call_count == 3

        # Verify error was logged (line 190-193)
        error_calls = [
            c
            for c in mock_logger.error.call_args_list
            if "清空流式队列时发生意外错误" in str(c)
        ]
        assert len(error_calls) > 0
        assert "已清空2项" in error_calls[0][0][0]


@pytest.mark.asyncio
async def test_clear_stream_queue_empty_queue():
    """
    测试场景: 清空一个空队列
    预期: 记录信息日志
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = queue.Empty  # Immediately empty

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
        patch("asyncio.to_thread", side_effect=queue.Empty),
    ):
        await clear_stream_queue()

        # Verify debug log for empty queue cleared
        debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("队列已清空" in c or "[Stream]" in c for c in debug_calls)


"""
Extended tests for api_utils/utils_ext/files.py - Final coverage completion.

Focus: Cover lines 78-80 (IOError in extract_data_url_to_local),
       107-108 (file exists in save_blob_to_local),
       114-116 (IOError in save_blob_to_local).
Strategy: Mock file operations to trigger error paths.
"""


def test_extract_data_url_to_local_write_failure():
    """
    测试场景: 写入文件时发生 IOError
    预期: 记录错误,返回 None (lines 78-80)
    """
    data = b"test data"
    b64_data = base64.b64encode(data).decode()
    data_url = f"data:text/plain;base64,{b64_data}"

    with (
        patch("logging.getLogger") as mock_get_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", side_effect=IOError("Disk full")),
    ):
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        # 执行
        result = extract_data_url_to_local(data_url, "req1")

        # 验证: 返回 None (line 80)
        assert result is None

        # 验证: logger.error 被调用 (line 79)
        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "保存文件失败" in error_msg
        assert "Disk full" in error_msg


def test_save_blob_to_local_file_exists():
    """
    测试场景: 文件已存在,跳过保存
    预期: 记录日志,返回文件路径 (lines 106-108)
    """
    data = b"binary data"

    with (
        patch("logging.getLogger") as mock_get_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),  # 文件存在
    ):
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        # 执行
        result = save_blob_to_local(data, mime_type="image/png", req_id="req1")

        # 验证: 返回路径 (line 108)
        assert result is not None
        assert result.endswith(".png")

        # 验证: logger.info 被调用 (line 107)
        mock_logger.info.assert_called()
        info_msg = mock_logger.info.call_args[0][0]
        assert "文件已存在，跳过保存" in info_msg


def test_save_blob_to_local_write_failure():
    """
    测试场景: 写入二进制文件时发生 IOError
    预期: 记录错误,返回 None (lines 114-116)
    """
    data = b"test binary"

    with (
        patch("logging.getLogger") as mock_get_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", side_effect=IOError("Permission denied")),
    ):
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        # 执行
        result = save_blob_to_local(data, mime_type="application/pdf")

        # 验证: 返回 None (line 116)
        assert result is None

        # 验证: logger.error 被调用 (line 115)
        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "保存二进制失败" in error_msg
        assert "Permission denied" in error_msg
