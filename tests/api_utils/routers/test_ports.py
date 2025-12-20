"""
Tests for Ports Configuration API Router

Covers: GET/POST /api/ports/config, GET /api/ports/status, POST /api/ports/kill
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_utils.routers.ports import (
    KillRequest,
    PortConfig,
    PortStatus,
    ProcessInfo,
    _find_processes_on_port,
    _get_process_name,
    router,
)


@pytest.fixture
def app() -> FastAPI:
    """Create test FastAPI app with ports router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestPortModels:
    """Tests for port models."""

    def test_port_config_model(self) -> None:
        """Test PortConfig model with defaults."""
        config = PortConfig()
        assert config.fastapi_port == 2048
        assert config.camoufox_debug_port == 9222
        assert config.stream_proxy_port == 3120
        assert config.stream_proxy_enabled is True

    def test_port_config_validation(self) -> None:
        """Test PortConfig validates port ranges."""
        with pytest.raises(ValueError):
            PortConfig(fastapi_port=80)  # Below 1024

        # Valid range
        config = PortConfig(fastapi_port=8080)
        assert config.fastapi_port == 8080

    def test_process_info_model(self) -> None:
        """Test ProcessInfo model."""
        proc = ProcessInfo(pid=1234, name="python")
        assert proc.pid == 1234
        assert proc.name == "python"

    def test_port_status_model(self) -> None:
        """Test PortStatus model."""
        status = PortStatus(
            port=8080,
            port_type="FastAPI",
            in_use=True,
            processes=[ProcessInfo(pid=1234, name="python")],
        )
        assert status.in_use is True
        assert len(status.processes) == 1

    def test_kill_request_model(self) -> None:
        """Test KillRequest model."""
        req = KillRequest(pid=1234, confirm=True)
        assert req.pid == 1234
        assert req.confirm is True


class TestGetPortConfig:
    """Tests for GET /api/ports/config endpoint."""

    def test_get_port_config_defaults(self, client: TestClient, tmp_path: Path) -> None:
        """Test getting config when no file exists."""
        with patch(
            "api_utils.routers.ports._PORTS_CONFIG_FILE", tmp_path / "nonexistent.json"
        ):
            response = client.get("/api/ports/config")
            assert response.status_code == 200
            data = response.json()
            assert "fastapi_port" in data
            assert "camoufox_debug_port" in data

    def test_get_port_config_from_file(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """Test getting config from saved file."""
        config_file = tmp_path / "ports_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "fastapi_port": 9999,
                    "camoufox_debug_port": 9223,
                    "stream_proxy_port": 3121,
                    "stream_proxy_enabled": False,
                }
            )
        )

        with patch("api_utils.routers.ports._PORTS_CONFIG_FILE", config_file):
            response = client.get("/api/ports/config")
            assert response.status_code == 200
            data = response.json()
            assert data["fastapi_port"] == 9999


