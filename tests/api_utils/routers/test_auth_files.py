"""
Tests for Auth Files API Router

Covers: GET /api/auth/files, GET /api/auth/active,
        POST /api/auth/activate, DELETE /api/auth/deactivate
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_utils.routers.auth_files import (
    ActivateRequest,
    AuthFileInfo,
    AuthFilesResponse,
    router,
)


@pytest.fixture
def app() -> FastAPI:
    """Create test FastAPI app with auth_files router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_auth_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Create mock auth directories with test files."""
    active_dir = tmp_path / "active"
    saved_dir = tmp_path / "saved"
    active_dir.mkdir()
    saved_dir.mkdir()

    # Create test auth files
    test_auth = {"token": "test123", "expires": "2025-12-31"}
    (saved_dir / "user1.json").write_text(json.dumps(test_auth))
    (saved_dir / "user2.json").write_text(json.dumps(test_auth))

    return active_dir, saved_dir


class TestAuthFileModels:
    """Tests for auth file models."""

    def test_auth_file_info_model(self) -> None:
        """Test AuthFileInfo model."""
        info = AuthFileInfo(
            name="test.json",
            path="/path/to/test.json",
            size_bytes=1024,
            is_active=True,
        )
        assert info.name == "test.json"
        assert info.is_active is True

    def test_auth_files_response_model(self) -> None:
        """Test AuthFilesResponse model."""
        response = AuthFilesResponse(
            saved_files=[
                AuthFileInfo(name="a.json", path="/a.json", size_bytes=100),
            ],
            active_file="a.json",
        )
        assert len(response.saved_files) == 1
        assert response.active_file == "a.json"

    def test_activate_request_model(self) -> None:
        """Test ActivateRequest model."""
        req = ActivateRequest(filename="test.json")
        assert req.filename == "test.json"


class TestListAuthFiles:
    """Tests for GET /api/auth/files endpoint."""

    def test_list_auth_files_empty(self, client: TestClient, tmp_path: Path) -> None:
        """Test listing files when directories are empty."""
        active_dir = tmp_path / "active"
        saved_dir = tmp_path / "saved"
        active_dir.mkdir()
        saved_dir.mkdir()

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.get("/api/auth/files")
            assert response.status_code == 200
            data = response.json()
            assert data["saved_files"] == []
            assert data["active_file"] is None

    def test_list_auth_files_with_files(
        self, client: TestClient, mock_auth_dirs: tuple[Path, Path]
    ) -> None:
        """Test listing files when files exist."""
        active_dir, saved_dir = mock_auth_dirs

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.get("/api/auth/files")
            assert response.status_code == 200
            data = response.json()
            assert len(data["saved_files"]) == 2
            names = [f["name"] for f in data["saved_files"]]
            assert "user1.json" in names
            assert "user2.json" in names


class TestGetActiveAuth:
    """Tests for GET /api/auth/active endpoint."""

    def test_get_active_auth_none(self, client: TestClient, tmp_path: Path) -> None:
        """Test getting active auth when none is active."""
        active_dir = tmp_path / "active"
        saved_dir = tmp_path / "saved"
        active_dir.mkdir()
        saved_dir.mkdir()

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.get("/api/auth/active")
            assert response.status_code == 200
            assert response.json()["active_file"] is None

    def test_get_active_auth_exists(self, client: TestClient, tmp_path: Path) -> None:
        """Test getting active auth when one is active."""
        active_dir = tmp_path / "active"
        saved_dir = tmp_path / "saved"
        active_dir.mkdir()
        saved_dir.mkdir()
        (active_dir / "current.json").write_text("{}")

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.get("/api/auth/active")
            assert response.status_code == 200
            assert response.json()["active_file"] == "current.json"


class TestActivateAuth:
    """Tests for POST /api/auth/activate endpoint."""

    def test_activate_auth_file(
        self, client: TestClient, mock_auth_dirs: tuple[Path, Path]
    ) -> None:
        """Test activating an auth file."""
        active_dir, saved_dir = mock_auth_dirs

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.post(
                "/api/auth/activate",
                json={"filename": "user1.json"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["active_file"] == "user1.json"

            # Verify file was copied
            assert (active_dir / "user1.json").exists()

    def test_activate_auth_file_not_found(
        self, client: TestClient, mock_auth_dirs: tuple[Path, Path]
    ) -> None:
        """Test activating non-existent file returns 404."""
        active_dir, saved_dir = mock_auth_dirs

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.post(
                "/api/auth/activate",
                json={"filename": "nonexistent.json"},
            )
            assert response.status_code == 404


class TestDeactivateAuth:
    """Tests for DELETE /api/auth/deactivate endpoint."""

    def test_deactivate_auth(self, client: TestClient, tmp_path: Path) -> None:
        """Test deactivating current auth."""
        active_dir = tmp_path / "active"
        saved_dir = tmp_path / "saved"
        active_dir.mkdir()
        saved_dir.mkdir()
        (active_dir / "current.json").write_text("{}")

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.delete("/api/auth/deactivate")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            # Verify file was removed
            assert not (active_dir / "current.json").exists()

    def test_deactivate_auth_none_active(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """Test deactivating when no auth is active."""
        active_dir = tmp_path / "active"
        saved_dir = tmp_path / "saved"
        active_dir.mkdir()
        saved_dir.mkdir()

        with (
            patch("api_utils.routers.auth_files.ACTIVE_AUTH_DIR", str(active_dir)),
            patch("api_utils.routers.auth_files.SAVED_AUTH_DIR", str(saved_dir)),
        ):
            response = client.delete("/api/auth/deactivate")
            assert response.status_code == 200
            # Should succeed even if nothing to remove
            assert response.json()["success"] is True
