import os
from typing import Set

API_KEYS: Set[str] = set()
KEY_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "key.txt")


def load_api_keys():
    """Loads API keys from the key file into the API_KEYS set."""
    global API_KEYS
    API_KEYS.clear()
    if os.path.exists(KEY_FILE_PATH):
        with open(KEY_FILE_PATH, "r") as f:
            for line in f:
                key = line.strip()
                if key:
                    API_KEYS.add(key)


def initialize_keys():
    """Initializes API keys. Ensures key.txt exists and loads keys."""
    if not os.path.exists(KEY_FILE_PATH):
        with open(KEY_FILE_PATH, "w"):
            pass  # Create an empty file
    load_api_keys()


def verify_api_key(api_key_from_header: str) -> bool:
    """
    Verifies the API key.
    Returns True if API_KEYS is empty (no validation) or if the key is valid.
    """
    if not API_KEYS:
        return True
    return api_key_from_header in API_KEYS
