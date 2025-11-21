import asyncio
import os
import logging
import glob
import time
import random
from typing import Optional

from config.global_state import GlobalState
import server  # To access global browser/page instances

logger = logging.getLogger("AuthRotation")

# Track recently used profiles to avoid rapid cycling/reuse
# Maps filename -> timestamp of last use
_USED_PROFILES_HISTORY = {}
_HISTORY_RETENTION_SECONDS = 3600 * 2 # 2 hours retention for history

# Profiles currently in cooldown (e.g. due to quota limit)
_COOLDOWN_PROFILES = {}
_COOLDOWN_SECONDS = 900 # 15 minutes cooldown

# [FINAL-02] Depletion Guard: Track rotation attempts
_ROTATION_TIMESTAMPS = []
_ROTATION_LIMIT_WINDOW = 60 # seconds
_ROTATION_LIMIT_COUNT = 3   # max attempts per window

def _get_next_profile() -> Optional[str]:
    """
    Scans auth_profiles/saved and auth_profiles/active to find the next best profile.
    Prioritizes profiles that haven't been used recently.
    Excludes profiles in cooldown.
    """
    base_dirs = ["auth_profiles/saved", "auth_profiles/active"]
    all_profiles = []
    
    for d in base_dirs:
        if os.path.exists(d):
            # Find all .json files
            files = glob.glob(os.path.join(d, "*.json"))
            all_profiles.extend([os.path.abspath(f) for f in files])
            
    if not all_profiles:
        return None
    
    current_time = time.time()
    
    # Clean up cooldowns
    cooldown_keys_to_remove = [k for k, v in _COOLDOWN_PROFILES.items() if current_time - v > _COOLDOWN_SECONDS]
    for k in cooldown_keys_to_remove:
        del _COOLDOWN_PROFILES[k]
        
    # Filter out profiles that don't exist or are in cooldown
    valid_profiles = [p for p in all_profiles if os.path.exists(p) and p not in _COOLDOWN_PROFILES]
    
    if not valid_profiles:
        logger.warning("No valid profiles available (all missing or in cooldown). Falling back to ignore cooldowns.")
        # Emergency fallback: ignore cooldowns if everything is blocked
        valid_profiles = [p for p in all_profiles if os.path.exists(p)]
        
    if not valid_profiles:
        return None
        
    # Clean up history
    keys_to_remove = [k for k, v in _USED_PROFILES_HISTORY.items() if current_time - v > _HISTORY_RETENTION_SECONDS]
    for k in keys_to_remove:
        del _USED_PROFILES_HISTORY[k]
        
    # Sort profiles by last used time (Least Recently Used)
    # If never used, timestamp is 0
    def get_last_used(path):
        return _USED_PROFILES_HISTORY.get(path, 0)
        
    # Sort: Primary key = last_used (ascending), Secondary key = random (to shuffle never-used ones)
    random.shuffle(valid_profiles)
    valid_profiles.sort(key=get_last_used)
    
    # Pick the candidate
    candidate = valid_profiles[0]
    
    return candidate

async def perform_auth_rotation() -> bool:
    """
    Performs the authentication profile rotation with FULL Browser Restart.
    
    1. Acquires Hard Lock (stops requests).
    2. Stops the Browser (Clean Shutdown).
    3. Swaps the Profile (Active -> Saved, Saved -> Active).
    4. Starts the Browser (New Session).
    5. Releases Lock.
    """
    # Avoid re-entry if already rotating
    if not GlobalState.AUTH_ROTATION_LOCK.is_set():
        logger.info("⚠️ Rotation already in progress (Lock is set). Skipping duplicate trigger.")
        return True

    # [FINAL-02] Depletion Guard Check
    global _ROTATION_TIMESTAMPS
    current_time = time.time()
    # Filter timestamps within the window
    _ROTATION_TIMESTAMPS = [t for t in _ROTATION_TIMESTAMPS if current_time - t < _ROTATION_LIMIT_WINDOW]
    
    if len(_ROTATION_TIMESTAMPS) >= _ROTATION_LIMIT_COUNT:
        logger.critical("🚨 CRITICAL: TOO MANY ROTATIONS! All accounts may be exhausted. Stopping Browser & Locking API.")
        
        # Stop everything
        if server.page_instance:
            try:
                await server.page_instance.close()
            except Exception: pass
        if server.browser_instance:
            try:
                await server.browser_instance.close()
            except Exception: pass
            
        server.page_instance = None
        server.browser_instance = None
        server.is_browser_connected = False
        
        # PERMANENT LOCK (Do not release GlobalState.AUTH_ROTATION_LOCK)
        # We leave the lock cleared so no new requests can proceed.
        return False

    # Record this attempt
    _ROTATION_TIMESTAMPS.append(current_time)

    logger.info("🔄 Starting Auth Profile Rotation (Full Browser Restart)...")
    
    # 1. Block new requests
    GlobalState.AUTH_ROTATION_LOCK.clear()
    logger.info("🔒 Request processing locked.")
    
    try:
        # 2. Stop Browser
        logger.info("🛑 Stopping Browser...")
        if server.page_instance:
            try:
                await server.page_instance.close()
            except Exception: pass
            server.page_instance = None
            
        if server.browser_instance:
            try:
                await server.browser_instance.close()
                logger.info("✅ Browser instance closed.")
            except Exception as e:
                logger.warning(f"Error closing browser instance: {e}")
            server.browser_instance = None
            server.is_browser_connected = False
            
        if server.playwright_manager:
            try:
                await server.playwright_manager.stop()
                logger.info("✅ Playwright manager stopped.")
            except Exception as e:
                logger.warning(f"Error stopping Playwright: {e}")
            server.playwright_manager = None
            server.is_playwright_ready = False

        # 3. Select next profile
        next_profile_path = _get_next_profile()
        if not next_profile_path:
            logger.critical("❌ Rotation Failed: No available auth profiles found!")
            return False
            
        logger.info(f"👉 Selected next profile: {os.path.basename(next_profile_path)}")
        _USED_PROFILES_HISTORY[next_profile_path] = time.time()
        
        # Update global state for the new profile path so initialization picks it up
        server.current_auth_profile_path = next_profile_path
        # Also set the env var because _initialize_page_logic checks it in some modes
        os.environ['ACTIVE_AUTH_JSON_PATH'] = next_profile_path

        # 4. Start Browser
        logger.info("🚀 Restarting Browser...")
        from api_utils.app import _initialize_browser_and_page
        
        # We need to re-initialize playwright and browser
        # _initialize_browser_and_page handles: playwright start, browser connect, page init
        # Note: It relies on 'server' globals which we just cleared.
        
        try:
            await _initialize_browser_and_page()
            if server.is_page_ready:
                logger.info("✅ Browser Restarted & Page Ready.")
                
                # Reset Quota Status
                GlobalState.reset_quota_status()
                return True
            else:
                logger.error("❌ Browser started but page is not ready.")
                return False
        except Exception as start_err:
             logger.error(f"❌ Failed to restart browser: {start_err}")
             return False

    except Exception as e:
        logger.error(f"❌ Unexpected error during auth rotation: {e}", exc_info=True)
        return False
        
    finally:
        # 5. Release lock
        GlobalState.AUTH_ROTATION_LOCK.set()
        logger.info("🔓 Request processing unlocked.")