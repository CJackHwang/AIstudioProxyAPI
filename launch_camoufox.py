#!/usr/bin/env python3
# launch_camoufox.py
import sys
import subprocess
import time
import re
import os
import signal
import atexit
import argparse
import select
import traceback
import json
import threading
import queue
import logging
import logging.handlers
import socket
import platform
import shutil

# --- New imports ---
from dotenv import load_dotenv

# Load .env file early to ensure subsequent modules get correct env vars
load_dotenv()

import uvicorn
from server import app # Import FastAPI app object from server.py
# -----------------

# Try importing launch_server (for internal launch mode, simulating Camoufox behavior)
try:
    import camoufox.server
    import camoufox.utils
    from camoufox.server import launch_server
    from camoufox import DefaultAddons # Assuming DefaultAddons contains AntiFingerprint

    # --- Monkeypatch Fix Start ---
    # Fix "proxy: expected object, got null" error in camoufox.
    # The launch_server function fails if 'proxy' is explicitly None in the config because
    # camoufox.utils.launch_options returns 'proxy': None, which becomes null in JSON,
    # causing the Node.js launcher to throw "expected object, got null".
    _original_launch_options = camoufox.utils.launch_options

    def _patched_launch_options(*args, **kwargs):
        # Call original to get the full config dict (which includes defaults like proxy=None)
        opts = _original_launch_options(*args, **kwargs)
        # Remove 'proxy' key if it is None, so it doesn't get sent to the JS launcher
        if 'proxy' in opts and opts['proxy'] is None:
            del opts['proxy']
        return opts

    # Replace the function in camoufox.server module so launch_server uses our wrapper
    camoufox.server.launch_options = _patched_launch_options
    # --- Monkeypatch Fix End ---

except ImportError:
    if '--internal-launch' in sys.argv or any(arg.startswith('--internal-') for arg in sys.argv): # Check for internal args broadly
        print("❌ Fatal Error: Internal launch mode requires 'camoufox.server.launch_server' and 'camoufox.DefaultAddons' but failed to import.", file=sys.stderr)
        print("   This usually means the 'camoufox' package is not installed correctly or not in PYTHONPATH.", file=sys.stderr)
        sys.exit(1)
    else:
        launch_server = None
        DefaultAddons = None

# --- Configuration Constants ---
PYTHON_EXECUTABLE = sys.executable
ENDPOINT_CAPTURE_TIMEOUT = int(os.environ.get('ENDPOINT_CAPTURE_TIMEOUT', '45'))  # Seconds (from dev)
DEFAULT_SERVER_PORT = int(os.environ.get('DEFAULT_FASTAPI_PORT', '2048'))  # FastAPI server port
DEFAULT_CAMOUFOX_PORT = int(os.environ.get('DEFAULT_CAMOUFOX_PORT', '9222'))  # Camoufox debug port (if needed for internal launch)
DEFAULT_STREAM_PORT = int(os.environ.get('STREAM_PORT', '3120'))  # Stream proxy server port
DEFAULT_HELPER_ENDPOINT = os.environ.get('GUI_DEFAULT_HELPER_ENDPOINT', '')  # External Helper endpoint
DEFAULT_AUTH_SAVE_TIMEOUT = int(os.environ.get('AUTH_SAVE_TIMEOUT', '30'))  # Auth save timeout
DEFAULT_SERVER_LOG_LEVEL = os.environ.get('SERVER_LOG_LEVEL', 'INFO')  # Server log level
AUTH_PROFILES_DIR = os.path.join(os.path.dirname(__file__), "auth_profiles")
ACTIVE_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "active")
SAVED_AUTH_DIR = os.path.join(AUTH_PROFILES_DIR, "saved")
HTTP_PROXY = os.environ.get('HTTP_PROXY', '')
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', '')
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LAUNCHER_LOG_FILE_PATH = os.path.join(LOG_DIR, 'launch_app.log')

# --- Global process handle ---
camoufox_proc = None

# --- Logger instance ---
logger = logging.getLogger("CamoufoxLauncher")

# --- WebSocket endpoint regex ---
ws_regex = re.compile(r"(ws://\S+)")


# --- Thread-safe output queue handler (_enqueue_output) (from dev - more robust error handling) ---
def _enqueue_output(stream, stream_name, output_queue, process_pid_for_log="<UnknownPID>"):
    log_prefix = f"[ReadThread-{stream_name}-PID:{process_pid_for_log}]"
    try:
        for line_bytes in iter(stream.readline, b''):
            if not line_bytes:
                break
            try:
                line_str = line_bytes.decode('utf-8', errors='replace')
                output_queue.put((stream_name, line_str))
            except Exception as decode_err:
                logger.warning(f"{log_prefix} Decode error: {decode_err}. Raw data (first 100 bytes): {line_bytes[:100]}")
                output_queue.put((stream_name, f"[Decode Error: {decode_err}] {line_bytes[:100]}...\n"))
    except ValueError:
        logger.debug(f"{log_prefix} ValueError (Stream might be closed).")
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error reading stream: {e}", exc_info=True)
    finally:
        output_queue.put((stream_name, None))
        if hasattr(stream, 'close') and not stream.closed:
            try:
                stream.close()
            except Exception:
                pass
        logger.debug(f"{log_prefix} Thread exiting.")

