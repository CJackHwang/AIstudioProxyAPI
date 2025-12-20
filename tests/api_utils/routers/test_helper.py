"""
Tests for api_utils/routers/helper.py

Tests for Helper configuration API endpoints.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api_utils.routers.helper import (
    HelperConfig,
    _load_config,
    _save_config,
    router,
)


# ==================== _load_config TESTS ====================


def test_load_config_file_exists(tmp_path):
    """Test _load_config loads config from existing file."""
    config_data = {"enabled": True, "endpoint": "http://example.com", "sapisid": "xyz"}

    with patch("api_utils.routers.helper._HELPER_CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(config_data)

        result = _load_config()

        assert result.enabled is True
        assert result.endpoint == "http://example.com"
        assert result.sapisid == "xyz"


def test_load_config_file_not_exists():
    """Test _load_config returns default when file doesn't exist."""
    with patch("api_utils.routers.helper._HELPER_CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = False

        result = _load_config()

        assert result.enabled is False
        assert result.endpoint == ""
        assert result.sapisid is None


def test_load_config_parse_error():
    """Test _load_config handles JSON parse error gracefully."""
    with patch("api_utils.routers.helper._HELPER_CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "not valid json"

        result = _load_config()

        # Should return default config
        assert result.enabled is False
        assert result.endpoint == ""


def test_load_config_validation_error():
    """Test _load_config handles validation error gracefully."""
    with patch("api_utils.routers.helper._HELPER_CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = True
        # enabled should be bool, this is invalid
        mock_file.read_text.return_value = json.dumps({"enabled": "not_a_bool"})

        result = _load_config()

        # Should return default config due to validation error
        assert isinstance(result, HelperConfig)


# ==================== _save_config TESTS ====================


def test_save_config_success(tmp_path):
    """Test _save_config saves config successfully."""
    config = HelperConfig(enabled=True, endpoint="http://test.com", sapisid="abc123")

    mock_config_dir = MagicMock()
    mock_config_file = MagicMock()

    with (
        patch("api_utils.routers.helper._CONFIG_DIR", mock_config_dir),
        patch("api_utils.routers.helper._HELPER_CONFIG_FILE", mock_config_file),
    ):
        _save_config(config)

        mock_config_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_config_file.write_text.assert_called_once()

        # Verify JSON content
        call_args = mock_config_file.write_text.call_args
        written_content = call_args[0][0]
        parsed = json.loads(written_content)
        assert parsed["enabled"] is True
        assert parsed["endpoint"] == "http://test.com"


def test_save_config_write_error():
    """Test _save_config handles write error gracefully."""
    config = HelperConfig(enabled=True, endpoint="http://test.com")

    mock_config_dir = MagicMock()
    mock_config_file = MagicMock()
    mock_config_file.write_text.side_effect = PermissionError("Cannot write")

    with (
        patch("api_utils.routers.helper._CONFIG_DIR", mock_config_dir),
        patch("api_utils.routers.helper._HELPER_CONFIG_FILE", mock_config_file),
    ):
        # Should not raise
        _save_config(config)


def test_save_config_mkdir_error():
    """Test _save_config handles mkdir error gracefully."""
    config = HelperConfig(enabled=True, endpoint="http://test.com")

    mock_config_dir = MagicMock()
    mock_config_dir.mkdir.side_effect = PermissionError("Cannot create directory")

    with patch("api_utils.routers.helper._CONFIG_DIR", mock_config_dir):
        # Should not raise
        _save_config(config)


# ==================== API Endpoint TESTS ====================


@pytest.fixture
def client():
    """Create test client for the router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestHelperEndpoints:
    """Tests for Helper configuration API endpoints."""

    def test_get_helper_config_endpoint(self, client):
        """Test GET /api/helper/config returns config."""
        with patch(
            "api_utils.routers.helper._load_config",
            return_value=HelperConfig(
                enabled=True, endpoint="http://example.com", sapisid="test"
            ),
        ):
            response = client.get("/api/helper/config")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["endpoint"] == "http://example.com"
            assert data["sapisid"] == "test"

    def test_update_helper_config_endpoint(self, client):
        """Test POST /api/helper/config updates and returns config."""
        with patch("api_utils.routers.helper._save_config") as mock_save:
            response = client.post(
                "/api/helper/config",
                json={"enabled": True, "endpoint": "http://new.example.com"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Helper 配置已保存"
            assert data["config"]["enabled"] is True
            assert data["config"]["endpoint"] == "http://new.example.com"

            mock_save.assert_called_once()

    def test_update_helper_config_with_sapisid(self, client):
        """Test POST /api/helper/config with sapisid."""
        with patch("api_utils.routers.helper._save_config"):
            response = client.post(
                "/api/helper/config",
                json={
                    "enabled": True,
                    "endpoint": "http://test.com",
                    "sapisid": "secret123",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["config"]["sapisid"] == "secret123"

    def test_update_helper_config_validation_error(self, client):
        """Test POST /api/helper/config with invalid data."""
        response = client.post(
            "/api/helper/config",
            json={"enabled": "not_a_bool"},  # Invalid type
        )

        # FastAPI returns 422 for validation errors
        assert response.status_code == 422
