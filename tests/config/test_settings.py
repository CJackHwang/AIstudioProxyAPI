"""
High-quality tests for config/settings.py - Settings configuration.

Focus: Test helper functions and path configuration.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from config.settings import (
    get_boolean_env,
    get_environment_variable,
    get_int_env,
)


# ===================== get_environment_variable Tests =====================


def test_get_environment_variable_returns_value():
    """测试场景: 环境变量存在时返回其值"""
    with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
        assert get_environment_variable("TEST_VAR") == "test_value"


def test_get_environment_variable_returns_default():
    """测试场景: 环境变量不存在时返回默认值"""
    assert get_environment_variable("NON_EXISTENT_VAR", "default") == "default"


def test_get_environment_variable_returns_empty_default():
    """测试场景: 无默认值时返回空字符串"""
    assert get_environment_variable("NON_EXISTENT_VAR") == ""


# ===================== get_boolean_env Tests =====================


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("on", True),
        ("ON", True),
    ],
)
def test_get_boolean_env_true_values(env_value: str, expected: bool):
    """测试场景: 布尔真值解析 (true/1/yes/on)"""
    with patch.dict(os.environ, {"BOOL_VAR": env_value}):
        assert get_boolean_env("BOOL_VAR") is expected


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("NO", False),
        ("off", False),
        ("OFF", False),
        ("", False),
        ("invalid", False),
    ],
)
def test_get_boolean_env_false_values(env_value: str, expected: bool):
    """测试场景: 布尔假值解析 (false/0/no/off/empty/invalid)"""
    with patch.dict(os.environ, {"BOOL_VAR": env_value}):
        assert get_boolean_env("BOOL_VAR") is expected


def test_get_boolean_env_default_true():
    """测试场景: 默认值为 True 时的逻辑翻转"""
    # When default=True, only explicit false values return False
    assert get_boolean_env("NON_EXISTENT", default=True) is True

    with patch.dict(os.environ, {"BOOL_VAR": "false"}):
        assert get_boolean_env("BOOL_VAR", default=True) is False
    with patch.dict(os.environ, {"BOOL_VAR": "0"}):
        assert get_boolean_env("BOOL_VAR", default=True) is False
    with patch.dict(os.environ, {"BOOL_VAR": "no"}):
        assert get_boolean_env("BOOL_VAR", default=True) is False
    with patch.dict(os.environ, {"BOOL_VAR": "off"}):
        assert get_boolean_env("BOOL_VAR", default=True) is False

    # Non-false values with default=True should return True
    with patch.dict(os.environ, {"BOOL_VAR": "anything"}):
        assert get_boolean_env("BOOL_VAR", default=True) is True


def test_get_boolean_env_default_false():
    """测试场景: 默认值为 False 时的标准逻辑"""
    assert get_boolean_env("NON_EXISTENT", default=False) is False


# ===================== get_int_env Tests =====================


def test_get_int_env_valid_integer():
    """测试场景: 有效整数字符串解析"""
    with patch.dict(os.environ, {"INT_VAR": "123"}):
        assert get_int_env("INT_VAR") == 123


def test_get_int_env_negative_integer():
    """测试场景: 负整数解析"""
    with patch.dict(os.environ, {"INT_VAR": "-456"}):
        assert get_int_env("INT_VAR") == -456


def test_get_int_env_zero():
    """测试场景: 零值解析"""
    with patch.dict(os.environ, {"INT_VAR": "0"}):
        assert get_int_env("INT_VAR") == 0


def test_get_int_env_invalid_returns_default():
    """测试场景: 无效字符串回退到默认值"""
    with patch.dict(os.environ, {"INT_VAR": "invalid"}):
        assert get_int_env("INT_VAR", default=10) == 10


def test_get_int_env_float_string_returns_default():
    """测试场景: 浮点数字符串回退到默认值"""
    with patch.dict(os.environ, {"INT_VAR": "3.14"}):
        assert get_int_env("INT_VAR", default=5) == 5


def test_get_int_env_empty_returns_default():
    """测试场景: 空字符串回退到默认值"""
    with patch.dict(os.environ, {"INT_VAR": ""}):
        assert get_int_env("INT_VAR", default=7) == 7


def test_get_int_env_non_existent_returns_default():
    """测试场景: 环境变量不存在时返回默认值"""
    assert get_int_env("NON_EXISTENT_INT", default=5) == 5


# ===================== Path Constants Tests =====================


def test_path_constants_are_strings():
    """测试场景: 路径常量均为字符串类型"""
    from config.settings import (
        ACTIVE_AUTH_DIR,
        APP_LOG_FILE_PATH,
        AUTH_PROFILES_DIR,
        LOG_DIR,
        SAVED_AUTH_DIR,
        UPLOAD_FILES_DIR,
    )

    assert isinstance(AUTH_PROFILES_DIR, str)
    assert isinstance(ACTIVE_AUTH_DIR, str)
    assert isinstance(SAVED_AUTH_DIR, str)
    assert isinstance(LOG_DIR, str)
    assert isinstance(APP_LOG_FILE_PATH, str)
    assert isinstance(UPLOAD_FILES_DIR, str)


def test_path_constants_contain_expected_dirs():
    """测试场景: 路径常量包含预期目录名称"""
    from config.settings import (
        ACTIVE_AUTH_DIR,
        APP_LOG_FILE_PATH,
        AUTH_PROFILES_DIR,
        LOG_DIR,
        SAVED_AUTH_DIR,
        UPLOAD_FILES_DIR,
    )

    assert "auth_profiles" in AUTH_PROFILES_DIR
    assert "active" in ACTIVE_AUTH_DIR
    assert "saved" in SAVED_AUTH_DIR
    assert "logs" in LOG_DIR
    assert "app.log" in APP_LOG_FILE_PATH
    assert "upload_files" in UPLOAD_FILES_DIR


def test_path_relationship_active_under_profiles():
    """测试场景: active 目录应在 auth_profiles 下"""
    from config.settings import ACTIVE_AUTH_DIR, AUTH_PROFILES_DIR

    # ACTIVE_AUTH_DIR should be a subdirectory of AUTH_PROFILES_DIR
    assert AUTH_PROFILES_DIR in ACTIVE_AUTH_DIR


def test_path_relationship_saved_under_profiles():
    """测试场景: saved 目录应在 auth_profiles 下"""
    from config.settings import AUTH_PROFILES_DIR, SAVED_AUTH_DIR

    assert AUTH_PROFILES_DIR in SAVED_AUTH_DIR


# ===================== Module-level Constants Tests =====================


def test_module_constants_with_env_override():
    """测试场景: 模块级常量可通过环境变量覆盖"""
    original_module = sys.modules.get("config.settings")

    try:
        with (
            patch.dict(
                os.environ,
                {
                    "DEBUG_LOGS_ENABLED": "true",
                    "TRACE_LOGS_ENABLED": "1",
                    "JSON_LOGS": "yes",
                },
            ),
            patch("dotenv.load_dotenv"),
        ):
            if "config.settings" in sys.modules:
                del sys.modules["config.settings"]

            import config.settings as settings

            assert settings.DEBUG_LOGS_ENABLED is True
            assert settings.TRACE_LOGS_ENABLED is True
            assert settings.JSON_LOGS_ENABLED is True
    finally:
        if original_module is not None:
            sys.modules["config.settings"] = original_module
        elif "config.settings" in sys.modules:
            del sys.modules["config.settings"]


def test_log_rotation_config():
    """测试场景: 日志轮转配置解析"""
    original_module = sys.modules.get("config.settings")

    try:
        with (
            patch.dict(
                os.environ,
                {
                    "LOG_FILE_MAX_BYTES": "5242880",  # 5MB
                    "LOG_FILE_BACKUP_COUNT": "10",
                },
            ),
            patch("dotenv.load_dotenv"),
        ):
            if "config.settings" in sys.modules:
                del sys.modules["config.settings"]

            import config.settings as settings

            assert settings.LOG_FILE_MAX_BYTES == 5242880
            assert settings.LOG_FILE_BACKUP_COUNT == 10
    finally:
        if original_module is not None:
            sys.modules["config.settings"] = original_module
        elif "config.settings" in sys.modules:
            del sys.modules["config.settings"]
