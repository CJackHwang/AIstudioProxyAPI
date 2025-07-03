# --- browser_utils/__init__.py ---
# 浏览器操作工具模块
from .initialization import _initialize_page_logic, _close_page_logic, signal_camoufox_shutdown
from .operations import (
    _handle_model_list_response,
    detect_and_extract_page_error,
    save_error_snapshot,
    get_response_via_edit_button,
    get_response_via_copy_button,
    _wait_for_response_completion,
    _get_final_response_content,
    get_raw_text_content
)
from .model_management import (
    switch_ai_studio_model,
    load_excluded_models,
    _handle_initial_model_state_and_storage,
    _set_model_from_page_display,
    _verify_ui_state_settings,
    _force_ui_state_settings,
    _force_ui_state_with_retry,
    _verify_and_apply_ui_state
)
from .script_manager import ScriptManager, script_manager
from .resource_manager import BrowserResourceManager, get_resource_manager, cleanup_global_resources

__all__ = [
    # 初始化相关
    '_initialize_page_logic',
    '_close_page_logic', 
    'signal_camoufox_shutdown',
    
    # 页面操作相关
    '_handle_model_list_response',
    'detect_and_extract_page_error',
    'save_error_snapshot',
    'get_response_via_edit_button',
    'get_response_via_copy_button',
    '_wait_for_response_completion',
    '_get_final_response_content',
    'get_raw_text_content',
    
    # 模型管理相关
    'switch_ai_studio_model',
    'load_excluded_models',
    '_handle_initial_model_state_and_storage',
    '_set_model_from_page_display',
    '_verify_ui_state_settings',
    '_force_ui_state_settings',
    '_force_ui_state_with_retry',
    '_verify_and_apply_ui_state',

    # 脚本管理相关
    'ScriptManager',
    'script_manager',

    # 资源管理相关
    'BrowserResourceManager',
    'get_resource_manager',
    'cleanup_global_resources'
]