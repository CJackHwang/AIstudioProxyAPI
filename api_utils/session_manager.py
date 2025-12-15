import asyncio
import logging
import os
from typing import List, Optional, Tuple
from playwright.async_api import Browser, BrowserContext, Page

# Import directly to avoid circular imports if possible, or use lazy imports
from browser_utils.initialization.core import initialize_page_logic
from browser_utils.model_management import _handle_initial_model_state_and_storage
from browser_utils import enable_temporary_chat_mode

logger = logging.getLogger("AIStudioProxyServer")

class Session:
    def __init__(self, id: str, profile_path: str):
        self.id = id
        self.profile_path = profile_path
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.lock = asyncio.Lock()
        self.is_ready = False

    async def initialize(self, browser: Browser) -> bool:
        try:
            logger.info(f"Initializing session {self.id} with profile {self.profile_path}")
            # initialize_page_logic is expected to return (context, page) after refactoring
            self.context, self.page = await initialize_page_logic(browser, self.profile_path)
            
            if self.page:
                self.is_ready = True
                # Perform post-initialization setup
                # These functions might need to be updated if they rely on global state, 
                # but they seem to take page as argument.
                await _handle_initial_model_state_and_storage(self.page)
                await enable_temporary_chat_mode(self.page)
                return True
            else:
                logger.error(f"Session {self.id} initialization failed: Page is None")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize session {self.id}: {e}", exc_info=True)
            return False

    async def close(self):
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                logger.warning(f"Error closing session {self.id}: {e}")
        self.is_ready = False
        self.page = None
        self.context = None

class SessionManager:
    def __init__(self):
        self.sessions: List[Session] = []
        self._rr_index = 0
        self.lock = asyncio.Lock()

    async def initialize_all(self, browser: Browser, auth_dir: str):
        logger.info(f"Initializing sessions from {auth_dir}")
        if not os.path.exists(auth_dir):
            logger.error(f"Auth directory {auth_dir} does not exist.")
            return

        files = [f for f in os.listdir(auth_dir) if f.endswith('.json')]
        files.sort() # Ensure deterministic order

        if not files:
            logger.warning(f"No auth profiles found in {auth_dir}")
            return

        for f in files:
            profile_path = os.path.join(auth_dir, f)
            session_id = f.replace('.json', '')
            session = Session(session_id, profile_path)
            if await session.initialize(browser):
                self.sessions.append(session)
                logger.info(f"Session {session_id} initialized successfully.")
            else:
                logger.warning(f"Session {session_id} failed to initialize.")

        logger.info(f"Initialized {len(self.sessions)} sessions.")

    def acquire_session(self) -> Optional[Session]:
        if not self.sessions:
            return None
        
        # Simple Round-Robin
        session = self.sessions[self._rr_index]
        self._rr_index = (self._rr_index + 1) % len(self.sessions)
        return session