class TestUpdatePortConfig:
    """Tests for POST /api/ports/config endpoint."""

    def test_update_port_config(self, client: TestClient, tmp_path: Path) -> None:
        """Test updating port configuration."""
        config_file = tmp_path / "ports_config.json"

        with patch("api_utils.routers.ports._PORTS_CONFIG_FILE", config_file):
            response = client.post(
                "/api/ports/config",
                json={
                    "fastapi_port": 8080,
                    "camoufox_debug_port": 9000,
                    "stream_proxy_port": 3200,
                    "stream_proxy_enabled": True,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["config"]["fastapi_port"] == 8080
            assert "restart" in data["message"].lower() or "重启" in data["message"]

    def test_update_port_config_invalid(self, client: TestClient) -> None:
        """Test updating with invalid port."""
        response = client.post(
            "/api/ports/config",
            json={
                "fastapi_port": 80,  # Invalid
                "camoufox_debug_port": 9222,
                "stream_proxy_port": 3120,
                "stream_proxy_enabled": True,
            },
        )
        assert response.status_code == 422


class TestPortStatus:
    """Tests for GET /api/ports/status endpoint."""

    def test_get_port_status(self, client: TestClient) -> None:
        """Test getting port status."""
        with patch("api_utils.routers.ports._find_processes_on_port", return_value=[]):
            response = client.get("/api/ports/status")
            assert response.status_code == 200
            data = response.json()
            assert "ports" in data
            assert len(data["ports"]) >= 2  # At least FastAPI and Camoufox

    def test_get_port_status_with_processes(self, client: TestClient) -> None:
        """Test port status shows active processes."""
        mock_processes = [ProcessInfo(pid=1234, name="python")]

        with patch(
            "api_utils.routers.ports._find_processes_on_port",
            return_value=mock_processes,
        ):
            response = client.get("/api/ports/status")
            assert response.status_code == 200
            data = response.json()
            # At least one port should show in_use
            in_use_ports = [p for p in data["ports"] if p["in_use"]]
            assert len(in_use_ports) > 0


class TestKillProcess:
    """Tests for POST /api/ports/kill endpoint."""

    def test_kill_process_requires_confirmation(self, client: TestClient) -> None:
        """Test kill endpoint requires confirmation."""
        response = client.post(
            "/api/ports/kill",
            json={"pid": 1234, "confirm": False},
        )
        assert response.status_code == 400

    def test_kill_process_with_confirmation(self, client: TestClient) -> None:
        """Test kill process with confirmation when PID is on a tracked port."""
        # Must mock _find_processes_on_port to return a process with matching PID
        mock_processes = [ProcessInfo(pid=1234, name="python")]
        with (
            patch(
                "api_utils.routers.ports._find_processes_on_port",
                return_value=mock_processes,
            ),
            patch(
                "api_utils.routers.ports._kill_process",
                return_value=(True, "进程已终止"),
            ),
        ):
            response = client.post(
                "/api/ports/kill",
                json={"pid": 1234, "confirm": True},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_kill_process_unauthorized_pid(self, client: TestClient) -> None:
        """Test kill process fails for PID not on tracked ports (security check)."""
        # Mock _find_processes_on_port to return empty (PID not on any port)
        with patch(
            "api_utils.routers.ports._find_processes_on_port",
            return_value=[],
        ):
            response = client.post(
                "/api/ports/kill",
                json={"pid": 9999, "confirm": True},
            )
            assert response.status_code == 403
            data = response.json()
            assert "9999" in data["detail"]

    def test_kill_process_failure(self, client: TestClient) -> None:
        """Test kill process failure when kill actually fails."""
        # Mock: PID is on tracked port, but kill fails
        mock_processes = [ProcessInfo(pid=1234, name="python")]
        with (
            patch(
                "api_utils.routers.ports._find_processes_on_port",
                return_value=mock_processes,
            ),
            patch(
                "api_utils.routers.ports._kill_process",
                return_value=(False, "无法终止进程"),
            ),
        ):
            response = client.post(
                "/api/ports/kill",
                json={"pid": 1234, "confirm": True},
            )
            assert response.status_code == 500
            data = response.json()
            assert data["success"] is False


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_find_processes_on_port_empty(self) -> None:
        """Test finding processes on unused port."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _find_processes_on_port(59999)  # Unlikely to be in use
            assert isinstance(result, list)

    def test_get_process_name_unknown(self) -> None:
        """Test getting name for non-existent PID."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            name = _get_process_name(999999)  # Non-existent PID
            assert name == "Unknown"

    def test_find_processes_on_port_linux(self) -> None:
        """Test finding processes on Linux."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="1234\n5678\n")
            with patch.object(
                __import__("api_utils.routers.ports", fromlist=["_get_process_name"]),
                "_get_process_name",
                return_value="python",
            ):
                result = _find_processes_on_port(8080)
                assert isinstance(result, list)

    def test_get_process_name_linux(self) -> None:
        """Test getting process name on Linux."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="python3\n")
            name = _get_process_name(1234)
            assert name == "python3"

    def test_get_process_name_darwin(self) -> None:
        """Test getting process name on macOS."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="node\n")
            name = _get_process_name(1234)
            assert name == "node"

    def test_find_processes_on_port_exception(self) -> None:
        """Test finding processes handles exceptions."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run", side_effect=Exception("fail")),
        ):
            result = _find_processes_on_port(8080)
            assert result == []


class TestKillProcessHelper:
    """Tests for _kill_process helper function."""

    def test_kill_process_linux_success(self) -> None:
        """Test killing process on Linux with SIGTERM."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run") as mock_run,
        ):
            # First call is SIGTERM, second is check (process gone)
            mock_run.side_effect = [
                MagicMock(returncode=0),  # SIGTERM
                MagicMock(returncode=1),  # Check shows process gone
            ]
            with patch("time.sleep"):
                success, msg = _kill_process(1234)
                assert success is True

    def test_kill_process_linux_force_kill(self) -> None:
        """Test killing process on Linux requires SIGKILL."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run") as mock_run,
        ):
            # SIGTERM doesn't work, SIGKILL does
            mock_run.side_effect = [
                MagicMock(returncode=0),  # SIGTERM
                MagicMock(returncode=0),  # Check shows still alive
                MagicMock(returncode=0),  # SIGKILL
                MagicMock(returncode=1),  # Check shows process gone
            ]
            with patch("time.sleep"):
                success, msg = _kill_process(1234)
                assert success is True
                assert "SIGKILL" in msg or "强制终止" in msg

    def test_kill_process_unsupported_os(self) -> None:
        """Test killing process on unsupported OS."""
        from api_utils.routers.ports import _kill_process

        with patch("platform.system", return_value="FreeBSD"):
            success, msg = _kill_process(1234)
            assert success is False

    def test_kill_process_exception(self) -> None:
        """Test killing process handles exceptions."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run", side_effect=Exception("permission denied")),
        ):
            success, msg = _kill_process(1234)
            assert success is False
            assert "permission denied" in msg.lower() or "错误" in msg


class TestWindowsPlatform:
    """Tests for Windows-specific code paths."""

    def test_find_processes_windows_success(self) -> None:
        """Test _find_processes_on_port on Windows with successful netstat parsing."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
            patch(
                "api_utils.routers.ports._get_process_name", return_value="python.exe"
            ),
        ):
            # Simulate netstat -ano output (actual netstat format without header)
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       1234\n"
                    "TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       5678\n"
                ),
            )
            result = _find_processes_on_port(8080)
            assert len(result) == 1
            assert result[0].pid == 1234
            assert result[0].name == "python.exe"

    def test_find_processes_windows_no_match(self) -> None:
        """Test _find_processes_on_port on Windows when port not found."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "  Proto  Local Address          Foreign Address        State           PID\n"
                    "  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       5678\n"
                ),
            )
            result = _find_processes_on_port(8080)
            assert len(result) == 0

    def test_find_processes_windows_multiple(self) -> None:
        """Test _find_processes_on_port on Windows with same port multiple PIDs."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
            patch("api_utils.routers.ports._get_process_name", return_value="node.exe"),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "  Proto  Local Address          Foreign Address        State           PID\n"
                    "  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       1234\n"
                    "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       1234\n"
                ),
            )
            result = _find_processes_on_port(8080)
            # Should deduplicate by PID
            assert len(result) == 1

    def test_get_process_name_windows_success(self) -> None:
        """Test _get_process_name on Windows with tasklist."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            # tasklist /NH /FO CSV output format
            mock_run.return_value = MagicMock(
                returncode=0, stdout='"python.exe","1234","Console","1","10,000 K"\n'
            )
            name = _get_process_name(1234)
            assert name == "python.exe"

    def test_get_process_name_windows_empty(self) -> None:
        """Test _get_process_name on Windows with empty result."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            name = _get_process_name(1234)
            assert name == "Unknown"

    def test_get_process_name_windows_failure(self) -> None:
        """Test _get_process_name on Windows with non-zero return code."""
        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            name = _get_process_name(1234)
            assert name == "Unknown"

    def test_kill_process_windows_success(self) -> None:
        """Test _kill_process on Windows with taskkill success."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            success, msg = _kill_process(1234)
            assert success is True
            assert "1234" in msg

    def test_kill_process_windows_failure(self) -> None:
        """Test _kill_process on Windows with taskkill failure."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("api_utils.routers.ports.platform.system", return_value="Windows"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
            patch(
                "api_utils.routers.ports.subprocess.CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=1, stderr="Access denied or process not found"
            )
            success, msg = _kill_process(1234)
            assert success is False
            assert "1234" in msg or "无法" in msg

    def test_kill_process_linux_cannot_kill(self) -> None:
        """Test _kill_process on Linux when process survives SIGKILL."""
        from api_utils.routers.ports import _kill_process

        with (
            patch("api_utils.routers.ports.platform.system", return_value="Linux"),
            patch("api_utils.routers.ports.subprocess.run") as mock_run,
        ):
            # Process survives both SIGTERM and SIGKILL
            mock_run.side_effect = [
                MagicMock(returncode=0),  # SIGTERM
                MagicMock(returncode=0),  # Check shows still alive
                MagicMock(returncode=0),  # SIGKILL
                MagicMock(returncode=0),  # Check shows still alive
            ]
            with patch("time.sleep"):
                success, msg = _kill_process(1234)
                assert success is False
                assert "无法" in msg or "1234" in msg
