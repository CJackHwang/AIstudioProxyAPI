"""
Tests for api_utils/routers/server.py

Tests for server control API endpoints including status and restart.
"""

import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api_utils.routers.server import (
    RestartRequest,
    ServerStatus,
    _format_uptime,
    _init_start_time,
    router,
)


# ==================== _format_uptime TESTS ====================


class TestFormatUptime:
    """Tests for _format_uptime helper function."""

    def test_seconds_only(self):
        """Test formatting with only seconds."""
        result = _format_uptime(45)
        assert result == "45秒"

    def test_minutes_and_seconds(self):
        """Test formatting with minutes and seconds."""
        result = _format_uptime(125)  # 2 min 5 sec
        assert "2分钟" in result
        assert "5秒" in result

    def test_hours_minutes_seconds(self):
        """Test formatting with hours, minutes, and seconds."""
        result = _format_uptime(3725)  # 1 hr 2 min 5 sec
        assert "1小时" in result
        assert "2分钟" in result
        assert "5秒" in result

    def test_days_hours_minutes_seconds(self):
        """Test formatting with days, hours, minutes, and seconds."""
        result = _format_uptime(90125)  # 1 day 1 hr 2 min 5 sec
        assert "1天" in result
        assert "1小时" in result
        assert "2分钟" in result
        assert "5秒" in result

    def test_zero_seconds(self):
        """Test formatting with zero seconds."""
        result = _format_uptime(0)
        assert result == "0秒"

    def test_exact_hour(self):
        """Test formatting with exact hour (no minutes)."""
        result = _format_uptime(3600)  # 1 hour exactly
        assert "1小时" in result
        assert "0秒" in result
        assert "分钟" not in result

    def test_exact_day(self):
        """Test formatting with exact day."""
        result = _format_uptime(86400)  # 1 day exactly
        assert "1天" in result
        assert "0秒" in result


# ==================== _init_start_time TESTS ====================


def test_init_start_time_sets_value():
    """Test _init_start_time sets the start time."""
    with patch("api_utils.routers.server._SERVER_START_TIME", None):
        with patch("api_utils.routers.server.time.time", return_value=12345.0):
            # Force re-initialization by importing fresh
            import api_utils.routers.server as server_module

            server_module._SERVER_START_TIME = None
            server_module._init_start_time()

            assert server_module._SERVER_START_TIME == 12345.0


def test_init_start_time_only_once():
    """Test _init_start_time only sets value once."""
    import api_utils.routers.server as server_module

    original_value = server_module._SERVER_START_TIME

    # Should not change since already set
    server_module._init_start_time()

    assert server_module._SERVER_START_TIME == original_value


# ==================== Model TESTS ====================


def test_server_status_model():
    """Test ServerStatus model creation."""
    status = ServerStatus(
        status="running",
        uptime_seconds=100.5,
        uptime_formatted="1分钟 40秒",
        launch_mode="headless",
        server_port=2048,
        stream_port=3120,
        version="1.0.0",
        python_version="3.12.0",
        started_at="2024-01-01T00:00:00",
    )

    assert status.status == "running"
    assert status.uptime_seconds == 100.5
    assert status.server_port == 2048


def test_restart_request_model():
    """Test RestartRequest model creation."""
    request = RestartRequest(mode="debug", confirm=True)

    assert request.mode == "debug"
    assert request.confirm is True


def test_restart_request_defaults():
    """Test RestartRequest model defaults."""
    request = RestartRequest()

    assert request.mode == "headless"
    assert request.confirm is False


# ==================== API Endpoint TESTS ====================


@pytest.fixture
def client():
    """Create test client for the router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestServerEndpoints:
    """Tests for Server control API endpoints."""

    def test_get_server_status_endpoint(self, client):
        """Test GET /api/server/status returns status."""
        response = client.get("/api/server/status")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "running"
        assert "uptime_seconds" in data
        assert "uptime_formatted" in data
        assert "launch_mode" in data
        assert "server_port" in data
        assert "stream_port" in data
        assert "version" in data
        assert "python_version" in data
        assert "started_at" in data

    def test_restart_server_no_confirm(self, client):
        """Test POST /api/server/restart without confirm fails."""
        response = client.post(
            "/api/server/restart", json={"mode": "headless", "confirm": False}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "确认" in data["message"]

    def test_restart_server_invalid_mode(self, client):
        """Test POST /api/server/restart with invalid mode fails."""
        response = client.post(
            "/api/server/restart", json={"mode": "invalid_mode", "confirm": True}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "无效" in data["message"]

    def test_restart_server_headless_success(self, client):
        """Test POST /api/server/restart with headless mode succeeds."""
        response = client.post(
            "/api/server/restart", json={"mode": "headless", "confirm": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["mode"] == "headless"
        assert os.environ.get("REQUESTED_RESTART_MODE") == "headless"

    def test_restart_server_debug_success(self, client):
        """Test POST /api/server/restart with debug mode succeeds."""
        response = client.post(
            "/api/server/restart", json={"mode": "debug", "confirm": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["mode"] == "debug"

    def test_restart_server_virtual_display_success(self, client):
        """Test POST /api/server/restart with virtual_display mode succeeds."""
        response = client.post(
            "/api/server/restart", json={"mode": "virtual_display", "confirm": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["mode"] == "virtual_display"

    def test_get_server_status_uses_env_vars(self, client):
        """Test server status reads from environment variables."""
        with patch.dict(
            os.environ,
            {
                "LAUNCH_MODE": "debug",
                "SERVER_PORT_INFO": "3000",
                "STREAM_PORT": "4000",
            },
        ):
            response = client.get("/api/server/status")

            data = response.json()
            assert data["launch_mode"] == "debug"
            assert data["server_port"] == 3000
            assert data["stream_port"] == 4000
