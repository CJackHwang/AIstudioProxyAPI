"""
Tests for api_utils/context_init.py - Request context initialization.

Test Strategy:
- Test initialize_request_context with various configurations
- Use REAL asyncio.Lock instances (not AsyncMock)
- Use real server_state module
- Mock only logging side effects
- Test context dictionary construction with actual values

Coverage Target: 95%+
Mock Budget: <40 (down from 95)
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from api_utils.context_init import initialize_request_context
from api_utils.server_state import state


class TestInitializeRequestContext:
    """Tests for initialize_request_context function."""

    @pytest.mark.asyncio
    async def test_streaming_request_context(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test context initialization for streaming request."""
        # Set up server state
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {"temperature": 1.0}
        state.parsed_model_list = [
            {"id": "gemini-1.5-pro", "object": "model"},
            {"id": "gemini-1.5-flash", "object": "model"},
        ]

        request = make_chat_request(model="gemini-1.5-pro", stream=True)

        with patch("api_utils.server_state.state.logger", MagicMock()) as mock_logger:
            context = await initialize_request_context("req1", request)

            # Verify logging - now uses debug, not info
            assert mock_logger.debug.call_count >= 1
            log_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("[Request]" in msg for msg in log_calls)

            # Verify context fields
            assert context["is_streaming"] is True
            assert context["requested_model"] == "gemini-1.5-pro"
            assert context["current_ai_studio_model_id"] == "gemini-1.5-pro"
            assert context["is_page_ready"] is True
            assert context["page"] == real_locks_mock_browser.page_instance
            assert context["model_actually_switched"] is False
            assert context["needs_model_switching"] is False
            assert context["model_id_to_use"] is None

            # Verify real locks
            assert isinstance(context["model_switching_lock"], asyncio.Lock)
            assert isinstance(context["params_cache_lock"], asyncio.Lock)

    @pytest.mark.asyncio
    async def test_non_streaming_request_context(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test context initialization for non-streaming request."""
        state.current_ai_studio_model_id = "gemini-1.5-flash"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request(model="gemini-1.5-flash", stream=False)

        with patch("api_utils.server_state.state.logger", MagicMock()) as mock_logger:
            context = await initialize_request_context("req2", request)

            # Verify streaming flag
            assert context["is_streaming"] is False
            assert context["requested_model"] == "gemini-1.5-flash"

            # Verify logging uses debug
            log_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("Stream=False" in msg for msg in log_calls)

    @pytest.mark.asyncio
    async def test_different_model_name(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test context with different model name."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request(model="gemini-2.0-flash-thinking-exp")

        with patch("api_utils.server_state.state.logger", MagicMock()) as mock_logger:
            context = await initialize_request_context("req3", request)

            assert context["requested_model"] == "gemini-2.0-flash-thinking-exp"

            # Verify logging includes model name in debug call
            log_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("gemini-2.0-flash-thinking-exp" in msg for msg in log_calls)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "is_ready,expected",
        [
            (True, True),
            (False, False),
        ],
    )
    async def test_page_ready_states(
        self, real_locks_mock_browser, make_chat_request, is_ready, expected
    ):
        """Test context with different page ready states."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = is_ready
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req4", request)

            assert context["is_page_ready"] == expected

    @pytest.mark.asyncio
    async def test_none_current_model(self, real_locks_mock_browser, make_chat_request):
        """Test context when current model ID is None (initial state)."""
        state.current_ai_studio_model_id = None
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req5", request)

            assert context["current_ai_studio_model_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cache_value",
        [
            {},
            {"temperature": 0.7, "max_tokens": 1024},
            {"last_known_model_id_for_params": "gemini-1.5-pro"},
        ],
    )
    async def test_various_params_caches(
        self, real_locks_mock_browser, make_chat_request, cache_value
    ):
        """Test context with various parameter cache states."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = cache_value
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req6", request)

            assert context["page_params_cache"] == cache_value

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "model_list",
        [
            [],
            [{"id": "gemini-1.5-pro", "object": "model"}],
            [
                {"id": "gemini-1.5-pro", "object": "model"},
                {"id": "gemini-1.5-flash", "object": "model"},
                {"id": "gemini-2.0-flash", "object": "model"},
            ],
        ],
    )
    async def test_various_model_lists(
        self, real_locks_mock_browser, make_chat_request, model_list
    ):
        """Test context with various model lists."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = model_list

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req7", request)

            assert context["parsed_model_list"] == model_list

    @pytest.mark.asyncio
    async def test_context_includes_all_required_fields(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test that context includes all required fields."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req8", request)

            # Verify all required keys exist
            required_keys = [
                "logger",
                "page",
                "is_page_ready",
                "parsed_model_list",
                "current_ai_studio_model_id",
                "model_switching_lock",
                "page_params_cache",
                "params_cache_lock",
                "is_streaming",
                "model_actually_switched",
                "requested_model",
                "model_id_to_use",
                "needs_model_switching",
            ]

            for key in required_keys:
                assert key in context, f"Missing required key: {key}"

            # Verify default flag values
            assert context["model_actually_switched"] is False
            assert context["model_id_to_use"] is None
            assert context["needs_model_switching"] is False

    @pytest.mark.asyncio
    async def test_context_return_type_is_dict(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test that context is returned as a dictionary."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req9", request)

            assert isinstance(context, dict)

    @pytest.mark.asyncio
    async def test_logger_message_format(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test logger message format includes request details."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request(model="test-model-123", stream=True)

        with patch("api_utils.server_state.state.logger", MagicMock()) as mock_logger:
            await initialize_request_context("test-req-abc", request)

            # Verify log messages use debug, not info
            log_calls = [call[0][0] for call in mock_logger.debug.call_args_list]

            # Log should include [Request] tag and model/stream parameters
            assert any("[Request]" in msg for msg in log_calls)
            assert any("test-model-123" in msg for msg in log_calls)
            assert any("Stream=True" in msg for msg in log_calls)

    @pytest.mark.asyncio
    async def test_locks_are_real_asyncio_locks(
        self, real_locks_mock_browser, make_chat_request
    ):
        """Test that locks in context are real asyncio.Lock instances."""
        state.current_ai_studio_model_id = "gemini-1.5-pro"
        state.is_page_ready = True
        state.page_instance = real_locks_mock_browser.page_instance
        state.model_switching_lock = real_locks_mock_browser.model_switching_lock
        state.params_cache_lock = real_locks_mock_browser.params_cache_lock
        state.page_params_cache = {}
        state.parsed_model_list = []

        request = make_chat_request()

        with patch("api_utils.server_state.state.logger", MagicMock()):
            context = await initialize_request_context("req10", request)

            # Verify locks are real asyncio.Lock instances
            assert isinstance(context["model_switching_lock"], asyncio.Lock)
            assert isinstance(context["params_cache_lock"], asyncio.Lock)

            # Verify locks can be acquired
            async with context["model_switching_lock"]:
                assert context["model_switching_lock"].locked()
            assert not context["model_switching_lock"].locked()

            async with context["params_cache_lock"]:
                assert context["params_cache_lock"].locked()
            assert not context["params_cache_lock"].locked()
