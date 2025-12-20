"""
Tests for api_utils/routers/model_capabilities.py

Tests for model capability determination and API endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from api_utils.routers.model_capabilities import (
    _get_model_capabilities,
    router,
)


# ==================== _get_model_capabilities TESTS ====================


class TestGetModelCapabilities:
    """Tests for _get_model_capabilities helper function."""

    def test_gemini3_flash(self):
        """Test Gemini 3 Flash model capabilities."""
        result = _get_model_capabilities("gemini-3-flash")
        assert result["thinkingType"] == "level"
        assert result["levels"] == ["minimal", "low", "medium", "high"]
        assert result["defaultLevel"] == "high"
        assert result["supportsGoogleSearch"] is True

    def test_gemini3_flash_variant(self):
        """Test Gemini 3 Flash variant (gemini3flash)."""
        result = _get_model_capabilities("gemini3flash-exp")
        assert result["thinkingType"] == "level"
        assert "minimal" in result["levels"]

    def test_gemini3_pro(self):
        """Test Gemini 3 Pro model capabilities."""
        result = _get_model_capabilities("gemini-3-pro")
        assert result["thinkingType"] == "level"
        assert result["levels"] == ["low", "high"]
        assert result["defaultLevel"] == "high"
        assert result["supportsGoogleSearch"] is True

    def test_gemini3_pro_variant(self):
        """Test Gemini 3 Pro variant (gemini3pro)."""
        result = _get_model_capabilities("gemini3pro-latest")
        assert result["thinkingType"] == "level"
        assert result["levels"] == ["low", "high"]

    def test_gemini25_pro(self):
        """Test Gemini 2.5 Pro model capabilities."""
        result = _get_model_capabilities("gemini-2.5-pro-preview")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is True
        assert result["budgetRange"] == [1024, 32768]
        assert result["defaultBudget"] == 32768
        assert result["supportsGoogleSearch"] is True

    def test_gemini25_pro_variant(self):
        """Test Gemini 2.5 Pro variant (gemini-2.5pro)."""
        result = _get_model_capabilities("gemini-2.5pro-exp")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is True

    def test_gemini25_flash(self):
        """Test Gemini 2.5 Flash model capabilities."""
        result = _get_model_capabilities("gemini-2.5-flash-preview")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is False
        assert result["budgetRange"] == [512, 24576]
        assert result["defaultBudget"] == 24576
        assert result["supportsGoogleSearch"] is True

    def test_gemini25_flash_variant(self):
        """Test Gemini 2.5 Flash variant (gemini-2.5flash)."""
        result = _get_model_capabilities("gemini-2.5flash-exp")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is False

    def test_gemini_flash_latest(self):
        """Test gemini-flash-latest maps to 2.5 Flash."""
        result = _get_model_capabilities("gemini-flash-latest")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is False

    def test_gemini_flash_lite_latest(self):
        """Test gemini-flash-lite-latest maps to 2.5 Flash."""
        result = _get_model_capabilities("gemini-flash-lite-latest")
        assert result["thinkingType"] == "budget"
        assert result["alwaysOn"] is False

    def test_gemini20(self):
        """Test Gemini 2.0 model capabilities (no thinking)."""
        result = _get_model_capabilities("gemini-2.0-flash-exp")
        assert result["thinkingType"] == "none"
        assert result["supportsGoogleSearch"] is False

    def test_gemini20_variant(self):
        """Test Gemini 2.0 variant (gemini2.0)."""
        result = _get_model_capabilities("gemini2.0-flash")
        assert result["thinkingType"] == "none"
        assert result["supportsGoogleSearch"] is False

    def test_gemini_robotics(self):
        """Test Gemini robotics model (special case - has Google Search)."""
        result = _get_model_capabilities("gemini-robotics-er-1.5-preview")
        assert result["thinkingType"] == "none"
        assert result["supportsGoogleSearch"] is True

    def test_other_model(self):
        """Test unknown/other model falls back to defaults."""
        result = _get_model_capabilities("some-other-model")
        assert result["thinkingType"] == "none"
        assert result["supportsGoogleSearch"] is True

    def test_case_insensitive(self):
        """Test model matching is case insensitive."""
        result = _get_model_capabilities("GEMINI-3-FLASH")
        assert result["thinkingType"] == "level"


# ==================== API Endpoint TESTS ====================


@pytest.fixture
def client():
    """Create test client for the router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestModelCapabilitiesEndpoints:
    """Tests for model capabilities API endpoints."""

    @pytest.mark.asyncio
    async def test_get_model_capabilities_endpoint(self, client):
        """Test GET /api/model-capabilities returns full structure."""
        response = client.get("/api/model-capabilities")
        assert response.status_code == 200

        data = response.json()
        assert "categories" in data
        assert "matchers" in data

        # Verify categories
        categories = data["categories"]
        assert "gemini3Flash" in categories
        assert "gemini3Pro" in categories
        assert "gemini25Pro" in categories
        assert "gemini25Flash" in categories
        assert "gemini2" in categories
        assert "other" in categories

        # Verify matchers
        matchers = data["matchers"]
        assert len(matchers) >= 5
        assert all("pattern" in m and "category" in m for m in matchers)

    @pytest.mark.asyncio
    async def test_get_single_model_capabilities_endpoint(self, client):
        """Test GET /api/model-capabilities/{model_id} returns model capabilities."""
        response = client.get("/api/model-capabilities/gemini-3-flash")
        assert response.status_code == 200

        data = response.json()
        assert data["thinkingType"] == "level"
        assert "levels" in data

    @pytest.mark.asyncio
    async def test_get_single_model_unknown(self, client):
        """Test GET /api/model-capabilities/{model_id} for unknown model."""
        response = client.get("/api/model-capabilities/unknown-model")
        assert response.status_code == 200

        data = response.json()
        assert data["thinkingType"] == "none"
        assert data["supportsGoogleSearch"] is True
