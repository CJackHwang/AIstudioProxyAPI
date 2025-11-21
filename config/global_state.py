import asyncio
import time
import logging

logger = logging.getLogger(__name__)

class GlobalState:
    """
    Singleton class to hold global application state, specifically for Quota Exceeded logic.
    """
    _instance = None
    IS_QUOTA_EXCEEDED = False
    QUOTA_EXCEEDED_TIMESTAMP = 0.0
    
    # Global Event for holding requests during auth rotation
    # Initially set to True (allowed) by init_rotation_lock()
    AUTH_ROTATION_LOCK = asyncio.Event()
    
    # Global Event to signal Quota Exceeded immediately
    QUOTA_EXCEEDED_EVENT = asyncio.Event()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalState, cls).__new__(cls)
        return cls._instance

    @classmethod
    def init_rotation_lock(cls):
        """Initialize the rotation lock to allow requests."""
        cls.AUTH_ROTATION_LOCK.set()
        logger.info("🔐 Global Auth Rotation Lock initialized (OPEN).")

    @classmethod
    def set_quota_exceeded(cls):
        """
        Sets the global quota exceeded flag and logs a critical warning.
        """
        if not cls.IS_QUOTA_EXCEEDED:
            cls.IS_QUOTA_EXCEEDED = True
            cls.QUOTA_EXCEEDED_TIMESTAMP = time.time()
            cls.QUOTA_EXCEEDED_EVENT.set()
            logger.critical("⛔ GLOBAL ALERT: Quota Exceeded! (Event Signal Sent)")

    @classmethod
    def reset_quota_status(cls):
        """
        Resets the global quota exceeded flag.
        """
        cls.IS_QUOTA_EXCEEDED = False
        cls.QUOTA_EXCEEDED_TIMESTAMP = 0.0
        cls.QUOTA_EXCEEDED_EVENT.clear()
        logger.info("✅ GLOBAL ALERT: Quota status manually reset.")