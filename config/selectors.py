"""
CSS选择器配置模块
包含所有用于页面元素定位的CSS选择器
"""

# --- 输入相关选择器 ---
PROMPT_TEXTAREA_SELECTOR = "ms-prompt-input-wrapper ms-autosize-textarea textarea"
INPUT_SELECTOR = PROMPT_TEXTAREA_SELECTOR
INPUT_SELECTOR2 = PROMPT_TEXTAREA_SELECTOR

# --- 按钮选择器 ---
# 发送按钮：优先匹配 aria-label="Run" 的按钮；如页面结构变更，可退化到容器内的提交按钮。
SUBMIT_BUTTON_SELECTOR = 'button[aria-label="Run"].run-button, ms-run-button button[type="submit"].run-button'
CLEAR_CHAT_BUTTON_SELECTOR = 'button[data-test-clear="outside"][aria-label="New chat"], button[aria-label="New chat"]'
CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR = (
    'button.ms-button-primary:has-text("Discard and continue")'
)
UPLOAD_BUTTON_SELECTOR = 'button[aria-label^="Insert assets"]'

# --- 响应相关选择器 ---
RESPONSE_CONTAINER_SELECTOR = "ms-chat-turn .chat-turn-container.model"
RESPONSE_TEXT_SELECTOR = "ms-cmark-node.cmark-node"

# --- 加载和状态选择器 ---
LOADING_SPINNER_SELECTOR = 'button[aria-label="Run"].run-button svg .stoppable-spinner'
OVERLAY_SELECTOR = ".mat-mdc-dialog-inner-container"

# --- 错误提示选择器 ---
ERROR_TOAST_SELECTOR = "div.toast.warning, div.toast.error"
QUOTA_EXCEEDED_SELECTOR = "ms-callout.error-callout .message"

# --- 编辑相关选择器 ---
EDIT_MESSAGE_BUTTON_SELECTOR = (
    "ms-chat-turn:last-child .actions-container button.toggle-edit-button"
)
MESSAGE_TEXTAREA_SELECTOR = "ms-chat-turn:last-child ms-text-chunk ms-autosize-textarea"
FINISH_EDIT_BUTTON_SELECTOR = 'ms-chat-turn:last-child .actions-container button.toggle-edit-button[aria-label="Stop editing"]'

# --- 菜单和复制相关选择器 ---
MORE_OPTIONS_BUTTON_SELECTOR = (
    "div.actions-container div ms-chat-turn-options div > button"
)
COPY_MARKDOWN_BUTTON_SELECTOR = "button.mat-mdc-menu-item:nth-child(4)"
COPY_MARKDOWN_BUTTON_SELECTOR_ALT = 'div[role="menu"] button:has-text("Copy Markdown")'

# --- 设置相关选择器 ---
MAX_OUTPUT_TOKENS_SELECTOR = 'input[aria-label="Maximum output tokens"]'
STOP_SEQUENCE_INPUT_SELECTOR = 'input[aria-label="Add stop token"]'
MAT_CHIP_REMOVE_BUTTON_SELECTOR = (
    'mat-chip-set mat-chip-row button[aria-label*="Remove"]'
)
TOP_P_INPUT_SELECTOR = 'ms-slider input[type="number"][max="1"]'
TEMPERATURE_INPUT_SELECTOR = 'ms-slider input[type="number"][max="2"]'
USE_URL_CONTEXT_SELECTOR = 'button[aria-label="Browse the url context"]'

# --- 思考模式相关选择器 ---
# 主思考开关：控制是否启用思考模式（总开关）
ENABLE_THINKING_MODE_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch'
)

# 手动预算开关：控制是否手动限制思考预算
SET_THINKING_BUDGET_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch'
)
# 思考预算输入框
THINKING_BUDGET_INPUT_SELECTOR = '[data-test-slider] input[type="number"]'

# 思考等级下拉 (Gemini 3.0+ UI Detection) - 必须包含此项
THINKING_LEVEL_DROPDOWN_SELECTOR = 'mat-select[aria-label="Thinking Level"]'

# 思考等级下拉 (通用选择器)
THINKING_LEVEL_SELECT_SELECTOR = '[role="combobox"][aria-label="Thinking Level"], mat-select[aria-label="Thinking Level"], [role="combobox"][aria-label="Thinking level"], mat-select[aria-label="Thinking level"]'
THINKING_LEVEL_OPTION_LOW_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Low"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Low")'
THINKING_LEVEL_OPTION_HIGH_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("High"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("High")'

# --- Google Search Grounding ---
GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR = (
    'div[data-test-id="searchAsAToolTooltip"] mat-slide-toggle button'
)