"""
CSS选择器配置模块
包含所有用于页面元素定位的CSS选择器
"""

# --- 输入相关选择器 ---
# 主输入 textarea 兼容当前和旧 UI 结构
# 当前结构: ms-prompt-input-wrapper > ... > ms-autosize-textarea > textarea.textarea
PROMPT_TEXTAREA_SELECTOR = (
    # 当前 UI 结构
    "textarea.textarea, "  # 最直接的选择器
    "ms-autosize-textarea textarea, "
    "ms-chunk-input textarea, "
    "ms-prompt-input-wrapper ms-autosize-textarea textarea, "
    'ms-prompt-input-wrapper textarea[aria-label*="prompt" i], '
    "ms-prompt-input-wrapper textarea, "
    # 过渡期 UI (ms-prompt-box) - 已弃用但保留作为回退
    "ms-prompt-box ms-autosize-textarea textarea, "
    'ms-prompt-box textarea[aria-label="Enter a prompt"], '
    "ms-prompt-box textarea"
)
INPUT_SELECTOR = PROMPT_TEXTAREA_SELECTOR
INPUT_SELECTOR2 = PROMPT_TEXTAREA_SELECTOR

# --- 按钮选择器 ---
# 发送按钮：优先匹配 prompt 区域内 aria-label="Run" 的提交按钮
SUBMIT_BUTTON_SELECTOR = (
    # 当前 UI 结构
    'ms-prompt-input-wrapper ms-run-button button[aria-label="Run"], '
    'ms-prompt-input-wrapper button[aria-label="Run"][type="submit"], '
    'button[aria-label="Run"].run-button, '
    'ms-run-button button[type="submit"].run-button, '
    # 过渡期 UI (ms-prompt-box) - 已弃用但保留作为回退
    'ms-prompt-box ms-run-button button[aria-label="Run"], '
    'ms-prompt-box button[aria-label="Run"][type="submit"]'
)
CLEAR_CHAT_BUTTON_SELECTOR = 'button[data-test-clear="outside"][aria-label="New chat"], button[aria-label="New chat"]'
CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR = (
    'button.ms-button-primary:has-text("Discard and continue")'
)
UPLOAD_BUTTON_SELECTOR = (
    'button[data-test-id="add-media-button"], '
    'button[aria-label^="Insert assets"], '
    'button[aria-label^="Insert images"]'
)

# --- 响应相关选择器 ---
RESPONSE_CONTAINER_SELECTOR = "ms-chat-turn .chat-turn-container.model"
RESPONSE_TEXT_SELECTOR = "ms-cmark-node.cmark-node"

# --- 加载和状态选择器 ---
LOADING_SPINNER_SELECTOR = 'button[aria-label="Run"].run-button svg .stoppable-spinner'
OVERLAY_SELECTOR = ".mat-mdc-dialog-inner-container"

# --- 错误提示选择器 ---
ERROR_TOAST_SELECTOR = "div.toast.warning, div.toast.error"

# --- 编辑相关选择器 ---
EDIT_MESSAGE_BUTTON_SELECTOR = (
    "ms-chat-turn:last-child .actions-container button.toggle-edit-button"
)
MESSAGE_TEXTAREA_SELECTOR = (
    "ms-chat-turn:last-child textarea, ms-chat-turn:last-child ms-text-chunk textarea"
)
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
MAT_CHIP_REMOVE_BUTTON_SELECTOR = 'mat-chip button.remove-button[aria-label*="Remove"]'
TOP_P_INPUT_SELECTOR = 'ms-slider input[type="number"][max="1"]'
TEMPERATURE_INPUT_SELECTOR = 'ms-slider input[type="number"][max="2"]'
USE_URL_CONTEXT_SELECTOR = 'button[aria-label="Browse the url context"]'

# --- 思考模式相关选择器 ---
# 主思考开关：控制是否启用思考模式（总开关）
# Flash模型使用 aria-label="Toggle thinking mode"
# 回退: 旧版 data-test-toggle 属性
ENABLE_THINKING_MODE_TOGGLE_SELECTOR = (
    'button[role="switch"][aria-label="Toggle thinking mode"], '
    'mat-slide-toggle[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch'
)
# 手动预算开关：控制是否手动限制思考预算
# Flash模型使用 aria-label="Toggle thinking budget between auto and manual"
# 回退: 旧版 data-test-toggle 属性
SET_THINKING_BUDGET_TOGGLE_SELECTOR = (
    'button[role="switch"][aria-label="Toggle thinking budget between auto and manual"], '
    'mat-slide-toggle[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch'
)
# 思考预算输入框
# 思考预算滑块具有独特的 min="512" 属性（温度是 max="2"，TopP 是 max="1"）
# 优先使用最精确的选择器，保留多层回退以应对 UI 变化
THINKING_BUDGET_INPUT_SELECTOR = (
    # 最精确: 使用 data-test-id 容器 + spinbutton
    '[data-test-id="user-setting-budget-animation-wrapper"] input[type="number"], '
    # 回退1: 使用独特的 min="512" 属性定位（仅思考预算滑块有此属性）
    'input.slider-number-input[min="512"], '
    'ms-slider input[type="number"][min="512"], '
    # 回退2: 旧版 data-test-slider 属性
    '[data-test-slider] input[type="number"]'
)

# 思考等级下拉
THINKING_LEVEL_SELECT_SELECTOR = '[role="combobox"][aria-label="Thinking Level"], mat-select[aria-label="Thinking Level"], [role="combobox"][aria-label="Thinking level"], mat-select[aria-label="Thinking level"]'
THINKING_LEVEL_OPTION_LOW_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Low"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Low")'
THINKING_LEVEL_OPTION_HIGH_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("High"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("High")'
THINKING_LEVEL_OPTION_MEDIUM_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Medium"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Medium")'
THINKING_LEVEL_OPTION_MINIMAL_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Minimal"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Minimal")'


# --- Google Search Grounding ---
GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR = (
    'div[data-test-id="searchAsAToolTooltip"] mat-slide-toggle button'
)

# --- 页面元素选择器 ---
# 模型名称显示元素
MODEL_NAME_SELECTOR = '[data-test-id="model-name"]'
# CDK Overlay 容器（用于菜单、对话框等）
CDK_OVERLAY_CONTAINER_SELECTOR = "div.cdk-overlay-container"
# 聊天轮次容器
CHAT_TURN_SELECTOR = "ms-chat-turn"

# --- 思考模式回退选择器 ---
# 这些选择器用于 thinking.py 中的回退逻辑
# 主思考开关父容器（新版UI）
THINKING_MODE_TOGGLE_PARENT_SELECTOR = (
    'mat-slide-toggle:has(button[aria-label="Toggle thinking mode"])'
)
# 主思考开关旧版根元素
THINKING_MODE_TOGGLE_OLD_ROOT_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="enable-thinking"]'
)
# 思考预算开关父容器（新版UI）
THINKING_BUDGET_TOGGLE_PARENT_SELECTOR = 'mat-slide-toggle:has(button[aria-label="Toggle thinking budget between auto and manual"])'
# 思考预算开关旧版根元素
THINKING_BUDGET_TOGGLE_OLD_ROOT_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="manual-budget"]'
)
