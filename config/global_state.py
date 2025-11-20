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

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalState, cls).__new__(cls)
        return cls._instance

    @classmethod
    def set_quota_exceeded(cls):
        """
        Sets the global quota exceeded flag and logs a critical warning.
        Triggers a delayed shutdown to allow logs to flush.
        """
        if not cls.IS_QUOTA_EXCEEDED:
            cls.IS_QUOTA_EXCEEDED = True
            cls.QUOTA_EXCEEDED_TIMESTAMP = time.time()
            logger.critical("⛔ GLOBAL ALERT: Quota Exceeded! System entering lock-down mode.")
            
            # Trigger delayed shutdown
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(cls._delayed_shutdown())
            except RuntimeError:
                # If no loop is running (e.g. in a synchronous context), just warn or exit immediately
                logger.warning("Could not schedule delayed shutdown (no running loop). System may require manual restart.")

    @classmethod
    async def _delayed_shutdown(cls):
        logger.warning("⏳ System will shut down in 5 seconds due to Quota Exceeded...")
        import asyncio
        import sys
        import os
        import signal
        
        await asyncio.sleep(5)
        
        logger.critical("🛑 Initiating System Shutdown now.")
        try:
            # Use os.kill to send SIGINT, which simulates Ctrl+C and allows for cleanup handlers if any
            os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            # Fallback to sys.exit if os.kill fails (e.g. on Windows sometimes)
            sys.exit(1)

    @classmethod
    def reset_quota_status(cls):
        """
        Resets the global quota exceeded flag.
        """
        cls.IS_QUOTA_EXCEEDED = False
        cls.QUOTA_EXCEEDED_TIMESTAMP = 0.0
        logger.info("✅ GLOBAL ALERT: Quota status manually reset.")