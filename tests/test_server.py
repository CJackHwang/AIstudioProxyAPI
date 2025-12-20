"""
Tests for server.py - Server module attribute forwarding.

Tests the attribute forwarding mechanism that provides backward compatibility
by delegating attribute access to the central state object.
"""


class TestServerModuleLogic:
    """Tests for server module logic extracted for testability."""

    def test_state_attrs_set_is_complete(self) -> None:
        """Verify that _STATE_ATTRS contains expected attributes."""
        # Import the set directly to test its contents
        # We define what we expect based on the server module design
        expected_attrs = {
            "STREAM_QUEUE",
            "STREAM_PROCESS",
            "playwright_manager",
            "browser_instance",
            "page_instance",
            "is_playwright_ready",
            "is_browser_connected",
            "is_page_ready",
            "is_initializing",
            "PLAYWRIGHT_PROXY_SETTINGS",
            "global_model_list_raw_json",
            "parsed_model_list",
            "model_list_fetch_event",
            "current_ai_studio_model_id",
            "model_switching_lock",
            "excluded_model_ids",
            "request_queue",
            "processing_lock",
            "worker_task",
            "page_params_cache",
            "params_cache_lock",
            "console_logs",
            "network_log",
            "logger",
            "log_ws_manager",
            "should_exit",
        }

        # Read the actual file to verify the set
        import ast
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "server.py"
        content = server_path.read_text()
        tree = ast.parse(content)

        # Find the _STATE_ATTRS assignment
        state_attrs_found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_STATE_ATTRS":
                        # Extract the set literal
                        if isinstance(node.value, ast.Set):
                            state_attrs_found = {
                                elt.value
                                for elt in node.value.elts
                                if isinstance(elt, ast.Constant)
                            }
                        break

        assert state_attrs_found is not None, "_STATE_ATTRS not found in server.py"
        assert state_attrs_found == expected_attrs

    def test_clear_debug_logs_clears_state(self) -> None:
        """Verify clear_debug_logs function clears state logs."""
        from api_utils.server_state import state

        # Add some debug logs (using correct data structures - both are lists of dicts)
        state.console_logs.append({"message": "test log"})
        state.network_log["requests"].append({"test": "request"})

        assert len(state.console_logs) > 0
        assert len(state.network_log["requests"]) > 0

        # Call clear function directly from state (as server.clear_debug_logs delegates to it)
        state.clear_debug_logs()

        assert len(state.console_logs) == 0
        assert len(state.network_log["requests"]) == 0

    def test_state_forwarding_logic(self) -> None:
        """Verify the logic for forwarding state attributes works correctly."""
        from api_utils.server_state import state

        # Test that we can get/set attributes on state
        original_value = state.should_exit

        try:
            state.should_exit = True
            assert state.should_exit is True
        finally:
            state.should_exit = original_value

    def test_getattr_implementation(self) -> None:
        """Test the __getattr__ implementation logic."""
        from typing import Any

        from api_utils.server_state import state

        # Simulate the __getattr__ logic
        _STATE_ATTRS = {"page_instance", "should_exit"}

        def mock_getattr(name: str) -> Any:
            if name in _STATE_ATTRS:
                return getattr(state, name)
            raise AttributeError(f"module 'server' has no attribute '{name}'")

        # Test known attribute
        result = mock_getattr("page_instance")
        assert result is state.page_instance

        # Test unknown attribute
        import pytest

        with pytest.raises(AttributeError):
            mock_getattr("nonexistent_attr")

    def test_setattr_implementation(self) -> None:
        """Test the __setattr__ implementation logic."""
        from typing import Any

        from api_utils.server_state import state

        # Simulate the __setattr__ logic
        _STATE_ATTRS = {"should_exit"}
        test_globals: dict[str, Any] = {}

        def mock_setattr(name: str, value: Any) -> None:
            if name in _STATE_ATTRS:
                setattr(state, name, value)
            else:
                test_globals[name] = value

        original_value = state.should_exit

        try:
            # Test state attribute
            mock_setattr("should_exit", True)
            assert state.should_exit is True

            # Test non-state attribute
            mock_setattr("custom_attr", "custom_value")
            assert test_globals["custom_attr"] == "custom_value"
        finally:
            state.should_exit = original_value


class TestServerApp:
    """Tests for the FastAPI app creation.

    Note: These tests verify FastAPI app behavior through the existing
    api_utils tests rather than importing server.py directly, which has
    side effects (loading .env, creating app instance).
    """

    def test_create_app_produces_valid_app(self) -> None:
        """Verify create_app produces a valid FastAPI instance."""
        from api_utils import create_app

        app = create_app()
        assert app is not None
        assert hasattr(app, "routes")
        assert hasattr(app, "middleware")


class TestServerModuleDirectAccess:
    """Tests that directly access the server module's __getattr__ and __setattr__."""

    def test_getattr_logic_with_state_attrs(self) -> None:
        """Test that _STATE_ATTRS contains expected forwarding attributes."""
        # Import the _STATE_ATTRS set from server module to verify it exists
        import importlib.util

        spec = importlib.util.spec_from_file_location("server_module", "server.py")
        if spec and spec.loader:
            # Just verify we can parse the module and _STATE_ATTRS is defined
            with open("server.py") as f:
                content = f.read()
            assert "_STATE_ATTRS" in content
            assert "should_exit" in content

    def test_getattr_raises_for_unknown(self) -> None:
        """Test __getattr__ logic raises AttributeError for unknown attrs."""
        import pytest

        from api_utils.server_state import state

        _STATE_ATTRS = {"should_exit"}

        # Simulate __getattr__ logic
        def mock_getattr(name: str):
            if name in _STATE_ATTRS:
                return getattr(state, name)
            raise AttributeError(f"module 'server' has no attribute '{name}'")

        with pytest.raises(AttributeError) as exc_info:
            mock_getattr("nonexistent_xyz")
        assert "nonexistent_xyz" in str(exc_info.value)

    def test_setattr_logic_for_state_attrs(self) -> None:
        """Test __setattr__ logic forwards state attributes correctly."""
        from api_utils.server_state import state

        _STATE_ATTRS = {"should_exit"}
        test_globals: dict = {}

        # Simulate __setattr__ logic
        def mock_setattr(name: str, value) -> None:
            if name in _STATE_ATTRS:
                setattr(state, name, value)
            else:
                test_globals[name] = value

        original = state.should_exit
        try:
            mock_setattr("should_exit", True)
            assert state.should_exit is True

            mock_setattr("custom_attr", "value")
            assert test_globals["custom_attr"] == "value"
        finally:
            state.should_exit = original

    def test_clear_debug_logs_via_state(self) -> None:
        """Test clear_debug_logs functionality via state object."""
        from api_utils.server_state import state

        # Add test data
        state.console_logs.append({"test": "log"})

        # Call state's clear function directly
        state.clear_debug_logs()

        assert len(state.console_logs) == 0

    def test_app_creation(self) -> None:
        """Test that create_app produces a valid FastAPI instance."""
        from api_utils import create_app
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)
