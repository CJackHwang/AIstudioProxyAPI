"""
Model Capabilities API Endpoint

SINGLE SOURCE OF TRUTH for model thinking capabilities.
Frontend fetches this to determine UI controls dynamically.

Configuration is loaded from config/model_capabilities.json.
When new models are released, update the JSON file - no code changes needed.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# Config file path
_CONFIG_PATH = (
    Path(__file__).parent.parent.parent / "config" / "model_capabilities.json"
)


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    """
    Load model capabilities configuration from JSON file.

    Uses LRU cache to avoid repeated file reads.
    Raises FileNotFoundError if config is missing.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"Model capabilities config not found: {_CONFIG_PATH}")

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def reload_config() -> None:
    """Clear the config cache, forcing a reload on next access."""
    _load_config.cache_clear()


def _get_model_capabilities(model_id: str) -> dict[str, Any]:
    """
    Determine thinking capabilities for a model.

    Returns dict with:
    - thinkingType: "level" | "budget" | "none"
    - levels: List of thinking levels (for type="level")
    - alwaysOn: Whether thinking is always on (for Gemini 2.5 Pro)
    - budgetRange: [min, max] for budget slider
    - supportsGoogleSearch: Whether the model supports Google Search
    """
    config = _load_config()
    categories = config.get("categories", {})
    matchers = config.get("matchers", [])

    model_lower = model_id.lower()

    # Try each matcher in order (order matters: more specific first)
    for matcher in matchers:
        pattern = matcher.get("pattern", "")
        category_name = matcher.get("category", "")

        if pattern and category_name:
            try:
                if re.search(pattern, model_lower, re.IGNORECASE):
                    if category_name in categories:
                        return categories[category_name].copy()
            except re.error:
                # Invalid regex pattern, skip
                continue

    # Default to "other" category
    return categories.get(
        "other", {"thinkingType": "none", "supportsGoogleSearch": True}
    )


@router.get("/api/model-capabilities")
async def get_model_capabilities() -> JSONResponse:
    """
    Return thinking capabilities for all known model categories.

    Frontend uses this to dynamically configure thinking controls.
    """
    config = _load_config()
    return JSONResponse(content=config)


@router.get("/api/model-capabilities/{model_id:path}")
async def get_single_model_capabilities(model_id: str) -> JSONResponse:
    """
    Return thinking capabilities for a specific model.

    Args:
        model_id: Model identifier (e.g., "gemini-2.5-flash-preview")
    """
    return JSONResponse(content=_get_model_capabilities(model_id))
