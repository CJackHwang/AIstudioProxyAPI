# --- browser_utils/initialization/core.py ---
import asyncio
import logging
import os
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import (
    Browser as AsyncBrowser,
)
from playwright.async_api import (
    BrowserContext as AsyncBrowserContext,
)
from playwright.async_api import (
    Error as PlaywrightAsyncError,
)
from playwright.async_api import (
    Page as AsyncPage,
)
from playwright.async_api import (
    expect as expect_async,
)

from config import (
    AI_STUDIO_URL_PATTERN,
    INPUT_SELECTOR,
    MODEL_NAME_SELECTOR,
    USER_INPUT_END_MARKER_SERVER,
    USER_INPUT_START_MARKER_SERVER,
    GlobalState,
)
from config.selector_utils import (
    INPUT_WRAPPER_SELECTORS,
)

from .auth import wait_for_model_list_and_handle_auth_save
from .debug import setup_debug_listeners
from .network import setup_network_interception_and_scripts

logger = logging.getLogger("AIStudioProxyServer")


async def _wait_for_shutdown():
    """Helper to wait for GlobalState.IS_SHUTTING_DOWN event."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, GlobalState.IS_SHUTTING_DOWN.wait)


async def initialize_page_logic(  # pragma: no cover
    browser: AsyncBrowser, storage_state_path: Optional[str] = None
) -> Tuple[AsyncPage, bool]:
    """
    Initialize page logic, connecting to existing browser

    Args:
        browser: Playwright browser instance
        storage_state_path: Optional authentication file path. If provided, it will be prioritized.
    """
    logger.debug("[Init] Initializing page logic")
    temp_context: Optional[AsyncBrowserContext] = None
    storage_state_path_to_use: Optional[str] = None
    launch_mode = os.environ.get("LAUNCH_MODE", "debug")
    loop = asyncio.get_running_loop()

    # Prioritize the passed storage_state_path
    if storage_state_path:
        if os.path.exists(storage_state_path):
            storage_state_path_to_use = storage_state_path
            logger.debug(f"Using specified auth file: {storage_state_path_to_use}")
        else:
            logger.error(f"Specified auth file does not exist: {storage_state_path}")
            # If it's a clearly specified path but does not exist, it should be an error
            raise RuntimeError(
                f"Specified auth file does not exist: {storage_state_path}"
            )
    else:
        # Fall back to existing environment variable logic
        if launch_mode == "headless" or launch_mode == "virtual_headless":
            # Check for Auto-Auth Rotation on Startup
            if (
                os.environ.get("AUTO_AUTH_ROTATION_ON_STARTUP", "false").lower()
                == "true"
            ):
                logger.info(
                    "   🤖 Auto-Auth Rotation on Startup is ENABLED. Selecting profile..."
                )
                try:
                    # Local import to avoid circular dependencies
                    from browser_utils.auth_rotation import (
                        _get_next_profile,
                        check_profile_cookie_health,
                    )

                    next_profile = _get_next_profile()
                    if next_profile:
                        os.environ["ACTIVE_AUTH_JSON_PATH"] = next_profile
                        logger.info(f"   ✅ Auto-selected profile: {next_profile}")

                        # Check cookie health of selected profile
                        health = check_profile_cookie_health(next_profile)
                        if health["health_status"] == "critical":
                            logger.warning(
                                "   ⚠️ Selected profile has expired authentication cookies. "
                                "Consider refreshing by logging in again in debug mode."
                            )
                    else:
                        logger.warning(
                            "   ⚠️ Auto-Auth Rotation: No available profiles found. Continuing with environment defaults."
                        )
                except ImportError:
                    logger.error(
                        "   ❌ Auto-Auth Rotation failed: Could not import auth_rotation module."
                    )
                except Exception as e:
                    logger.error(
                        f"   ❌ Error during Auto-Auth Rotation on Startup: {e}",
                        exc_info=True,
                    )

            auth_filename = os.environ.get("ACTIVE_AUTH_JSON_PATH")
            logger.info(
                f"[DEBUG] Headless Init: ACTIVE_AUTH_JSON_PATH='{auth_filename}'"
            )

            if auth_filename:
                constructed_path = auth_filename
                if os.path.exists(constructed_path):
                    storage_state_path_to_use = constructed_path
                else:
                    logger.error(
                        f"{launch_mode} mode auth file invalid or does not exist: '{constructed_path}'"
                    )
                    # DIAGNOSTIC: Check if we should have rotated
                    logger.info(
                        f"[DEBUG] Auth file missing. Auto-Rotation Flag: {os.environ.get('AUTO_AUTH_ROTATION_ON_STARTUP')}"
                    )
                    raise RuntimeError(
                        f"{launch_mode} mode auth file invalid: '{constructed_path}'"
                    )
            else:
                logger.error(
                    f"{launch_mode} mode requires ACTIVE_AUTH_JSON_PATH environment variable, but it's not set or is empty."
                )
                raise RuntimeError(
                    f"{launch_mode} mode requires ACTIVE_AUTH_JSON_PATH."
                )
        elif launch_mode == "debug":
            logger.info(
                "Debug mode: Attempting to load auth file from environment variable ACTIVE_AUTH_JSON_PATH..."
            )
            auth_filepath_from_env = os.environ.get("ACTIVE_AUTH_JSON_PATH")
            if auth_filepath_from_env and os.path.exists(auth_filepath_from_env):
                storage_state_path_to_use = auth_filepath_from_env
                logger.debug(
                    f"Auth file to be used in debug mode (from environment variable): {storage_state_path_to_use}"
                )
            elif auth_filepath_from_env:
                logger.warning(
                    f"The file pointed to by ACTIVE_AUTH_JSON_PATH in debug mode does not exist: '{auth_filepath_from_env}'. Auth file not loaded."
                )
            else:
                logger.info(
                    "Auth file not provided via environment variable in debug mode. Current browser state will be used."
                )
        elif launch_mode == "direct_debug_no_browser":
            logger.info(
                "direct_debug_no_browser mode: storage_state not loaded, no browser operations performed."
            )
        else:
            logger.warning(
                f"Warning: Unknown launch mode '{launch_mode}'. storage_state not loaded."
            )

    try:
        # Consolidate into one log message
        auth_file = (
            os.path.basename(storage_state_path_to_use)
            if storage_state_path_to_use
            else None
        )
        # AI Studio's mobile layout (< ~960px) no longer renders the run-settings
        # panel in the DOM, so model-name/temperature/etc. selectors need a
        # desktop-sized viewport (matches the 1440x900 Camoufox window).
        context_options: Dict[str, Any] = {"viewport": {"width": 1440, "height": 900}}
        if storage_state_path_to_use:
            context_options["storage_state"] = storage_state_path_to_use
            from api_utils.server_state import state

            state.current_auth_profile_path = storage_state_path_to_use
            logger.info(
                f"   (Using storage_state='{os.path.basename(storage_state_path_to_use)}')"
            )
        else:
            from api_utils.server_state import state

            state.current_auth_profile_path = None
            logger.info("   (Not using storage_state)")

        # Proxy settings need to be retrieved from the server module
        from api_utils.server_state import state

        if state.PLAYWRIGHT_PROXY_SETTINGS:
            context_options["proxy"] = state.PLAYWRIGHT_PROXY_SETTINGS
            logger.debug(
                f"[Browser] Context configured with proxy: {state.PLAYWRIGHT_PROXY_SETTINGS['server']}"
            )

        context_options["ignore_https_errors"] = True

        # Single consolidated log
        if auth_file:
            logger.info(f"[Browser] Context created (Auth: {auth_file})")
        else:
            logger.debug("[Browser] Context created (No Auth)")

        temp_context = await browser.new_context(**context_options)

        # Set up network interception and script injection
        await setup_network_interception_and_scripts(temp_context)

        found_page: Optional[AsyncPage] = None
        pages = temp_context.pages
        target_url_base = f"https://{AI_STUDIO_URL_PATTERN}"
        target_full_url = f"{target_url_base}prompts/new_chat"
        login_url_pattern = "accounts.google.com"
        current_url = ""

        # Import _handle_model_list_response - delayed import to avoid circular dependency
        from browser_utils.operations import _handle_model_list_response

        for p_iter in pages:
            try:
                page_url_to_check = p_iter.url
                if (
                    not p_iter.is_closed()
                    and target_url_base in page_url_to_check
                    and "/prompts/" in page_url_to_check
                ):
                    found_page = p_iter
                    current_url = page_url_to_check
                    logger.debug(f"Found opened AI Studio page: {current_url}")
                    if found_page:
                        logger.debug(
                            f"Adding model list response listener to existing page {found_page.url}."
                        )
                        found_page.on("response", _handle_model_list_response)
                        # Setup debug listeners for error snapshots
                        setup_debug_listeners(found_page)
                    break
            except PlaywrightAsyncError as pw_err_url:
                logger.warning(f"Playwright error checking page URL: {pw_err_url}")
            except AttributeError as attr_err_url:
                logger.warning(f"Attribute error checking page URL: {attr_err_url}")
            except asyncio.CancelledError:
                raise
            except Exception as e_url_check:
                logger.warning(
                    f"   Other unexpected error checking page URL: {e_url_check} (Type: {type(e_url_check).__name__})"
                )

        if not found_page:
            logger.info(f"[Navigation] Opening new page: {target_full_url}")
            found_page = await temp_context.new_page()
            if found_page:
                logger.debug(
                    "Adding model list response listener to new page (before navigation)."
                )
                found_page.on("response", _handle_model_list_response)
                # Setup debug listeners for error snapshots
                setup_debug_listeners(found_page)
            try:
                await found_page.goto(
                    target_full_url, wait_until="domcontentloaded", timeout=90000
                )
                current_url = found_page.url
                logger.debug(
                    f"New page navigation attempt complete. Current URL: {current_url}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as new_page_nav_err:
                # Import save_error_snapshot function
                from browser_utils.operations import save_error_snapshot

                await save_error_snapshot("init_new_page_nav_fail")
                error_str = str(new_page_nav_err)
                if "NS_ERROR_NET_INTERRUPT" in error_str:
                    logger.error(
                        "\n" + "=" * 30 + " Network Navigation Error Tips " + "=" * 30
                    )
                    logger.error(
                        f"Navigation to '{target_full_url}' failed with network interrupt error (NS_ERROR_NET_INTERRUPT)."
                    )
                    logger.error(
                        "This usually means the connection was unexpectedly disconnected while the browser was trying to load the page."
                    )
                    logger.error("Possible causes and troubleshooting suggestions:")
                    logger.error(
                        "     1. Network connection: Please check if your local network connection is stable and try to access the target URL in a normal browser."
                    )
                    logger.error(
                        "     2. AI Studio service: Confirm if the aistudio.google.com service itself is available."
                    )
                    logger.error(
                        "     3. Firewall/Proxy/VPN: Check local firewall, antivirus, proxy, or VPN settings."
                    )
                    logger.error(
                        "     4. Camoufox service: Confirm if the launch_camoufox.py script is running normally."
                    )
                    logger.error(
                        "     5. System resource issues: Ensure the system has enough memory and CPU resources."
                    )
                    logger.error("=" * 74 + "\n")
                raise RuntimeError(
                    f"Failed to navigate to new page: {new_page_nav_err}"
                ) from new_page_nav_err

        if login_url_pattern in current_url:
            if launch_mode == "headless":
                logger.error(
                    "Detected redirect to login page in headless mode, authentication may have expired. Please update the auth file."
                )
                raise RuntimeError(
                    "Auth failed in headless mode, auth file update required."
                )
            else:
                print(f"\n{'=' * 20} Action Required {'=' * 20}", flush=True)
                login_prompt = "   Detected login may be required. If the browser shows a login page, please complete the Google login in the browser window, then press Enter here to continue..."
                # NEW: If SUPPRESS_LOGIN_WAIT is set, skip waiting for user input.
                if os.environ.get("SUPPRESS_LOGIN_WAIT", "").lower() in (
                    "1",
                    "true",
                    "yes",
                ):
                    logger.info(
                        "SUPPRESS_LOGIN_WAIT flag detected, skipping wait for user input."
                    )
                else:
                    print(USER_INPUT_START_MARKER_SERVER, flush=True)
                    await loop.run_in_executor(None, input, login_prompt)
                    print(USER_INPUT_END_MARKER_SERVER, flush=True)
                logger.info("Checking login status...")
                try:
                    await found_page.wait_for_url(
                        f"**/{AI_STUDIO_URL_PATTERN}**", timeout=180000
                    )
                    current_url = found_page.url
                    if login_url_pattern in current_url:
                        logger.error(
                            "Page still seems to be on the login page after manual login attempt."
                        )
                        raise RuntimeError(
                            "Still on login page after manual login attempt."
                        )
                    logger.info(
                        "Login successful! Please do not operate the browser window and wait for further instructions."
                    )

                    # Call auth save logic after successful login
                    if os.environ.get("AUTO_SAVE_AUTH", "false").lower() == "true":
                        await wait_for_model_list_and_handle_auth_save(
                            temp_context, launch_mode, loop
                        )

                except asyncio.CancelledError:
                    raise
                except Exception as wait_login_err:
                    from browser_utils.operations import save_error_snapshot

                    await save_error_snapshot("init_login_wait_fail")
                    logger.error(
                        f"Failed to detect AI Studio URL after login prompt or error saving status: {wait_login_err}",
                        exc_info=True,
                    )
                    raise RuntimeError(
                        f"Failed to detect AI Studio URL after login prompt: {wait_login_err}"
                    ) from wait_login_err

        elif target_url_base not in current_url or "/prompts/" not in current_url:
            from browser_utils.operations import save_error_snapshot

            await save_error_snapshot("init_unexpected_page")
            logger.error(
                f"Unexpected page URL after initial navigation: {current_url}. Expected it to contain '{target_url_base}' and '/prompts/'."
            )
            raise RuntimeError(
                f"Unexpected page after initial navigation: {current_url}."
            )

        await found_page.bring_to_front()

        try:
            # Use centralized selector fallback logic to find input container
            # Supports current and old UI structures (ms-prompt-input-wrapper / ms-chunk-editor / ms-prompt-box)
            # Use find_first_visible_locator to wait for element visibility, solving timing issues in headless mode
            from config.selector_utils import find_first_visible_locator

            # Wrap in a way that respects the shutdown signal
            async def find_locator_task():
                return await find_first_visible_locator(
                    found_page,
                    INPUT_WRAPPER_SELECTORS,
                    description="Input Container",
                    timeout_per_selector=30000,
                )

            find_task = asyncio.create_task(find_locator_task())
            shutdown_task = asyncio.create_task(_wait_for_shutdown())

            done, pending = await asyncio.wait(
                [find_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
            )

            if shutdown_task in done:
                logger.info(
                    "🛑 Shutdown signal received during initialization. Aborting."
                )
                find_task.cancel()
                raise RuntimeError("Initialization aborted due to shutdown signal.")

            shutdown_task.cancel()
            input_wrapper_locator, matched_selector = await find_task

            if not input_wrapper_locator:
                raise RuntimeError(
                    "Could not find input container element. Tried selectors: "
                    + ", ".join(INPUT_WRAPPER_SELECTORS)
                )

            # Container confirmed visible by find_first_visible_locator, check input box directly
            await expect_async(found_page.locator(INPUT_SELECTOR)).to_be_visible(
                timeout=10000
            )
            logger.debug(
                f"[Selector] Input area located and visible ({matched_selector})"
            )

            model_name_locator = found_page.locator(MODEL_NAME_SELECTOR)
            try:
                model_name_on_page = await model_name_locator.first.inner_text(
                    timeout=5000
                )
            except PlaywrightAsyncError as e:
                logger.error(f"Error getting model name (model_name_locator): {e}")
                raise

            result_page_instance = found_page
            result_page_ready = True

            logger.info(
                f"[Page] Logic initialization successful | Current Model: {model_name_on_page}"
            )
            return result_page_instance, result_page_ready
        except asyncio.CancelledError:
            raise
        except Exception as input_visible_err:
            from browser_utils.operations import save_error_snapshot

            await save_error_snapshot("init_fail_input_timeout")
            logger.error(
                f"Page initialization failed: core input area did not become visible within expected time. Last URL was {found_page.url}",
                exc_info=True,
            )
            raise RuntimeError(
                f"Page initialization failed: core input area did not become visible within expected time. Last URL was {found_page.url}"
            ) from input_visible_err
    except asyncio.CancelledError:
        logger.warning("Page initialization cancelled.")
        if temp_context:
            try:
                await temp_context.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        raise
    except Exception as e_init_page:
        logger.critical(
            f"Serious unexpected error during page logic initialization: {e_init_page}",
            exc_info=True,
        )
        if temp_context:
            try:
                logger.info(
                    "   Attempting to close temporary browser context due to initialization error."
                )
                # [ID-04] Optimize Browser Lifecycle Management: Add timeout to context close
                await asyncio.wait_for(temp_context.close(), timeout=2.0)
                logger.info("   Temporary browser context closed.")
            except asyncio.TimeoutError:
                logger.warning(
                    "   🚨 [ID-04] Browser context close timeout (2s), skipping forced close to speed up shutdown."
                )
            except asyncio.CancelledError:
                raise
            except Exception as close_err:
                logger.warning(f"Error closing temporary browser context: {close_err}")
        from browser_utils.operations import save_error_snapshot

        await save_error_snapshot("init_unexpected_error")
        raise RuntimeError(
            f"Unexpected page initialization error: {e_init_page}"
        ) from e_init_page


async def close_page_logic() -> Tuple[None, bool]:  # pragma: no cover
    """Close page logic"""
    # Need to access global variables
    from api_utils.server_state import state

    logger.info("--- Running page logic shutdown --- ")
    if state.page_instance and not state.page_instance.is_closed():
        try:
            # [ID-04] Optimize Browser Lifecycle Management: 2-second timeout for graceful close
            await asyncio.wait_for(state.page_instance.close(), timeout=2.0)
            logger.info("   Page closed")
        except asyncio.TimeoutError:
            logger.warning(
                "   🚨 [ID-04] Browser page close timeout (2s), skipping forced close to speed up shutdown."
            )
        except PlaywrightAsyncError as pw_err:
            logger.warning(f"Playwright error closing page: {pw_err}")
        except asyncio.CancelledError:
            raise
        except Exception as other_err:
            logger.error(
                f"   Unexpected error closing page: {other_err} (Type: {type(other_err).__name__})",
                exc_info=True,
            )
    state.page_instance = None
    state.is_page_ready = False
    logger.info("Page logic state reset.")
    return None, False


async def signal_camoufox_shutdown() -> None:  # pragma: no cover
    """Send shutdown signal to Camoufox server"""
    logger.info(
        "Attempting to send shutdown signal to Camoufox server (this feature may have been handled by parent process)..."
    )
    ws_endpoint = os.environ.get("CAMOUFOX_WS_ENDPOINT")
    if not ws_endpoint:
        logger.warning(
            "Could not send shutdown signal: CAMOUFOX_WS_ENDPOINT environment variable not found."
        )
        return

    # Need to access global browser instance
    from api_utils.server_state import state

    if not state.browser_instance or not state.browser_instance.is_connected():
        logger.warning(
            "Browser instance disconnected or not initialized, skipping shutdown signal send."
        )
        return
    try:
        await asyncio.sleep(0.2)
        logger.info("(Simulated) Shutdown signal handled.")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(
            f"Captured exception while sending shutdown signal: {e}", exc_info=True
        )


async def _is_temporary_chat_active(page: AsyncPage) -> bool:
    """Best-effort check for whether Temporary chat is currently enabled.

    Supports both the legacy toggle-class signal and the newer UI variants:
    - menu item checkmark (`data-test-incognito-checkmark`)
    - header indicator (`ms-incognito-mode-indicator`)
    """

    try:
        # Newer UI: header indicator appears only when Temporary chat is active.
        indicator_locator = page.locator(
            "ms-incognito-mode-indicator [data-test-id='main-text'], "
            "ms-incognito-mode-indicator .main-text"
        )
        indicator_count = await indicator_locator.count()
        for i in range(indicator_count):
            try:
                indicator_item = indicator_locator.nth(i)
                if not await indicator_item.is_visible(timeout=500):
                    continue
                indicator_text = (await indicator_item.inner_text()).strip().lower()
                if indicator_text == "temporary chat":
                    return True
            except Exception:
                continue

        # New menu UI: active state is represented by a checkmark inside the menu item.
        try:
            checkmark_locator = page.locator("[data-test-incognito-checkmark]")
            if await checkmark_locator.count() > 0:
                return True
        except Exception:
            pass

        # Menu button variants (legacy and gray-release UI).
        toggle_locator = page.locator(
            "button[data-test-incognito-toggle], "
            'button[aria-label="Temporary chat toggle"], '
            'button[aria-label="Toggle temporary chat"]'
        )
        if await toggle_locator.count() > 0:
            # Legacy/alternative signals.
            for attr_name in ("aria-pressed", "aria-checked"):
                try:
                    attr_value = await toggle_locator.get_attribute(attr_name)
                    if attr_value and attr_value.lower() == "true":
                        return True
                except Exception:
                    pass

            try:
                button_classes = await toggle_locator.get_attribute("class") or ""
                if "ms-button-active" in button_classes:
                    return True
            except Exception:
                pass

        return False
    except Exception:
        return False


async def enable_temporary_chat_mode(page: AsyncPage) -> bool:  # pragma: no cover
    """
    Check and enable "Temporary chat" mode in the AI Studio interface.
    Supports both direct UI visibility and collapsed menu visibility.
    """
    incognito_selector = (
        "button[data-test-incognito-toggle], "
        'button[aria-label="Temporary chat toggle"], '
        'button[aria-label="Toggle temporary chat"]'
    )
    menu_trigger_selector = 'button[aria-label="View more actions"]'

    incognito_locator = page.locator(incognito_selector)
    menu_trigger = page.locator(menu_trigger_selector)

    async def _close_menu_if_needed() -> None:
        """Best-effort menu cleanup that tolerates UI variants without a menu trigger."""
        try:
            if await menu_trigger.count() == 0:
                return
            if await menu_trigger.is_visible():
                if await menu_trigger.get_attribute("aria-expanded") == "true":
                    logger.debug("[UI] Closing menu to restore UI state")
                    await page.keyboard.press("Escape")
        except Exception:
            pass

    try:
        if await _is_temporary_chat_active(page):
            logger.debug("[UI] Temporary chat mode already active")
            await _close_menu_if_needed()
            return True

        # Fast path
        logger.debug("[UI] Searching for temporary chat button (Fast path)")
        try:
            await incognito_locator.wait_for(state="visible", timeout=3000)
        except Exception:
            # Fallback
            logger.debug("[UI] Button not visible, attempting to open menu")
            if await menu_trigger.is_visible():
                await menu_trigger.click()
                # Wait for the menu item to appear
                await incognito_locator.wait_for(state="visible", timeout=5000)
            else:
                logger.warning("[UI] Neither button nor menu trigger found")
                return False

        if await _is_temporary_chat_active(page):
            logger.debug("[UI] Temporary chat mode already active")
        else:
            logger.debug("[UI] Enabling temporary chat mode")
            await incognito_locator.click(timeout=5000, force=True)
            await asyncio.sleep(1)

        enabled = await _is_temporary_chat_active(page)

        # Recovery: Close menu if still expanded
        await _close_menu_if_needed()
        return enabled

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[UI] Error in temporary chat mode: {e}")
        # Final safety attempt to clear any stuck UI
        await _close_menu_if_needed()
        return await _is_temporary_chat_active(page)
