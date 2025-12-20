"""
Model Capabilities API Endpoint

SINGLE SOURCE OF TRUTH for model thinking capabilities.
Frontend fetches this to determine UI controls dynamically.

When new models are released, update ONLY this file.
"""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# Model category types
ThinkingType = Literal["level", "budget", "none"]


def _get_model_capabilities(model_id: str) -> dict:
    """
    Determine thinking capabilities for a model.

    Returns dict with:
    - thinkingType: "level" | "budget" | "none"
    - levels: List of thinking levels (for type="level")
    - alwaysOn: Whether thinking is always on (for Gemini 2.5 Pro)
    - budgetRange: [min, max] for budget slider
    """
    model_lower = model_id.lower()

    # Gemini 3 Flash: 4-level selector
    if (
        "gemini-3" in model_lower or "gemini3" in model_lower
    ) and "flash" in model_lower:
        return {
            "thinkingType": "level",
            "levels": ["minimal", "low", "medium", "high"],
            "defaultLevel": "high",
            "supportsGoogleSearch": True,
        }

    # Gemini 3 Pro: 2-level selector
    if ("gemini-3" in model_lower or "gemini3" in model_lower) and "pro" in model_lower:
        return {
            "thinkingType": "level",
            "levels": ["low", "high"],
            "defaultLevel": "high",
            "supportsGoogleSearch": True,
        }

    # Gemini 2.5 Pro: Always-on thinking with budget
    if "gemini-2.5-pro" in model_lower or "gemini-2.5pro" in model_lower:
        return {
            "thinkingType": "budget",
            "alwaysOn": True,
            "budgetRange": [1024, 32768],
            "defaultBudget": 32768,
            "supportsGoogleSearch": True,
        }

    # Gemini 2.5 Flash and latest variants: Toggle + budget
    if (
        "gemini-2.5-flash" in model_lower
        or "gemini-2.5flash" in model_lower
        or model_lower == "gemini-flash-latest"
        or model_lower == "gemini-flash-lite-latest"
    ):
        return {
            "thinkingType": "budget",
            "alwaysOn": False,
            "budgetRange": [512, 24576],
            "defaultBudget": 24576,
            "supportsGoogleSearch": True,
        }

    # Gemini 2.0 models: No thinking, no Google Search
    if "gemini-2.0" in model_lower or "gemini2.0" in model_lower:
        return {
            "thinkingType": "none",
            "supportsGoogleSearch": False,
        }

    # Gemini robotics models: special case - has Google Search
    if "gemini-robotics" in model_lower:
        return {
            "thinkingType": "none",
            "supportsGoogleSearch": True,
        }

    # Other models: No thinking controls, default to Google Search enabled
    return {
        "thinkingType": "none",
        "supportsGoogleSearch": True,
    }


@router.get("/api/model-capabilities")
async def get_model_capabilities() -> JSONResponse:
    """
    Return thinking capabilities for all known model categories.

    Frontend uses this to dynamically configure thinking controls.
    """
    return JSONResponse(
        content={
            "categories": {
                "gemini3Flash": {
                    "thinkingType": "level",
                    "levels": ["minimal", "low", "medium", "high"],
                    "defaultLevel": "high",
                    "supportsGoogleSearch": True,
                },
                "gemini3Pro": {
                    "thinkingType": "level",
                    "levels": ["low", "high"],
                    "defaultLevel": "high",
                    "supportsGoogleSearch": True,
                },
                "gemini25Pro": {
                    "thinkingType": "budget",
                    "alwaysOn": True,
                    "budgetRange": [1024, 32768],
                    "defaultBudget": 32768,
                    "supportsGoogleSearch": True,
                },
                "gemini25Flash": {
                    "thinkingType": "budget",
                    "alwaysOn": False,
                    "budgetRange": [512, 24576],
                    "defaultBudget": 24576,
                    "supportsGoogleSearch": True,
                },
                "gemini2": {
                    "thinkingType": "none",
                    "supportsGoogleSearch": False,
                },
                "other": {
                    "thinkingType": "none",
                    "supportsGoogleSearch": True,
                },
            },
            "matchers": [
                # Order matters: more specific patterns first
                {
                    "pattern": "gemini-3.*flash|gemini3.*flash",
                    "category": "gemini3Flash",
                },
                {"pattern": "gemini-3.*pro|gemini3.*pro", "category": "gemini3Pro"},
                {
                    "pattern": "gemini-2\\.5-pro|gemini-2\\.5pro",
                    "category": "gemini25Pro",
                },
                {
                    "pattern": "gemini-2\\.5-flash|gemini-2\\.5flash|gemini-flash-latest|gemini-flash-lite-latest",
                    "category": "gemini25Flash",
                },
                {"pattern": "gemini-2\\.0|gemini2\\.0", "category": "gemini2"},
            ],
        }
    )


@router.get("/api/model-capabilities/{model_id}")
async def get_single_model_capabilities(model_id: str) -> JSONResponse:
    """
    Return thinking capabilities for a specific model.
    """
    return JSONResponse(content=_get_model_capabilities(model_id))
