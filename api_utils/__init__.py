"""
API工具模块
提供FastAPI应用初始化、路由处理和工具函数
"""

# 应用初始化
from .app import (
    create_app
)

# 路由处理器
from .routes import (
    read_index,
    get_css,
    get_js,
    get_api_info,
    health_check,
    list_models,
    chat_completions,
    cancel_request,
    get_queue_status,
    websocket_log_endpoint
)

# 工具函数
from .utils import (
    generate_sse_chunk,
    generate_sse_stop_chunk,
    generate_sse_error_chunk,
    use_stream_response,
    clear_stream_queue,
    use_helper_get_response,
    validate_chat_request,
    prepare_combined_prompt,
    estimate_tokens,
    calculate_usage_stats
)

# 请求处理器
from .request_processor import (
    _process_request_refactored
)

# 队列工作器
from .queue_worker import (
    queue_worker
)

# 任务管理器
from .task_manager import (
    AsyncTaskManager,
    get_task_manager,
    cleanup_global_tasks,
    create_managed_task,
    cancel_managed_task,
    get_managed_task,
    get_task_info
)

# 优雅关闭管理器
from .graceful_shutdown import (
    GracefulShutdownManager,
    get_shutdown_manager,
    add_shutdown_handler,
    graceful_shutdown,
    install_signal_handlers,
    setup_default_shutdown_handlers
)

# 全局状态管理器
from .state_manager import (
    GlobalStateManager,
    get_state_manager,
    reset_global_state
)

# 模型管理器
from .model_manager import (
    ModelManager,
    get_model_manager,
    switch_model_safe,
    get_current_model_safe,
    validate_model_request_safe,
    is_model_switch_needed
)

__all__ = [
    # 应用初始化
    'create_app',
    # 路由处理器
    'read_index',
    'get_css',
    'get_js',
    'get_api_info',
    'health_check',
    'list_models',
    'chat_completions',
    'cancel_request',
    'get_queue_status',
    'websocket_log_endpoint',
    # 工具函数
    'generate_sse_chunk',
    'generate_sse_stop_chunk',
    'generate_sse_error_chunk',
    'use_stream_response',
    'clear_stream_queue',
    'use_helper_get_response',
    'validate_chat_request',
    'prepare_combined_prompt',
    'estimate_tokens',
    'calculate_usage_stats',
    # 请求处理器
    '_process_request_refactored',
    # 队列工作器
    'queue_worker',
    # 任务管理器
    'AsyncTaskManager',
    'get_task_manager',
    'cleanup_global_tasks',
    'create_managed_task',
    'cancel_managed_task',
    'get_managed_task',
    'get_task_info',
    # 优雅关闭管理器
    'GracefulShutdownManager',
    'get_shutdown_manager',
    'add_shutdown_handler',
    'graceful_shutdown',
    'install_signal_handlers',
    'setup_default_shutdown_handlers',
    # 全局状态管理器
    'GlobalStateManager',
    'get_state_manager',
    'reset_global_state',
    # 模型管理器
    'ModelManager',
    'get_model_manager',
    'switch_model_safe',
    'get_current_model_safe',
    'validate_model_request_safe',
    'is_model_switch_needed'
]