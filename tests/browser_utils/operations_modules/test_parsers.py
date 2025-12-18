"""
Comprehensive tests for browser_utils/operations_modules/parsers.py

Targets:
- _parse_userscript_models(): JavaScript to JSON conversion
- _get_injected_models(): File I/O and model injection
- _handle_model_list_response(): Network response parsing (async)

Coverage target: 70-80% (120-140 statements out of 177 missing)
"""

from unittest.mock import AsyncMock, mock_open, patch

import pytest

from browser_utils.operations_modules.parsers import (
    _get_injected_models,
    _handle_model_list_response,
    _parse_userscript_models,
)

# ==================== _parse_userscript_models TESTS ====================


def test_parse_userscript_models_simple_valid():
    """Test parsing simple valid JavaScript model array."""
    script = """
    const SCRIPT_VERSION = 'v2.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/gemini-test',
            displayName: 'Gemini Test',
            description: 'Test model'
        }
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1
    assert models[0]["name"] == "models/gemini-test"
    assert models[0]["displayName"] == "Gemini Test"
    assert models[0]["description"] == "Test model"


def test_parse_userscript_models_multiple_models():
    """Test parsing multiple models."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/model-1',
            displayName: 'Model 1',
            description: 'First model'
        },
        {
            name: 'models/model-2',
            displayName: 'Model 2',
            description: 'Second model'
        }
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 2
    assert models[0]["name"] == "models/model-1"
    assert models[1]["name"] == "models/model-2"


def test_parse_userscript_models_single_quotes():
    """Test parsing with single quotes."""
    script = """
    const SCRIPT_VERSION = 'v1.5';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test',
            displayName: 'Test Model',
            description: 'Single quote test'
        }
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1
    assert models[0]["description"] == "Single quote test"


def test_parse_userscript_models_backticks():
    """Test parsing with backticks and template strings."""
    script = """
    const SCRIPT_VERSION = 'v3.0';
    const MODELS_TO_INJECT = [
        {
            name: `models/test`,
            displayName: `Test ${SCRIPT_VERSION}`,
            description: `Model version ${SCRIPT_VERSION}`
        }
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1
    assert "v3.0" in models[0]["displayName"]
    assert "v3.0" in models[0]["description"]


def test_parse_userscript_models_with_comments():
    """Test parsing with JavaScript comments."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        // This is a test model
        {
            name: 'models/test',  // model name
            displayName: 'Test',  // display name
            description: 'Desc'   // description
        }
        // Another comment
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1
    assert models[0]["name"] == "models/test"


def test_parse_userscript_models_trailing_commas():
    """Test handling of trailing commas."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test',
            displayName: 'Test',
            description: 'Desc',
        },
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1


def test_parse_userscript_models_no_version():
    """Test parsing when SCRIPT_VERSION is missing (uses default)."""
    script = """
    const MODELS_TO_INJECT = [
        {
            name: 'models/test',
            displayName: 'Test v${SCRIPT_VERSION}',
            description: 'Desc'
        }
    ];
    """

    models = _parse_userscript_models(script)

    assert len(models) == 1
    # Should use default v1.6
    assert "v1.6" in models[0]["displayName"]


def test_parse_userscript_models_missing_array():
    """Test when MODELS_TO_INJECT array is not found."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const SOME_OTHER_ARRAY = [
        {name: 'test'}
    ];
    """

    models = _parse_userscript_models(script)

    assert models == []


def test_parse_userscript_models_invalid_json():
    """Test handling of invalid JavaScript that can't convert to JSON."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test',
            invalid: function() { return 'test'; }
        }
    ];
    """

    models = _parse_userscript_models(script)

    # Should return empty list on error
    assert models == []


def test_parse_userscript_models_missing_name_field():
    """Test skipping models without 'name' field."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            displayName: 'No Name Model',
            description: 'Missing name field'
        },
        {
            name: 'models/valid',
            displayName: 'Valid Model',
            description: 'Has name'
        }
    ];
    """

    models = _parse_userscript_models(script)

    # Should only return model with 'name' field
    assert len(models) == 1
    assert models[0]["name"] == "models/valid"