# --- Setup launcher logging system (setup_launcher_logging) (from dev - clears log on start) ---
def setup_launcher_logging(log_level=logging.INFO):
    os.makedirs(LOG_DIR, exist_ok=True)
    file_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s')
    console_log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(log_level)
    logger.propagate = False
    if os.path.exists(LAUNCHER_LOG_FILE_PATH):
        try:
            os.remove(LAUNCHER_LOG_FILE_PATH)
        except OSError:
            pass
    file_handler = logging.handlers.RotatingFileHandler(
        LAUNCHER_LOG_FILE_PATH, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8', mode='w'
    )
    file_handler.setFormatter(file_log_formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(console_log_formatter)
    logger.addHandler(stream_handler)
    logger.info("=" * 30 + " Camoufox Launcher Logging Initialized " + "=" * 30)
    logger.info(f"Log level set to: {logging.getLevelName(logger.getEffectiveLevel())}")
    logger.info(f"Log file path: {LAUNCHER_LOG_FILE_PATH}")

# --- Ensure auth directories exist (ensure_auth_dirs_exist) ---
def ensure_auth_dirs_exist():
    logger.info("Checking and ensuring auth directories exist...")
    try:
        os.makedirs(ACTIVE_AUTH_DIR, exist_ok=True)
        logger.info(f"  ✓ Active auth directory ready: {ACTIVE_AUTH_DIR}")
        os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
        logger.info(f"  ✓ Saved auth directory ready: {SAVED_AUTH_DIR}")
    except Exception as e:
        logger.error(f"  ❌ Failed to create auth directories: {e}", exc_info=True)
        sys.exit(1)

# --- Cleanup function (executed on exit) (from dev - more detailed logging and checks) ---
def cleanup():
    global camoufox_proc
    logger.info("--- Starting cleanup routine (launch_camoufox.py) ---")
    if camoufox_proc and camoufox_proc.poll() is None:
        pid = camoufox_proc.pid
        logger.info(f"Terminating Camoufox internal subprocess (PID: {pid})...")
        try:
            if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                try:
                    pgid = os.getpgid(pid)
                    logger.info(f"  Sending SIGTERM to Camoufox process group (PGID: {pgid})...")
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    logger.info(f"  Camoufox process group (PID: {pid}) not found, attempting direct termination...")
                    camoufox_proc.terminate()
            else:
                if sys.platform == "win32":
                    logger.info(f"Sending termination request to process tree (PID: {pid})")
                    subprocess.call(['taskkill', '/T', '/PID', str(pid)])
                else:
                    logger.info(f"  Sending SIGTERM to Camoufox (PID: {pid})...")
                    camoufox_proc.terminate()
            camoufox_proc.wait(timeout=5)
            logger.info(f"  ✓ Camoufox (PID: {pid}) successfully terminated via SIGTERM.")
        except subprocess.TimeoutExpired:
            logger.warning(f"  ⚠️ Camoufox (PID: {pid}) SIGTERM timed out. Sending SIGKILL to force terminate...")
            if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                try:
                    pgid = os.getpgid(pid)
                    logger.info(f"  Sending SIGKILL to Camoufox process group (PGID: {pgid})...")
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    logger.info(f"  Camoufox process group (PID: {pid}) not found during SIGKILL, attempting direct force kill...")
                    camoufox_proc.kill()
            else:
                if sys.platform == "win32":
                    logger.info(f"  Force killing Camoufox process tree (PID: {pid})")
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
                else:
                    camoufox_proc.kill()
            try:
                camoufox_proc.wait(timeout=2)
                logger.info(f"  ✓ Camoufox (PID: {pid}) successfully terminated via SIGKILL.")
            except Exception as e_kill:
                logger.error(f"  ❌ Error waiting for Camoufox (PID: {pid}) SIGKILL completion: {e_kill}")
        except Exception as e_term:
            logger.error(f"  ❌ Error terminating Camoufox (PID: {pid}): {e_term}", exc_info=True)
        finally:
            if hasattr(camoufox_proc, 'stdout') and camoufox_proc.stdout and not camoufox_proc.stdout.closed:
                camoufox_proc.stdout.close()
            if hasattr(camoufox_proc, 'stderr') and camoufox_proc.stderr and not camoufox_proc.stderr.closed:
                camoufox_proc.stderr.close()
        camoufox_proc = None
    elif camoufox_proc:
        logger.info(f"Camoufox internal subprocess (PID: {camoufox_proc.pid if hasattr(camoufox_proc, 'pid') else 'N/A'}) ended previously, exit code: {camoufox_proc.poll()}.")
        camoufox_proc = None
    else:
        logger.info("Camoufox internal subprocess not running or already cleaned up.")
    logger.info("--- Cleanup routine finished (launch_camoufox.py) ---")

atexit.register(cleanup)
def signal_handler(sig, frame):
    logger.info(f"Received signal {signal.Signals(sig).name} ({sig}). Initiating exit procedure...")
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- Check dependencies (check_dependencies) (from dev - more comprehensive) ---
def check_dependencies():
    logger.info("--- Step 1: Check Dependencies ---")
    required_modules = {}
    if launch_server is not None and DefaultAddons is not None:
        required_modules["camoufox"] = "camoufox (for server and addons)"
    elif launch_server is not None:
        required_modules["camoufox_server"] = "camoufox.server"
        logger.warning("  ⚠️ 'camoufox.server' imported, but 'camoufox.DefaultAddons' not imported. Addon exclusion features might be limited.")
    missing_py_modules = []
    dependencies_ok = True
    if required_modules:
        logger.info("Checking Python modules:")
        for module_name, install_package_name in required_modules.items():
            try:
                __import__(module_name)
                logger.info(f"  ✓ Module '{module_name}' found.")
            except ImportError:
                logger.error(f"  ❌ Module '{module_name}' (package: '{install_package_name}') not found.")
                missing_py_modules.append(install_package_name)
                dependencies_ok = False
    else:
        # Check if internal launch mode, if so, camoufox must be importable
        is_any_internal_arg = any(arg.startswith('--internal-') for arg in sys.argv)
        if is_any_internal_arg and (launch_server is None or DefaultAddons is None):
            logger.error(f"  ❌ Internal launch mode (--internal-*) requires 'camoufox' package, but import failed.")
            dependencies_ok = False
        elif not is_any_internal_arg:
             logger.info("Internal launch mode not requested and camoufox.server not imported, skipping 'camoufox' Python package check.")


    try:
        from server import app as server_app_check
        if server_app_check:
             logger.info(f"  ✓ Successfully imported 'app' object from 'server.py'.")
    except ImportError as e_import_server:
        logger.error(f"  ❌ Failed to import 'app' object from 'server.py': {e_import_server}")
        logger.error(f"     Please ensure 'server.py' exists and has no import errors.")
        dependencies_ok = False

    if not dependencies_ok:
        logger.error("-------------------------------------------------")
        logger.error("❌ Dependency check failed!")
        if missing_py_modules:
            logger.error(f"   Missing Python libraries: {', '.join(missing_py_modules)}")
            logger.error(f"   Please try installing via pip: pip install {' '.join(missing_py_modules)}")
        logger.error("-------------------------------------------------")
        sys.exit(1)
    else:
        logger.info("✅ All launcher dependency checks passed.")

# --- Port check and cleanup functions (from dev - more robust) ---
def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return False
        except OSError:
            return True
        except Exception as e:
            logger.warning(f"Unknown error checking port {port} (host {host}): {e}")
            return True

def find_pids_on_port(port: int) -> list[int]:
    pids = []
    system_platform = platform.system()
    command = ""
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            command = f"lsof -ti :{port} -sTCP:LISTEN"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode == 0 and stdout:
                pids = [int(pid) for pid in stdout.strip().split('\n') if pid.isdigit()]
            elif process.returncode != 0 and ("command not found" in stderr.lower() or "未找到命令" in stderr):
                logger.error(f"Command 'lsof' not found. Please ensure it is installed.")
            elif process.returncode not in [0, 1]: # lsof returns 1 when not found
                logger.warning(f"Failed to execute lsof command (return code {process.returncode}): {stderr.strip()}")
        elif system_platform == "Windows":
            command = f'netstat -ano -p TCP | findstr "LISTENING" | findstr ":{port} "'
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode == 0 and stdout:
                for line in stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 4 and parts[0].upper() == 'TCP' and f":{port}" in parts[1]:
                        if parts[-1].isdigit(): pids.append(int(parts[-1]))
                pids = list(set(pids)) # Remove duplicates
            elif process.returncode not in [0, 1]: # findstr returns 1 when not found
                logger.warning(f"Failed to execute netstat/findstr command (return code {process.returncode}): {stderr.strip()}")
        else:
            logger.warning(f"Unsupported OS '{system_platform}' for finding processes on port.")
    except FileNotFoundError:
        cmd_name = command.split()[0] if command else "Related tool"
        logger.error(f"Command '{cmd_name}' not found.")
    except subprocess.TimeoutExpired:
        logger.error(f"Command '{command}' timed out.")
    except Exception as e:
        logger.error(f"Error finding processes on port {port}: {e}", exc_info=True)
    return pids

def kill_process_interactive(pid: int) -> bool:
    system_platform = platform.system()
    success = False
    logger.info(f"  Attempting to terminate process PID: {pid}...")
    try:
        if system_platform == "Linux" or system_platform == "Darwin":
            result_term = subprocess.run(f"kill {pid}", shell=True, capture_output=True, text=True, timeout=3, check=False)
            if result_term.returncode == 0:
                logger.info(f"    ✓ PID {pid} sent SIGTERM signal.")
                success = True
            else:
                logger.warning(f"    PID {pid} SIGTERM failed: {result_term.stderr.strip() or result_term.stdout.strip()}. Attempting SIGKILL...")
                result_kill = subprocess.run(f"kill -9 {pid}", shell=True, capture_output=True, text=True, timeout=3, check=False)
                if result_kill.returncode == 0:
                    logger.info(f"    ✓ PID {pid} sent SIGKILL signal.")
                    success = True
                else:
                    logger.error(f"    ✗ PID {pid} SIGKILL failed: {result_kill.stderr.strip() or result_kill.stdout.strip()}.")
        elif system_platform == "Windows":
            command_desc = f"taskkill /PID {pid} /T /F"
            result = subprocess.run(command_desc, shell=True, capture_output=True, text=True, timeout=5, check=False)
            output = result.stdout.strip()
            error_output = result.stderr.strip()
            if result.returncode == 0 and ("SUCCESS" in output.upper() or "成功" in output):
                logger.info(f"    ✓ PID {pid} terminated via taskkill /F.")
                success = True
            elif "could not find process" in error_output.lower() or "找不到" in error_output: # Process might have exited itself
                logger.info(f"    PID {pid} not found during taskkill (might have exited).")
                success = True # Considered success as target is port availability
            else:
                logger.error(f"    ✗ PID {pid} taskkill /F failed: {(error_output + ' ' + output).strip()}.")
        else:
            logger.warning(f"    Unsupported OS '{system_platform}' for process termination.")
    except Exception as e:
        logger.error(f"    Unexpected error terminating PID {pid}: {e}", exc_info=True)
    return success

# --- Input function with timeout (from dev - more robust Windows implementation) ---
def input_with_timeout(prompt_message: str, timeout_seconds: int = 30) -> str:
    print(prompt_message, end='', flush=True)
    if sys.platform == "win32":
        user_input_container = [None]
        def get_input_in_thread():
            try:
                user_input_container[0] = sys.stdin.readline().strip()
            except Exception:
                user_input_container[0] = "" # Return empty string on error
        input_thread = threading.Thread(target=get_input_in_thread, daemon=True)
        input_thread.start()
        input_thread.join(timeout=timeout_seconds)
        if input_thread.is_alive():
            print("\nInput timed out. Using default value.", flush=True)
            return ""
        return user_input_container[0] if user_input_container[0] is not None else ""
    else: # Linux/macOS
        readable_fds, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
        if readable_fds:
            return sys.stdin.readline().strip()
        else:
            print("\nInput timed out. Using default value.", flush=True)
            return ""

def get_proxy_from_gsettings():
    """
    Retrieves the proxy settings from GSettings on Linux systems.
    Returns a proxy string like "http://host:port" or None.
    """
    def _run_gsettings_command(command_parts: list[str]) -> str | None:
        """Helper function to run gsettings command and return cleaned string output."""
        try:
            process_result = subprocess.run(
                command_parts,
                capture_output=True,
                text=True,
                check=False, # Do not raise CalledProcessError for non-zero exit codes
                timeout=1  # Timeout for the subprocess call
            )
            if process_result.returncode == 0:
                value = process_result.stdout.strip()
                if value.startswith("'") and value.endswith("'"): # Remove surrounding single quotes
                    value = value[1:-1]

                # If after stripping quotes, value is empty, or it's a gsettings "empty" representation
                if not value or value == "''" or value == "@as []" or value == "[]":
                    return None
                return value
            else:
                return None
        except subprocess.TimeoutExpired:
            return None
        except Exception: # Broad exception as per pseudocode
            return None

    proxy_mode = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy", "mode"])

    if proxy_mode == "manual":
        # Try HTTP proxy first
        http_host = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.http", "host"])
        http_port_str = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.http", "port"])

        if http_host and http_port_str:
            try:
                http_port = int(http_port_str)
                if http_port > 0:
                    return f"http://{http_host}:{http_port}"
            except ValueError:
                pass  # Continue to HTTPS

        # Try HTTPS proxy if HTTP not found or invalid
        https_host = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.https", "host"])
        https_port_str = _run_gsettings_command(["gsettings", "get", "org.gnome.system.proxy.https", "port"])

        if https_host and https_port_str:
            try:
                https_port = int(https_port_str)
                if https_port > 0:
                    # Note: Even for HTTPS proxy settings, the scheme for Playwright/requests is usually http://
                    return f"http://{https_host}:{https_port}"
            except ValueError:
                pass

    return None


def determine_proxy_configuration(internal_camoufox_proxy_arg=None):
    """
    Unified proxy configuration determination function
    Order of priority: Command line args > Env vars > System settings

    Args:
        internal_camoufox_proxy_arg: --internal-camoufox-proxy command line argument value

    Returns:
        dict: Dictionary containing proxy configuration info
        {
            'camoufox_proxy': str or None,  # Proxy used by Camoufox browser
            'stream_proxy': str or None,    # Upstream proxy used by stream proxy service
            'source': str                   # Proxy source description
        }
    """
    result = {
        'camoufox_proxy': None,
        'stream_proxy': None,
        'source': 'No Proxy'
    }

    # 1. Prefer command line arguments
    if internal_camoufox_proxy_arg is not None:
        if internal_camoufox_proxy_arg.strip():  # Non-empty string
            result['camoufox_proxy'] = internal_camoufox_proxy_arg.strip()
            result['stream_proxy'] = internal_camoufox_proxy_arg.strip()
            result['source'] = f"Command line arg --internal-camoufox-proxy: {internal_camoufox_proxy_arg.strip()}"
        else:  # Empty string, explicitly disable proxy
            result['source'] = "Command line arg --internal-camoufox-proxy='' (explicitly disabled)"
        return result

    # 2. Try env var UNIFIED_PROXY_CONFIG (priority over HTTP/HTTPS_PROXY)
    unified_proxy = os.environ.get("UNIFIED_PROXY_CONFIG")
    if unified_proxy:
        result['camoufox_proxy'] = unified_proxy
        result['stream_proxy'] = unified_proxy
        result['source'] = f"Env var UNIFIED_PROXY_CONFIG: {unified_proxy}"
        return result

    # 3. Try env var HTTP_PROXY
    http_proxy = os.environ.get("HTTP_PROXY")
    if http_proxy:
        result['camoufox_proxy'] = http_proxy
        result['stream_proxy'] = http_proxy
        result['source'] = f"Env var HTTP_PROXY: {http_proxy}"
        return result

    # 4. Try env var HTTPS_PROXY
    https_proxy = os.environ.get("HTTPS_PROXY")
    if https_proxy:
        result['camoufox_proxy'] = https_proxy
        result['stream_proxy'] = https_proxy
        result['source'] = f"Env var HTTPS_PROXY: {https_proxy}"
        return result

    # 5. Try system proxy settings (Linux only)
    if sys.platform.startswith('linux'):
        gsettings_proxy = get_proxy_from_gsettings()
        if gsettings_proxy:
            result['camoufox_proxy'] = gsettings_proxy
            result['stream_proxy'] = gsettings_proxy
            result['source'] = f"gsettings system proxy: {gsettings_proxy}"
            return result

    return result


# --- Main Execution Logic ---
if __name__ == "__main__":
    # Check if internal launch call; if so, do not configure launcher logging
    is_internal_call = any(arg.startswith('--internal-') for arg in sys.argv)
    if not is_internal_call:
        setup_launcher_logging(log_level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Launcher for Camoufox browser simulation and FastAPI proxy server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Internal arguments (from dev)
    parser.add_argument('--internal-launch-mode', type=str, choices=['debug', 'headless', 'virtual_headless'], help=argparse.SUPPRESS)
    parser.add_argument('--internal-auth-file', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-port', type=int, default=DEFAULT_CAMOUFOX_PORT, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-proxy', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--internal-camoufox-os', type=str, default="random", help=argparse.SUPPRESS)


    # User visible arguments (merged from dev and helper)
    parser.add_argument("--server-port", type=int, default=DEFAULT_SERVER_PORT, help=f"Port number for FastAPI server (Default: {DEFAULT_SERVER_PORT})")
    parser.add_argument(
        "--stream-port",
        type=int,
        default=DEFAULT_STREAM_PORT, # Read default from .env
        help=(
            f"Port for stream proxy server. "
            f"Provide --stream-port=0 to disable. Default: {DEFAULT_STREAM_PORT}"
        )
    )
    parser.add_argument(
        "--helper",
        type=str,
        default=DEFAULT_HELPER_ENDPOINT, # Use default value
        help=(
            f"Helper server getStreamResponse endpoint (e.g., http://127.0.0.1:3121/getStreamResponse). "
            f"Provide empty string (e.g., --helper='') to disable. Default: {DEFAULT_HELPER_ENDPOINT}"
        )
    )
    parser.add_argument(
        "--camoufox-debug-port", # from dev
        type=int,
        default=DEFAULT_CAMOUFOX_PORT,
        help=f"Debug port number for internal Camoufox instance (Default: {DEFAULT_CAMOUFOX_PORT})"
    )
    mode_selection_group = parser.add_mutually_exclusive_group() # from dev (more options)
    mode_selection_group.add_argument("--debug", action="store_true", help="Start debug mode (browser UI visible, allows interactive auth)")
    mode_selection_group.add_argument("--headless", action="store_true", help="Start headless mode (no browser UI, requires saved auth file)")
    mode_selection_group.add_argument("--virtual-display", action="store_true", help="Start headless mode with virtual display (Xvfb, Linux only)") # from dev

    # --camoufox-os argument removed, will be auto-detected and set by script
    parser.add_argument( # from dev
        "--active-auth-json", type=str, default=None,
        help="[Headless/Debug Optional] Path to active auth JSON file (in auth_profiles/active/ or saved/, or absolute path). "
             "If not provided, headless mode uses latest in active/, debug mode prompts or uses none."
    )
    parser.add_argument( # from dev
        "--auto-save-auth", action='store_true',
        help="[Debug Mode] Automatically prompt to save new auth state after successful login if no auth file was loaded."
    )
    parser.add_argument(
        "--save-auth-as", type=str, default=None,
        help="[Debug Mode] Specify filename for saving new auth file (without .json suffix)."
    )
    parser.add_argument( # from dev
        "--auth-save-timeout", type=int, default=DEFAULT_AUTH_SAVE_TIMEOUT,
        help=f"[Debug Mode] Timeout (seconds) for auto-save auth or filename input. Default: {DEFAULT_AUTH_SAVE_TIMEOUT}"
    )
    parser.add_argument(
        "--exit-on-auth-save", action='store_true',
        help="[Debug Mode] Automatically close launcher and all processes after successful auth save via UI."
    )
    # Logging related arguments (from dev)
    parser.add_argument(
        "--server-log-level", type=str, default=DEFAULT_SERVER_LOG_LEVEL, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"Log level for server.py. Default: {DEFAULT_SERVER_LOG_LEVEL}"
    )
    parser.add_argument(
        "--server-redirect-print", action='store_true',
        help="Redirect print output in server.py to its logging system. Default is not to redirect so input() prompts in debug mode are visible."
    )
    parser.add_argument("--debug-logs", action='store_true', help="Enable DEBUG level detailed logs inside server.py (env DEBUG_LOGS_ENABLED).")
    parser.add_argument("--trace-logs", action='store_true', help="Enable TRACE level more detailed logs inside server.py (env TRACE_LOGS_ENABLED).")

    args = parser.parse_args()

    # --- Auto-detect current system and set Camoufox OS simulation ---
    # This variable will be used for internal Camoufox launch and HOST_OS_FOR_SHORTCUT
    current_system_for_camoufox = platform.system()
    if current_system_for_camoufox == "Linux":
        simulated_os_for_camoufox = "linux"
    elif current_system_for_camoufox == "Windows":
        simulated_os_for_camoufox = "windows"
    elif current_system_for_camoufox == "Darwin": # macOS
        simulated_os_for_camoufox = "macos"
    else:
        simulated_os_for_camoufox = "linux" # Default fallback for unknown systems
        logger.warning(f"Unrecognized system '{current_system_for_camoufox}'. Camoufox OS simulation defaulting to: {simulated_os_for_camoufox}")
    logger.info(f"Based on system '{current_system_for_camoufox}', Camoufox OS simulation auto-set to: {simulated_os_for_camoufox}")

    # --- Handle internal Camoufox launch logic (if script called as subprocess) (from dev) ---
    if args.internal_launch_mode:
        if not launch_server or not DefaultAddons:
            print("❌ Fatal Error (--internal-launch-mode): camoufox.server.launch_server or camoufox.DefaultAddons unavailable. Script cannot proceed.", file=sys.stderr)
            sys.exit(1)

        internal_mode_arg = args.internal_launch_mode
        auth_file = args.internal_auth_file
        camoufox_port_internal = args.internal_camoufox_port
        # Use unified proxy configuration determination logic
        proxy_config = determine_proxy_configuration(args.internal_camoufox_proxy)
        actual_proxy_to_use = proxy_config['camoufox_proxy']
        print(f"--- [Internal Camoufox Launch] Proxy Config: {proxy_config['source']} ---", flush=True)

        camoufox_proxy_internal = actual_proxy_to_use # Update variable for later use
        camoufox_os_internal = args.internal_camoufox_os


        print(f"--- [Internal Camoufox Launch] Mode: {internal_mode_arg}, Auth File: {os.path.basename(auth_file) if auth_file else 'None'}, "
              f"Camoufox Port: {camoufox_port_internal}, Proxy: {camoufox_proxy_internal or 'None'}, Sim OS: {camoufox_os_internal} ---", flush=True)
        print(f"--- [Internal Camoufox Launch] Calling camoufox.server.launch_server ... ---", flush=True)

        try:
            launch_args_for_internal_camoufox = {
                "port": camoufox_port_internal,
                "addons": [],
                # "proxy": camoufox_proxy_internal, # Removed
                "exclude_addons": [DefaultAddons.UBO], # Assuming DefaultAddons.UBO exists
                "window": (1440, 900)
            }

            # Correct way to add proxy
            if camoufox_proxy_internal: # If proxy string exists and is not empty
                launch_args_for_internal_camoufox["proxy"] = {"server": camoufox_proxy_internal}
            # If camoufox_proxy_internal is None or empty, "proxy" key won't be added.
            if auth_file:
                launch_args_for_internal_camoufox["storage_state"] = auth_file

            if "," in camoufox_os_internal:
                camoufox_os_list_internal = [s.strip().lower() for s in camoufox_os_internal.split(',')]
                valid_os_values = ["windows", "macos", "linux"]
                if not all(val in valid_os_values for val in camoufox_os_list_internal):
                    print(f"❌ Internal Camoufox Launch Error: Invalid values in camoufox_os_internal list: {camoufox_os_list_internal}", file=sys.stderr)
                    sys.exit(1)
                launch_args_for_internal_camoufox['os'] = camoufox_os_list_internal
            elif camoufox_os_internal.lower() in ["windows", "macos", "linux"]:
                launch_args_for_internal_camoufox['os'] = camoufox_os_internal.lower()
            elif camoufox_os_internal.lower() != "random":
                print(f"❌ Internal Camoufox Launch Error: Invalid camoufox_os_internal value: '{camoufox_os_internal}'", file=sys.stderr)
                sys.exit(1)

            print(f"  Args passed to launch_server: {launch_args_for_internal_camoufox}", flush=True)

            if internal_mode_arg == 'headless':
                launch_server(headless=True, **launch_args_for_internal_camoufox)
            elif internal_mode_arg == 'virtual_headless':
                launch_server(headless="virtual", **launch_args_for_internal_camoufox)
            elif internal_mode_arg == 'debug':
                launch_server(headless=False, **launch_args_for_internal_camoufox)

            print(f"--- [Internal Camoufox Launch] camoufox.server.launch_server ({internal_mode_arg} mode) call finished/blocked. Script will wait for it to end. ---", flush=True)
        except Exception as e_internal_launch_final:
            print(f"❌ Error (--internal-launch-mode): Exception executing camoufox.server.launch_server: {e_internal_launch_final}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # --- Main Launcher Logic ---
    logger.info("🚀 Camoufox Launcher Started 🚀")
    logger.info("=================================================")
    ensure_auth_dirs_exist()
    check_dependencies()
    logger.info("=================================================")

    deprecated_auth_state_path = os.path.join(os.path.dirname(__file__), "auth_state.json")
    if os.path.exists(deprecated_auth_state_path):
        logger.warning(f"Detected deprecated auth file: {deprecated_auth_state_path}. This file is no longer used directly.")
        logger.warning("Please use debug mode to generate new auth files and manage files in 'auth_profiles' directory.")

    final_launch_mode = None # from dev
    if args.debug:
        final_launch_mode = 'debug'
    elif args.headless:
        final_launch_mode = 'headless'
    elif args.virtual_display: # from dev
        final_launch_mode = 'virtual_headless'
        if platform.system() != "Linux":
            logger.warning("⚠️ --virtual-display mode is mainly for Linux. On non-Linux systems, behavior may be identical to standard headless or cause internal errors.")
    else:
        # Read LAUNCH_MODE from .env as default
        env_launch_mode = os.environ.get('LAUNCH_MODE', '').lower()
        default_mode_from_env = None
        default_interactive_choice = '1'  # Default choice: headless

        # Map LAUNCH_MODE from .env to interactive choices
        if env_launch_mode == 'headless':
            default_mode_from_env = 'headless'
            default_interactive_choice = '1'
        elif env_launch_mode == 'debug' or env_launch_mode == 'normal':
            default_mode_from_env = 'debug'
            default_interactive_choice = '2'
        elif env_launch_mode == 'virtual_display' or env_launch_mode == 'virtual_headless':
            default_mode_from_env = 'virtual_headless'
            default_interactive_choice = '3' if platform.system() == "Linux" else '1'

        logger.info("--- Select Launch Mode (not specified via args) ---")
        if env_launch_mode and default_mode_from_env:
            logger.info(f"  Read default launch mode from .env: {env_launch_mode} -> {default_mode_from_env}")

        prompt_options_text = "[1] Headless, [2] Debug"
        valid_choices = {'1': 'headless', '2': 'debug'}

        if platform.system() == "Linux": # from dev
            prompt_options_text += ", [3] Headless (Virtual Display Xvfb)"
            valid_choices['3'] = 'virtual_headless'

        # Build prompt showing current default
        default_mode_name = valid_choices.get(default_interactive_choice, 'headless')
        user_mode_choice = input_with_timeout(
            f"  Enter launch mode ({prompt_options_text}; Default: {default_interactive_choice} {default_mode_name} mode, 15s timeout): ", 15
        ) or default_interactive_choice

        if user_mode_choice in valid_choices:
            final_launch_mode = valid_choices[user_mode_choice]
        else:
            final_launch_mode = default_mode_from_env or 'headless' # Use .env default or fallback to headless
            logger.info(f"Invalid input '{user_mode_choice}' or timeout, using default mode: {final_launch_mode} mode")
    logger.info(f"Final selected launch mode: {final_launch_mode.replace('_', ' ')} mode")
    logger.info("-------------------------------------------------")

    effective_active_auth_json_path = None # Initialize early

    # --- Interactive Auth File Creation Logic ---
    if final_launch_mode == 'debug' and not args.active_auth_json:
        create_new_auth_choice = input_with_timeout(
            "  Create and save new auth file? (y/n; Default: n, 15s timeout): ", 15
        ).strip().lower()
        if create_new_auth_choice == 'y':
            new_auth_filename = ""
            while not new_auth_filename:
                new_auth_filename_input = input_with_timeout(
                    f"  Enter filename to save (no .json suffix, alphanumeric/-/_): ", args.auth_save_timeout
                ).strip()
                # Simple validation
                if re.match(r"^[a-zA-Z0-9_-]+$", new_auth_filename_input):
                    new_auth_filename = new_auth_filename_input
                elif new_auth_filename_input == "":
                    logger.info("Input empty or timeout, cancelled creating new auth file.")
                    break
                else:
                    print("  Filename contains invalid characters, please retry.")

            if new_auth_filename:
                args.auto_save_auth = True
                args.save_auth_as = new_auth_filename
                logger.info(f"  Okay, will auto-save auth file as: {new_auth_filename}.json after successful login")
                # In this mode, should not load any existing auth files
                if effective_active_auth_json_path:
                    logger.info("  Cleared previously loaded auth file settings as new auth file will be created.")
                    effective_active_auth_json_path = None
        else:
            logger.info("  Okay, will not create new auth file.")

    if final_launch_mode == 'virtual_headless' and platform.system() == "Linux": # from dev
        logger.info("--- Check Xvfb (Virtual Display) Dependency ---")
        if not shutil.which("Xvfb"):
            logger.error("  ❌ Xvfb not found. Virtual display mode requires Xvfb. Please install (e.g., sudo apt-get install xvfb) and retry.")
            sys.exit(1)
        logger.info("  ✓ Xvfb found.")

    server_target_port = args.server_port
    logger.info(f"--- Step 2: Check if FastAPI server target port ({server_target_port}) is in use ---")
    port_is_available = False
    uvicorn_bind_host = "0.0.0.0" # from dev (was 127.0.0.1 in helper)
    if is_port_in_use(server_target_port, host=uvicorn_bind_host):
        logger.warning(f"  ❌ Port {server_target_port} (host {uvicorn_bind_host}) currently in use.")
        pids_on_port = find_pids_on_port(server_target_port)
        if pids_on_port:
            logger.warning(f"     Identified PIDs potentially using port {server_target_port}: {pids_on_port}")
            if final_launch_mode == 'debug':
                sys.stderr.flush()
                # Using input_with_timeout for consistency, though timeout might not be strictly needed here
                choice = input_with_timeout(f"     Attempt to terminate these processes? (y/n, n continues and may fail, 15s timeout): ", 15).strip().lower()
                if choice == 'y':
                    logger.info("     User selected to attempt termination...")
                    all_killed = all(kill_process_interactive(pid) for pid in pids_on_port)
                    time.sleep(2)
                    if not is_port_in_use(server_target_port, host=uvicorn_bind_host):
                        logger.info(f"     ✅ Port {server_target_port} (host {uvicorn_bind_host}) is now available.")
                        port_is_available = True
                    else:
                        logger.error(f"     ❌ Port {server_target_port} (host {uvicorn_bind_host}) still in use after termination attempt.")
                else:
                    logger.info("     User selected not to auto-terminate or timed out. Continuing server start attempt.")
            else:
                 logger.error(f"     Headless mode will not attempt auto-termination of port-hogging processes. Server start may fail.")
        else:
            logger.warning(f"     Could not auto-identify processes using port {server_target_port}. Server start may fail.")

        if not port_is_available:
            logger.warning(f"--- Port {server_target_port} might still be in use. Continuing, server will handle binding. ---")
    else:
        logger.info(f"  ✅ Port {server_target_port} (host {uvicorn_bind_host}) is currently available.")
        port_is_available = True


    logger.info("--- Step 3: Prepare and start Camoufox internal process ---")
    captured_ws_endpoint = None
    # effective_active_auth_json_path = None # from dev # Initialized early

    if args.active_auth_json:
        logger.info(f"  Attempting to use path from --active-auth-json: '{args.active_auth_json}'")
        candidate_path = os.path.expanduser(args.active_auth_json)

        # Attempt to resolve path:
        # 1. As absolute path
        if os.path.isabs(candidate_path) and os.path.exists(candidate_path) and os.path.isfile(candidate_path):
            effective_active_auth_json_path = candidate_path
        else:
            # 2. As path relative to CWD
            path_rel_to_cwd = os.path.abspath(candidate_path)
            if os.path.exists(path_rel_to_cwd) and os.path.isfile(path_rel_to_cwd):
                effective_active_auth_json_path = path_rel_to_cwd
            else:
                # 3. As path relative to script directory
                path_rel_to_script = os.path.join(os.path.dirname(__file__), candidate_path)
                if os.path.exists(path_rel_to_script) and os.path.isfile(path_rel_to_script):
                    effective_active_auth_json_path = path_rel_to_script
                # 4. If just a filename, check in ACTIVE_AUTH_DIR then SAVED_AUTH_DIR
                elif not os.path.sep in candidate_path: # This is a simple filename
                    path_in_active = os.path.join(ACTIVE_AUTH_DIR, candidate_path)
                    if os.path.exists(path_in_active) and os.path.isfile(path_in_active):
                        effective_active_auth_json_path = path_in_active
                    else:
                        path_in_saved = os.path.join(SAVED_AUTH_DIR, candidate_path)
                        if os.path.exists(path_in_saved) and os.path.isfile(path_in_saved):
                            effective_active_auth_json_path = path_in_saved

        if effective_active_auth_json_path:
            logger.info(f"  Using resolved auth file from --active-auth-json: {effective_active_auth_json_path}")
        else:
            logger.error(f"❌ Specified auth file (--active-auth-json='{args.active_auth_json}') not found or not a file.")
            sys.exit(1)
    else:
        # --active-auth-json not provided.
        if final_launch_mode == 'debug':
            # For debug mode, scan dirs and prompt user, don't auto-use files
            logger.info(f"  Debug Mode: Scanning directories to prompt user selection from available auth files...")
        else:
            # For headless mode, check default auth file in active/ dir
            logger.info(f"  --active-auth-json not provided. Checking default auth file in '{ACTIVE_AUTH_DIR}'...")
            try:
                if os.path.exists(ACTIVE_AUTH_DIR):
                    active_json_files = sorted([
                        f for f in os.listdir(ACTIVE_AUTH_DIR)
                        if f.lower().endswith('.json') and os.path.isfile(os.path.join(ACTIVE_AUTH_DIR, f))
                    ])
                    if active_json_files:
                        effective_active_auth_json_path = os.path.join(ACTIVE_AUTH_DIR, active_json_files[0])
                        logger.info(f"  Using first alphabetic JSON file in '{ACTIVE_AUTH_DIR}': {os.path.basename(effective_active_auth_json_path)}")
                    else:
                        logger.info(f"  Directory '{ACTIVE_AUTH_DIR}' empty or contains no JSON files.")
                else:
                    logger.info(f"  Directory '{ACTIVE_AUTH_DIR}' does not exist.")
            except Exception as e_scan_active:
                logger.warning(f"  Error scanning '{ACTIVE_AUTH_DIR}': {e_scan_active}", exc_info=True)

        # Handle debug mode user selection logic
        if final_launch_mode == 'debug' and not args.auto_save_auth:
            # For debug mode, scan all directories and prompt user
            available_profiles = []
            # Scan ACTIVE_AUTH_DIR first, then SAVED_AUTH_DIR
            for profile_dir_path_str, dir_label in [(ACTIVE_AUTH_DIR, "active"), (SAVED_AUTH_DIR, "saved")]:
                if os.path.exists(profile_dir_path_str):
                    try:
                        # Sort filenames in each directory
                        filenames = sorted([
                            f for f in os.listdir(profile_dir_path_str)
                            if f.lower().endswith(".json") and os.path.isfile(os.path.join(profile_dir_path_str, f))
                        ])
                        for filename in filenames:
                            full_path = os.path.join(profile_dir_path_str, filename)
                            available_profiles.append({"name": f"{dir_label}/{filename}", "path": full_path})
                    except OSError as e:
                        logger.warning(f"   ⚠️ Warning: Cannot read directory '{profile_dir_path_str}': {e}")

            if available_profiles:
                # Sort available profile list for consistent display
                available_profiles.sort(key=lambda x: x['name'])
                print('-'*60 + "\n   Found the following available auth files:", flush=True)
                for i, profile in enumerate(available_profiles): print(f"     {i+1}: {profile['name']}", flush=True)
                print("     N: Do not load any file (Use browser current state)\n" + '-'*60, flush=True)
                choice = input_with_timeout(f"   Select auth file number to load (Enter N or Enter to skip, {args.auth_save_timeout}s timeout): ", args.auth_save_timeout)
                if choice.strip().lower() not in ['n', '']:
                    try:
                        choice_index = int(choice.strip()) - 1
                        if 0 <= choice_index < len(available_profiles):
                            selected_profile = available_profiles[choice_index]
                            effective_active_auth_json_path = selected_profile["path"]
                            logger.info(f"   Selected to load auth file: {selected_profile['name']}")
                            print(f"   Selected loading: {selected_profile['name']}", flush=True)
                        else:
                            logger.info("   Invalid selection number or timeout. Will not load auth file.")
                            print("   Invalid selection number or timeout. Will not load auth file.", flush=True)
                    except ValueError:
                        logger.info("   Invalid input. Will not load auth file.")
                        print("   Invalid input. Will not load auth file.", flush=True)
                else:
                    logger.info("   Okay, no auth file loaded or timeout.")
                    print("   Okay, no auth file loaded or timeout.", flush=True)
                print('-'*60, flush=True)
            else:
                logger.info("   No auth files found. Using browser current state.")
                print("   No auth files found. Using browser current state.", flush=True)
        elif not effective_active_auth_json_path and not args.auto_save_auth:
            # For headless mode, error if --active-auth-json not provided and active/ empty
            logger.error(f"  ❌ {final_launch_mode} Mode Error: --active-auth-json not provided and no '.json' auth files found in '{ACTIVE_AUTH_DIR}'. Please save one in Debug mode or specify via argument.")
            sys.exit(1)

    # Build Camoufox internal launch command (from dev)
    camoufox_internal_cmd_args = [
        PYTHON_EXECUTABLE, '-u', __file__,
        '--internal-launch-mode', final_launch_mode
    ]
    if effective_active_auth_json_path:
        camoufox_internal_cmd_args.extend(['--internal-auth-file', effective_active_auth_json_path])

    camoufox_internal_cmd_args.extend(['--internal-camoufox-os', simulated_os_for_camoufox])
    camoufox_internal_cmd_args.extend(['--internal-camoufox-port', str(args.camoufox_debug_port)])

    # Fix: Pass proxy args to internal Camoufox process
    if args.internal_camoufox_proxy is not None:
        camoufox_internal_cmd_args.extend(['--internal-camoufox-proxy', args.internal_camoufox_proxy])

    camoufox_popen_kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'env': os.environ.copy()}
    camoufox_popen_kwargs['env']['PYTHONIOENCODING'] = 'utf-8'
    if sys.platform != "win32" and final_launch_mode != 'debug':
        camoufox_popen_kwargs['start_new_session'] = True
    elif sys.platform == "win32" and (final_launch_mode == 'headless' or final_launch_mode == 'virtual_headless'):
         camoufox_popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW


    try:
        logger.info(f"  Executing Camoufox internal launch command: {' '.join(camoufox_internal_cmd_args)}")
        camoufox_proc = subprocess.Popen(camoufox_internal_cmd_args, **camoufox_popen_kwargs)
        logger.info(f"  Camoufox internal process started (PID: {camoufox_proc.pid}). Waiting for WebSocket endpoint output (max {ENDPOINT_CAPTURE_TIMEOUT}s)...")

        camoufox_output_q = queue.Queue()
        camoufox_stdout_reader = threading.Thread(target=_enqueue_output, args=(camoufox_proc.stdout, "stdout", camoufox_output_q, camoufox_proc.pid), daemon=True)
        camoufox_stderr_reader = threading.Thread(target=_enqueue_output, args=(camoufox_proc.stderr, "stderr", camoufox_output_q, camoufox_proc.pid), daemon=True)
        camoufox_stdout_reader.start()
        camoufox_stderr_reader.start()

        ws_capture_start_time = time.time()
        camoufox_ended_streams_count = 0
        while time.time() - ws_capture_start_time < ENDPOINT_CAPTURE_TIMEOUT:
            if camoufox_proc.poll() is not None:
                logger.error(f"  Camoufox internal process (PID: {camoufox_proc.pid}) exited unexpectedly while waiting for WebSocket endpoint, exit code: {camoufox_proc.poll()}.")
                break
            try:
                stream_name, line_from_camoufox = camoufox_output_q.get(timeout=0.2)
                if line_from_camoufox is None:
                    camoufox_ended_streams_count += 1
                    logger.debug(f"  [InternalCamoufox-{stream_name}-PID:{camoufox_proc.pid}] Output stream closed (EOF).")
                    if camoufox_ended_streams_count >= 2:
                        logger.info(f"  All output streams of Camoufox internal process (PID: {camoufox_proc.pid}) closed.")
                        break
                    continue

                log_line_content = f"[InternalCamoufox-{stream_name}-PID:{camoufox_proc.pid}]: {line_from_camoufox.rstrip()}"
                if stream_name == "stderr" or "ERROR" in line_from_camoufox.upper() or "❌" in line_from_camoufox:
                    logger.warning(log_line_content)
                else:
                    logger.info(log_line_content)

                ws_match = ws_regex.search(line_from_camoufox)
                if ws_match:
                    captured_ws_endpoint = ws_match.group(1)
                    logger.info(f"  ✅ Successfully captured WebSocket endpoint from Camoufox internal process: {captured_ws_endpoint[:40]}...")
                    break
            except queue.Empty:
                continue

        if camoufox_stdout_reader.is_alive(): camoufox_stdout_reader.join(timeout=1.0)
        if camoufox_stderr_reader.is_alive(): camoufox_stderr_reader.join(timeout=1.0)

        if not captured_ws_endpoint and (camoufox_proc and camoufox_proc.poll() is None):
            logger.error(f"  ❌ Failed to capture WebSocket endpoint from Camoufox internal process (PID: {camoufox_proc.pid}) within {ENDPOINT_CAPTURE_TIMEOUT} seconds.")
            logger.error("  Camoufox internal process still running but didn't output expected WebSocket endpoint. Check its logs.")
            cleanup()
            sys.exit(1)
        elif not captured_ws_endpoint and (camoufox_proc and camoufox_proc.poll() is not None):
            logger.error(f"  ❌ Camoufox internal process exited, and failed to capture WebSocket endpoint.")
            sys.exit(1)
        elif not captured_ws_endpoint:
            logger.error(f"  ❌ Failed to capture WebSocket endpoint.")
            sys.exit(1)

    except Exception as e_launch_camoufox_internal:
        logger.critical(f"  ❌ Fatal error launching internal Camoufox or capturing WebSocket endpoint: {e_launch_camoufox_internal}", exc_info=True)
        cleanup()
        sys.exit(1)

    # --- Helper mode logic (New implementation) ---
    if args.helper: # If args.helper is not empty (helper enabled by default or user specified)
        logger.info(f"  Helper mode enabled, endpoint: {args.helper}")
        os.environ['HELPER_ENDPOINT'] = args.helper # Set endpoint env var

        if effective_active_auth_json_path:
            logger.info(f"    Attempting to extract SAPISID from auth file '{os.path.basename(effective_active_auth_json_path)}'...")
            sapisid = ""
            try:
                with open(effective_active_auth_json_path, 'r', encoding='utf-8') as file:
                    auth_file_data = json.load(file)
                    if "cookies" in auth_file_data and isinstance(auth_file_data["cookies"], list):
                        for cookie in auth_file_data["cookies"]:
                            if isinstance(cookie, dict) and cookie.get("name") == "SAPISID" and cookie.get("domain") == ".google.com":
                                sapisid = cookie.get("value", "")
                                break
            except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"    ⚠️ Failed to load or parse SAPISID from auth file '{os.path.basename(effective_active_auth_json_path)}': {e}")
            except Exception as e_sapisid_extraction:
                logger.warning(f"    ⚠️ Unknown error extracting SAPISID: {e_sapisid_extraction}")

            if sapisid:
                logger.info(f"    ✅ Successfully loaded SAPISID. Will set HELPER_SAPISID env var.")
                os.environ['HELPER_SAPISID'] = sapisid
            else:
                logger.warning(f"    ⚠️ Valid SAPISID not found in auth file '{os.path.basename(effective_active_auth_json_path)}'. HELPER_SAPISID will not be set.")
                if 'HELPER_SAPISID' in os.environ: # Clean up just in case
                    del os.environ['HELPER_SAPISID']
        else: # args.helper has value (Helper mode enabled), but no auth file
            logger.warning(f"    ⚠️ Helper mode enabled but no valid auth file to extract SAPISID. HELPER_SAPISID will not be set.")
            if 'HELPER_SAPISID' in os.environ: # Clean up
                del os.environ['HELPER_SAPISID']
    else: # args.helper is empty (user disabled helper via --helper='')
        logger.info("  Helper mode disabled via --helper=''.")
        # Clean up related env vars
        if 'HELPER_ENDPOINT' in os.environ:
            del os.environ['HELPER_ENDPOINT']
        if 'HELPER_SAPISID' in os.environ:
            del os.environ['HELPER_SAPISID']

    # --- Step 4: Set env vars and prepare to start FastAPI/Uvicorn server (from dev) ---
    logger.info("--- Step 4: Set env vars and prepare to start FastAPI/Uvicorn server ---")

    if captured_ws_endpoint:
        os.environ['CAMOUFOX_WS_ENDPOINT'] = captured_ws_endpoint
    else:
        logger.error("  Critical Logic Error: WebSocket endpoint not captured but program continuing.")
        sys.exit(1)

    os.environ['LAUNCH_MODE'] = final_launch_mode
    os.environ['SERVER_LOG_LEVEL'] = args.server_log_level.upper()
    os.environ['SERVER_REDIRECT_PRINT'] = str(args.server_redirect_print).lower()
    os.environ['DEBUG_LOGS_ENABLED'] = str(args.debug_logs).lower()
    os.environ['TRACE_LOGS_ENABLED'] = str(args.trace_logs).lower()
    if effective_active_auth_json_path:
        os.environ['ACTIVE_AUTH_JSON_PATH'] = effective_active_auth_json_path
    os.environ['AUTO_SAVE_AUTH'] = str(args.auto_save_auth).lower()
    if args.save_auth_as:
        os.environ['SAVE_AUTH_FILENAME'] = args.save_auth_as
    os.environ['AUTH_SAVE_TIMEOUT'] = str(args.auth_save_timeout)
    os.environ['SERVER_PORT_INFO'] = str(args.server_port)
    os.environ['STREAM_PORT'] = str(args.stream_port)

    # Set unified proxy configuration env var
    proxy_config = determine_proxy_configuration(args.internal_camoufox_proxy)
    if proxy_config['stream_proxy']:
        os.environ['UNIFIED_PROXY_CONFIG'] = proxy_config['stream_proxy']
        logger.info(f"  Setting unified proxy config: {proxy_config['source']}")
    elif 'UNIFIED_PROXY_CONFIG' in os.environ:
        del os.environ['UNIFIED_PROXY_CONFIG']

    host_os_for_shortcut_env = None
    camoufox_os_param_lower = simulated_os_for_camoufox.lower()
    if camoufox_os_param_lower == "macos": host_os_for_shortcut_env = "Darwin"
    elif camoufox_os_param_lower == "windows": host_os_for_shortcut_env = "Windows"
    elif camoufox_os_param_lower == "linux": host_os_for_shortcut_env = "Linux"
    if host_os_for_shortcut_env:
        os.environ['HOST_OS_FOR_SHORTCUT'] = host_os_for_shortcut_env
    elif 'HOST_OS_FOR_SHORTCUT' in os.environ:
        del os.environ['HOST_OS_FOR_SHORTCUT']

    logger.info(f"  Environment variables set for server.app:")
    env_keys_to_log = [
        'CAMOUFOX_WS_ENDPOINT', 'LAUNCH_MODE', 'SERVER_LOG_LEVEL',
        'SERVER_REDIRECT_PRINT', 'DEBUG_LOGS_ENABLED', 'TRACE_LOGS_ENABLED',
        'ACTIVE_AUTH_JSON_PATH', 'AUTO_SAVE_AUTH', 'SAVE_AUTH_FILENAME', 'AUTH_SAVE_TIMEOUT',
        'SERVER_PORT_INFO', 'HOST_OS_FOR_SHORTCUT',
        'HELPER_ENDPOINT', 'HELPER_SAPISID', 'STREAM_PORT',
        'UNIFIED_PROXY_CONFIG'  # Added unified proxy config
    ]
    for key in env_keys_to_log:
        if key in os.environ:
            val_to_log = os.environ[key]
            if key == 'CAMOUFOX_WS_ENDPOINT' and len(val_to_log) > 40: val_to_log = val_to_log[:40] + "..."
            if key == 'ACTIVE_AUTH_JSON_PATH': val_to_log = os.path.basename(val_to_log)
            logger.info(f"    {key}={val_to_log}")
        else:
            logger.info(f"    {key}= (Not Set)")


    # --- Step 5: Start FastAPI/Uvicorn server (from dev) ---
    logger.info(f"--- Step 5: Start Integrated FastAPI Server (Listening on: {args.server_port}) ---")

    if not args.exit_on_auth_save:
        try:
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=args.server_port,
                log_config=None
            )
            logger.info("Uvicorn server stopped.")
        except SystemExit as e_sysexit:
            logger.info(f"Uvicorn or subsystem exited via sys.exit({e_sysexit.code}).")
        except Exception as e_uvicorn:
            logger.critical(f"❌ Fatal error running Uvicorn: {e_uvicorn}", exc_info=True)
            sys.exit(1)
    else:
        logger.info("  --exit-on-auth-save enabled. Server will auto-close after auth save.")

        server_config = uvicorn.Config(app, host="0.0.0.0", port=args.server_port, log_config=None)
        server = uvicorn.Server(server_config)

        stop_watcher = threading.Event()

        def watch_for_saved_auth_and_shutdown():
            os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
            initial_files = set(os.listdir(SAVED_AUTH_DIR))
            logger.info(f"Started monitoring auth save directory: {SAVED_AUTH_DIR}")

            while not stop_watcher.is_set():
                try:
                    current_files = set(os.listdir(SAVED_AUTH_DIR))
                    new_files = current_files - initial_files
                    if new_files:
                        logger.info(f"Detected new saved auth files: {', '.join(new_files)}. Triggering shutdown in 3 seconds...")
                        time.sleep(3)
                        server.should_exit = True
                        logger.info("Shutdown signal sent to Uvicorn server.")
                        break
                    initial_files = current_files
                except Exception as e:
                    logger.error(f"Error monitoring auth directory: {e}", exc_info=True)

                if stop_watcher.wait(1):
                    break
            logger.info("Auth file monitor thread stopped.")

        watcher_thread = threading.Thread(target=watch_for_saved_auth_and_shutdown)

        try:
            watcher_thread.start()
            server.run()
            logger.info("Uvicorn server stopped.")
        except (KeyboardInterrupt, SystemExit) as e:
            event_name = "KeyboardInterrupt" if isinstance(e, KeyboardInterrupt) else f"SystemExit({getattr(e, 'code', '')})"
            logger.info(f"Received {event_name}, shutting down...")
        except Exception as e_uvicorn:
            logger.critical(f"❌ Fatal error running Uvicorn: {e_uvicorn}", exc_info=True)
            sys.exit(1)
        finally:
            stop_watcher.set()
            if watcher_thread.is_alive():
                watcher_thread.join()

    logger.info("🚀 Camoufox Launcher Main Logic Finished 🚀")