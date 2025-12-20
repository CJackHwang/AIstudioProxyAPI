"""
Tests for launcher/process.py

Tests for Camoufox process management including command building,
process lifecycle, and cleanup.
"""

import asyncio
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from io import BytesIO
from unittest.mock import MagicMock, call, patch

import pytest

from launcher.process import (
    CamoufoxProcessManager,
    _enqueue_output,
    build_launch_command,
)


# ==================== build_launch_command TESTS ====================


class TestBuildLaunchCommand:
    """Tests for build_launch_command pure function."""

    def test_basic_headless_mode(self):
        """Test basic command for headless mode."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=9222,
            internal_camoufox_proxy=None,
        )

        assert "--internal-launch-mode" in cmd
        assert "headless" in cmd
        assert "--internal-camoufox-os" in cmd
        assert "linux" in cmd
        assert "--internal-camoufox-port" in cmd
        assert "9222" in cmd

    def test_debug_mode(self):
        """Test command for debug mode."""
        cmd = build_launch_command(
            final_launch_mode="debug",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="windows",
            camoufox_debug_port=9223,
            internal_camoufox_proxy=None,
        )

        assert "debug" in cmd
        assert "windows" in cmd
        assert "9223" in cmd

    def test_with_auth_file(self):
        """Test command with auth file path."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path="/path/to/auth.json",
            simulated_os_for_camoufox="macos",
            camoufox_debug_port=9222,
            internal_camoufox_proxy=None,
        )

        assert "--internal-auth-file" in cmd
        assert "/path/to/auth.json" in cmd

    def test_without_auth_file(self):
        """Test command without auth file path."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=9222,
            internal_camoufox_proxy=None,
        )

        assert "--internal-auth-file" not in cmd

    def test_with_proxy(self):
        """Test command with proxy configuration."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=9222,
            internal_camoufox_proxy="http://proxy.example.com:8080",
        )

        assert "--internal-camoufox-proxy" in cmd
        assert "http://proxy.example.com:8080" in cmd

    def test_without_proxy(self):
        """Test command without proxy configuration."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=9222,
            internal_camoufox_proxy=None,
        )

        assert "--internal-camoufox-proxy" not in cmd

    def test_virtual_headless_mode(self):
        """Test command for virtual_headless mode."""
        cmd = build_launch_command(
            final_launch_mode="virtual_headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=9222,
            internal_camoufox_proxy=None,
        )

        assert "virtual_headless" in cmd


# ==================== _enqueue_output TESTS ====================


class TestEnqueueOutput:
    """Tests for _enqueue_output thread function."""

    def test_enqueue_output_basic(self):
        """Test basic output enqueueing."""
        output_queue = queue.Queue()
        stream = BytesIO(b"line1\nline2\n")

        _enqueue_output(stream, "stdout", output_queue, "1234")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        # Should have 2 lines + None sentinel
        assert len(items) == 3
        assert items[0] == ("stdout", "line1\n")
        assert items[1] == ("stdout", "line2\n")
        assert items[2] == ("stdout", None)  # Sentinel

    def test_enqueue_output_decode_error(self):
        """Test handling of decode errors."""
        output_queue = queue.Queue()
        # Invalid UTF-8 sequence
        stream = BytesIO(b"\xff\xfe invalid utf8\n")

        _enqueue_output(stream, "stderr", output_queue, "1234")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        # Should still produce output with replacement chars
        assert len(items) >= 2

    def test_enqueue_output_empty_stream(self):
        """Test handling of empty stream."""
        output_queue = queue.Queue()
        stream = BytesIO(b"")

        _enqueue_output(stream, "stdout", output_queue, "1234")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        # Should only have sentinel
        assert len(items) == 1
        assert items[0] == ("stdout", None)

    def test_enqueue_output_value_error(self):
        """Test handling of ValueError when stream is closed."""
        output_queue = queue.Queue()
        mock_stream = MagicMock()
        # readline raises ValueError (stream closed)
        mock_stream.readline.side_effect = ValueError("I/O operation on closed file")
        mock_stream.closed = True

        _enqueue_output(mock_stream, "stdout", output_queue, "1234")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        # Should have sentinel
        assert len(items) == 1
        assert items[0] == ("stdout", None)

    def test_enqueue_output_general_exception(self):
        """Test handling of general Exception in readline."""
        output_queue = queue.Queue()
        mock_stream = MagicMock()
        # readline raises general exception
        mock_stream.readline.side_effect = [Exception("Unexpected error")]
        mock_stream.closed = False

        _enqueue_output(mock_stream, "stderr", output_queue, "9999")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        # Should have sentinel (exception is logged, then finally block runs)
        assert len(items) == 1
        assert items[0] == ("stderr", None)

    def test_enqueue_output_stream_close_error(self):
        """Test handling of error when closing stream."""
        output_queue = queue.Queue()
        mock_stream = MagicMock()
        mock_stream.readline.return_value = b""  # Empty to trigger break
        mock_stream.closed = False
        mock_stream.close.side_effect = Exception("Close failed")

        # Should not raise, just log the error
        _enqueue_output(mock_stream, "stdout", output_queue, "1234")

        items = []
        while not output_queue.empty():
            items.append(output_queue.get_nowait())

        assert len(items) == 1
        assert items[0] == ("stdout", None)


# ==================== CamoufoxProcessManager TESTS ====================


class TestCamoufoxProcessManager:
    """Tests for CamoufoxProcessManager class."""

    def test_init(self):
        """Test manager initialization."""
        manager = CamoufoxProcessManager()

        assert manager.camoufox_proc is None
        assert manager.captured_ws_endpoint is None

    def test_cleanup_no_process(self):
        """Test cleanup when no process exists."""
        manager = CamoufoxProcessManager()

        # Should not raise
        manager.cleanup()

        assert manager.camoufox_proc is None

    def test_cleanup_process_already_exited(self):
        """Test cleanup when process has already exited."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Already exited
        manager.camoufox_proc = mock_proc

        manager.cleanup()

        assert manager.camoufox_proc is None

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix-specific process group test"
    )
    def test_cleanup_unix_sigterm_success(self):
        """Test cleanup on Unix with successful SIGTERM."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_proc.pid = 12345
        mock_proc.wait.return_value = None
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = False
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = False
        manager.camoufox_proc = mock_proc

        with (
            patch("os.getpgid", return_value=12345),
            patch("os.killpg") as mock_killpg,
        ):
            manager.cleanup()

        mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
        assert manager.camoufox_proc is None

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix-specific process group test"
    )
    def test_cleanup_unix_sigterm_timeout_then_sigkill(self):
        """Test cleanup on Unix when SIGTERM times out and SIGKILL is needed."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 5),
            None,
        ]
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = False
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = False
        manager.camoufox_proc = mock_proc

        with (
            patch("os.getpgid", return_value=12345),
            patch("os.killpg") as mock_killpg,
        ):
            manager.cleanup()

        # Should call killpg twice: once for SIGTERM, once for SIGKILL
        assert mock_killpg.call_count == 2
        mock_killpg.assert_any_call(12345, signal.SIGTERM)
        mock_killpg.assert_any_call(12345, signal.SIGKILL)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix-specific process group test"
    )
    def test_cleanup_unix_process_not_found(self):
        """Test cleanup on Unix when process group not found."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = True
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = True
        manager.camoufox_proc = mock_proc

        with (
            patch("os.getpgid", return_value=12345),
            patch("os.killpg", side_effect=ProcessLookupError()),
        ):
            manager.cleanup()

        assert manager.camoufox_proc is None

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_cleanup_windows(self):
        """Test cleanup on Windows."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = False
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = False
        manager.camoufox_proc = mock_proc

        with patch("subprocess.run") as mock_run:
            manager.cleanup()

        mock_run.assert_called_once()
        assert manager.camoufox_proc is None

    def test_cleanup_fallback_terminate(self):
        """Test cleanup fallback to terminate when no process groups."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.return_value = None
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = False
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = False
        manager.camoufox_proc = mock_proc

        # Remove getpgid/killpg to trigger fallback
        with (
            patch.object(os, "getpgid", None),
            patch.object(os, "killpg", None),
        ):
            # In case os doesn't have these attrs, patch hasattr
            with patch("builtins.hasattr", side_effect=lambda obj, attr: False):
                manager.cleanup()

        mock_proc.terminate.assert_called_once()
        assert manager.camoufox_proc is None

    def test_cleanup_fallback_terminate_then_kill(self):
        """Test cleanup fallback when terminate times out."""
        manager = CamoufoxProcessManager()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.closed = False
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.closed = False
        manager.camoufox_proc = mock_proc

        with patch("builtins.hasattr", side_effect=lambda obj, attr: False):
            manager.cleanup()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


# ==================== CamoufoxProcessManager.start TESTS ====================


class TestCamoufoxProcessManagerStart:
    """Tests for CamoufoxProcessManager.start method."""

    def test_start_success_captures_ws_endpoint(self):
        """Test successful start captures WebSocket endpoint."""
        manager = CamoufoxProcessManager()

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        # Create a mock args object
        mock_args = MagicMock()
        mock_args.camoufox_debug_port = 9222
        mock_args.internal_camoufox_proxy = None

        ws_endpoint = "ws://127.0.0.1:9222/devtools/browser/abc123"

        # Mock queue to return WS endpoint line
        mock_queue = MagicMock()
        mock_queue.get.side_effect = [
            ("stdout", f"WebSocket endpoint: {ws_endpoint}\n"),
            queue.Empty(),
        ]

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("queue.Queue", return_value=mock_queue),
            patch("threading.Thread") as mock_thread,
            patch("launcher.process.ENDPOINT_CAPTURE_TIMEOUT", 1),
            patch("launcher.process.ws_regex") as mock_regex,
        ):
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            mock_match = MagicMock()
            mock_match.group.return_value = ws_endpoint
            mock_regex.search.return_value = mock_match

            result = manager.start("headless", None, "linux", mock_args)

        assert result == ws_endpoint
        assert manager.captured_ws_endpoint == ws_endpoint

    def test_start_process_exits_early(self):
        """Test start when process exits early."""
        manager = CamoufoxProcessManager()

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = 1  # Already exited with error
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        mock_args = MagicMock()
        mock_args.camoufox_debug_port = 9222
        mock_args.internal_camoufox_proxy = None

        mock_queue = MagicMock()
        mock_queue.get.side_effect = queue.Empty()

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("queue.Queue", return_value=mock_queue),
            patch("threading.Thread") as mock_thread,
            patch("launcher.process.ENDPOINT_CAPTURE_TIMEOUT", 0.1),
            patch("sys.exit") as mock_exit,
        ):
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            manager.start("headless", None, "linux", mock_args)

        mock_exit.assert_called_once_with(1)

    def test_start_popen_exception(self):
        """Test start when Popen raises exception."""
        manager = CamoufoxProcessManager()

        mock_args = MagicMock()
        mock_args.camoufox_debug_port = 9222
        mock_args.internal_camoufox_proxy = None

        with (
            patch("subprocess.Popen", side_effect=OSError("Failed to start process")),
            patch("sys.exit") as mock_exit,
        ):
            manager.start("headless", None, "linux", mock_args)

        mock_exit.assert_called_once_with(1)