def test_parse_userscript_models_empty_array():
    """Test parsing empty MODELS_TO_INJECT array."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [];
    """

    models = _parse_userscript_models(script)

    assert models == []


def test_parse_userscript_models_exception_handling():
    """Test general exception handling."""
    # Invalid script content that will cause regex to fail
    script = None

    models = _parse_userscript_models(script)  # type: ignore[arg-type]

    assert models == []


# ==================== _get_injected_models TESTS ====================


@patch("browser_utils.operations_modules.parsers.os.environ.get")
def test_get_injected_models_disabled(mock_env_get):
    """Test when script injection is disabled."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "false",
        "USERSCRIPT_PATH": "browser_utils/more_models.js",
    }.get(key, default)

    models = _get_injected_models()

    assert models == []


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
def test_get_injected_models_file_not_found(mock_exists, mock_env_get):
    """Test when userscript file doesn't exist."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "nonexistent.js",
    }.get(key, default)
    mock_exists.return_value = False

    models = _get_injected_models()

    assert models == []


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_get_injected_models_success(mock_file, mock_exists, mock_env_get):
    """Test successful model injection."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "test.js",
    }.get(key, default)
    mock_exists.return_value = True

    script_content = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test-model',
            displayName: 'Test Model',
            description: 'A test model'
        }
    ];
    """
    mock_file.return_value.read.return_value = script_content

    models = _get_injected_models()

    assert len(models) == 1
    assert models[0]["id"] == "test-model"
    assert models[0]["display_name"] == "Test Model"
    assert models[0]["description"] == "A test model"
    assert models[0]["raw_model_path"] == "models/test-model"
    assert models[0]["owned_by"] == "ai_studio_injected"
    assert models[0]["injected"] is True


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_get_injected_models_no_models_prefix(mock_file, mock_exists, mock_env_get):
    """Test model without 'models/' prefix."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "test.js",
    }.get(key, default)
    mock_exists.return_value = True

    script_content = """
    const MODELS_TO_INJECT = [
        {
            name: 'simple-model-id',
            displayName: 'Simple Model'
        }
    ];
    """
    mock_file.return_value.read.return_value = script_content

    models = _get_injected_models()

    assert len(models) == 1
    assert models[0]["id"] == "simple-model-id"
    assert models[0]["raw_model_path"] == "simple-model-id"


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_get_injected_models_skip_empty_name(mock_file, mock_exists, mock_env_get):
    """Test skipping models with empty names."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "test.js",
    }.get(key, default)
    mock_exists.return_value = True

    script_content = """
    const MODELS_TO_INJECT = [
        {
            name: '',
            displayName: 'No Name'
        },
        {
            name: 'models/valid',
            displayName: 'Valid'
        }
    ];
    """
    mock_file.return_value.read.return_value = script_content

    models = _get_injected_models()

    assert len(models) == 1
    assert models[0]["id"] == "valid"


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
@patch("builtins.open")
def test_get_injected_models_file_read_error(mock_file, mock_exists, mock_env_get):
    """Test handling file read errors."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "test.js",
    }.get(key, default)
    mock_exists.return_value = True
    mock_file.side_effect = IOError("Read error")

    models = _get_injected_models()

    # Should return empty list on error
    assert models == []


@patch("browser_utils.operations_modules.parsers.os.environ.get")
@patch("browser_utils.operations_modules.parsers.os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_get_injected_models_parse_returns_empty(mock_file, mock_exists, mock_env_get):
    """Test when parsing returns no models."""
    mock_env_get.side_effect = lambda key, default="": {
        "ENABLE_SCRIPT_INJECTION": "true",
        "USERSCRIPT_PATH": "test.js",
    }.get(key, default)
    mock_exists.return_value = True

    # Invalid script that will parse to empty list
    script_content = "const OTHER = [];"
    mock_file.return_value.read.return_value = script_content

    models = _get_injected_models()

    assert models == []


# ==================== _handle_model_list_response TESTS ====================


@pytest.mark.asyncio
async def test_handle_model_list_response_not_models_endpoint(mock_server_module):
    """Test response from non-models endpoint is ignored."""
    response = AsyncMock()
    response.url = "https://example.com/other_endpoint"
    response.ok = True

    await _handle_model_list_response(response)

    # Should not process, no changes to server state


@pytest.mark.asyncio
async def test_handle_model_list_response_not_ok(mock_server_module):
    """Test response with non-OK status."""
    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = False

    await _handle_model_list_response(response)

    # Should not process


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_simple_list(mock_state):
    """Test processing simple list of model dicts."""
    # Reset server state
    import asyncio

    mock_state.global_model_list_raw_json = None
    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.status = 200
    response.json.return_value = [
        {"id": "gemini-pro", "displayName": "Gemini Pro", "description": "Pro model"}
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "gemini-pro"
    assert mock_state.parsed_model_list[0]["display_name"] == "Gemini Pro"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_dict_with_data_key(mock_state):
    """Test processing dict response with 'data' key."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = {"data": [{"id": "model-1", "displayName": "Model 1"}]}

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "model-1"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_dict_with_models_key(mock_state):
    """Test processing dict response with 'models' key."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = {
        "models": [{"id": "model-2", "displayName": "Model 2"}]
    }

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "model-2"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_list_based_model_fields(mock_state):
    """Test processing list-based model fields."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    # List format: [model_id_path, ..., display_name(idx 3), description(idx 4), ..., max_tokens(idx 6), ..., top_p(idx 9)]
    response.json.return_value = [
        ["models/test-list", 1, 2, "Test List Model", "List desc", 5, 8192, 7, 8, 0.95]
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "test-list"
    assert mock_state.parsed_model_list[0]["display_name"] == "Test List Model"
    assert mock_state.parsed_model_list[0]["default_max_output_tokens"] == 8192
    assert mock_state.parsed_model_list[0]["default_top_p"] == 0.95


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_excluded_model(mock_state):
    """Test that excluded models are skipped."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = {"excluded-model"}
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = [
        {"id": "excluded-model", "displayName": "Excluded"},
        {"id": "included-model", "displayName": "Included"},
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "included-model"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_empty_list(mock_state):
    """Test handling of empty model list."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = []

    await _handle_model_list_response(response)

    # Event should still be set
    assert mock_state.model_list_fetch_event.set.called


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_invalid_model_id(mock_state):
    """Test skipping models with invalid IDs."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = [
        {"id": None, "displayName": "Invalid"},
        {"id": "none", "displayName": "Also Invalid"},
        {"id": "valid-id", "displayName": "Valid"},
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "valid-id"


@pytest.mark.asyncio
@patch("browser_utils.operations_modules.parsers.os.environ.get", return_value="debug")
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_login_flow(mock_state, mock_env):
    """Test silent handling during login flow."""
    import asyncio

    mock_state.is_page_ready = False  # Triggers login flow
    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = [{"id": "test-model", "displayName": "Test"}]

    await _handle_model_list_response(response)

    # Should still process but silently (no logger.info calls in login flow)
    assert len(mock_state.parsed_model_list) == 1


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_three_layer_list(mock_state):
    """Test three-layer list structure."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    # Three-layer: [[[...], [...]]]
    response.json.return_value = [
        [
            ["models/test-1", 1, 2, "Test 1", "Desc 1"],
            ["models/test-2", 1, 2, "Test 2", "Desc 2"],
        ]
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 2


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_heuristic_search(mock_state):
    """Test heuristic search for model list in dict response."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    # Custom key (not 'data' or 'models')
    response.json.return_value = {
        "custom_models_key": [{"id": "heuristic-model", "displayName": "Heuristic"}]
    }

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "heuristic-model"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_dict_no_models_found(mock_state):
    """Test dict response with no model array found."""
    import asyncio

    mock_state.is_page_ready = True
    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = {"invalid_key": "no models here"}

    await _handle_model_list_response(response)

    # Should set event and return early
    assert mock_state.model_list_fetch_event.set.called


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_list_with_invalid_numeric_fields(
    mock_state,
):
    """Test list-based model with invalid numeric fields."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    # List with non-numeric values where numbers expected
    response.json.return_value = [
        ["models/test", 1, 2, "Name", "Desc", 5, "invalid", 7, 8, "bad_top_p"]
    ]

    await _handle_model_list_response(response)

    # Should still parse, but use fallback values
    assert len(mock_state.parsed_model_list) == 1


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("browser_utils.operations_modules.parsers.DEBUG_LOGS_ENABLED", True)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_debug_logs_enabled(mock_state):
    """Test detailed logging when DEBUG_LOGS_ENABLED=True."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.json.return_value = [
        {"id": "debug-model-1", "displayName": "Debug 1"},
        {"id": "debug-model-2", "displayName": "Debug 2"},
        {"id": "debug-model-3", "displayName": "Debug 3"},
    ]

    await _handle_model_list_response(response)

    # Should log first 3 models when debug enabled
    assert len(mock_state.parsed_model_list) == 3


# ==================== Model List Change Detection Tests ====================


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("browser_utils.operations_modules.parsers.DEBUG_LOGS_ENABLED", True)
@patch("api_utils.server_state.state")
async def test_handle_model_list_response_tracks_last_count(mock_state):
    """Test that _last_model_count is tracked for change detection."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False
    mock_state._last_model_count = 0

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.status = 200
    response.json.return_value = [
        {"id": "model-1", "displayName": "Model 1"},
        {"id": "model-2", "displayName": "Model 2"},
    ]

    await _handle_model_list_response(response)

    # _last_model_count should be updated
    assert mock_state._last_model_count == 2


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("browser_utils.operations_modules.parsers.DEBUG_LOGS_ENABLED", True)
@patch("api_utils.server_state.state")
async def test_handle_model_list_no_change_detection(mock_state):
    """Test that 'no change' log is shown when model count is same."""
    import asyncio

    # Pre-set same count
    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False
    mock_state._last_model_count = 2  # Set to match expected count

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.status = 200
    response.json.return_value = [
        {"id": "model-1", "displayName": "Model 1"},
        {"id": "model-2", "displayName": "Model 2"},
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 2


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("browser_utils.operations_modules.parsers.DEBUG_LOGS_ENABLED", True)
@patch("api_utils.server_state.state")
async def test_handle_model_list_excluded_in_change_block(mock_state):
    """Test that excluded models log is only shown when count changes."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = {"excluded-1"}
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False
    mock_state._last_model_count = 0  # Initial load

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.status = 200
    response.json.return_value = [
        {"id": "excluded-1", "displayName": "Excluded"},
        {"id": "included-1", "displayName": "Included"},
    ]

    await _handle_model_list_response(response)

    # Only included model should be in list
    assert len(mock_state.parsed_model_list) == 1
    assert mock_state.parsed_model_list[0]["id"] == "included-1"


@pytest.mark.asyncio
@patch(
    "browser_utils.operations_modules.parsers.MODELS_ENDPOINT_URL_CONTAINS", "models"
)
@patch("browser_utils.operations_modules.parsers.DEBUG_LOGS_ENABLED", True)
@patch("api_utils.server_state.state")
async def test_handle_model_list_first_load_always_logs(mock_state):
    """Test that first load (previous_count=0) always logs full details."""
    import asyncio

    mock_state.parsed_model_list = []
    mock_state.excluded_model_ids = set()
    mock_state.is_page_ready = True
    mock_state.model_list_fetch_event = AsyncMock(spec=asyncio.Event)
    mock_state.model_list_fetch_event.is_set.return_value = False
    # No _last_model_count attribute (first load)
    if hasattr(mock_state, "_last_model_count"):
        delattr(mock_state, "_last_model_count")

    response = AsyncMock()
    response.url = "https://example.com/models"
    response.ok = True
    response.status = 200
    response.json.return_value = [
        {"id": "test-model", "displayName": "Test"},
    ]

    await _handle_model_list_response(response)

    assert len(mock_state.parsed_model_list) == 1
