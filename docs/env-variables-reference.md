# 环境变量完整参考

本文档提供项目中所有环境变量的完整参考，包括用途、类型、默认值和示例。

## 📋 目录

- [端口配置](#端口配置)
- [代理配置](#代理配置)
- [日志配置](#日志配置)
- [认证配置](#认证配置)
- [浏览器配置](#浏览器配置)
- [API 默认参数](#api-默认参数)
- [超时配置](#超时配置)
- [GUI 启动器配置](#gui-启动器配置)
- [脚本注入配置](#脚本注入配置)
- [其他配置](#其他配置)
- [流状态配置](#流状态配置)

---

## 端口配置

### PORT

- **用途**: FastAPI 服务监听端口
- **类型**: 整数
- **默认值**: `2048`
- **示例**: `PORT=8000`
- **说明**: 主 API 服务的 HTTP 端口，所有 `/v1/*` 端点通过此端口访问

### DEFAULT_FASTAPI_PORT

- **用途**: GUI 启动器的默认 FastAPI 端口
- **类型**: 整数
- **默认值**: `2048`
- **示例**: `DEFAULT_FASTAPI_PORT=3048`
- **说明**: 当使用 GUI 或命令行启动时的默认端口，与 `PORT` 配合使用

### DEFAULT_CAMOUFOX_PORT

- **用途**: Camoufox 浏览器调试端口
- **类型**: 整数
- **默认值**: `9222`
- **示例**: `DEFAULT_CAMOUFOX_PORT=9223`
- **说明**: Camoufox 内部启动时使用的 CDP (Chrome DevTools Protocol) 端口

### STREAM_PORT

- **用途**: 集成流式代理服务端口
- **类型**: 整数
- **默认值**: `3120`
- **特殊值**: `0` - 禁用流式代理服务
- **示例**: `STREAM_PORT=3121`
- **说明**: 内置流式代理服务的监听端口，用于三层响应获取机制的第一层

---

## 启动配置

### DIRECT_LAUNCH

- **用途**: 快速启动
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `DIRECT_LAUNCH=false`
- **说明**: 跳过等待选项超时，直接使用默认选项快速启动

### SKIP_FRONTEND_BUILD

- **用途**: 跳过前端构建检查
- **类型**: 布尔值
- **默认值**: `false`
- **可选值**: `true`, `false`, `1`, `0`, `yes`, `no`
- **示例**: `SKIP_FRONTEND_BUILD=true`
- **说明**: 跳过启动时的前端资源构建检查。适用于没有 Node.js/npm 的环境，或使用预构建资源的部署场景。也可通过命令行参数 `--skip-frontend-build` 设置。

---

## 代理配置

### HTTP_PROXY

- **用途**: HTTP 代理服务器地址
- **类型**: 字符串 (URL)
- **默认值**: 空
- **示例**: `HTTP_PROXY=http://127.0.0.1:7890`
- **说明**: 用于 HTTP 请求的上游代理

### HTTPS_PROXY

- **用途**: HTTPS 代理服务器地址
- **类型**: 字符串 (URL)
- **默认值**: 空
- **示例**: `HTTPS_PROXY=http://127.0.0.1:7890`
- **说明**: 用于 HTTPS 请求的上游代理

### UNIFIED_PROXY_CONFIG

- **用途**: 统一代理配置（优先级高于 HTTP_PROXY/HTTPS_PROXY）
- **类型**: 字符串 (URL)
- **默认值**: `空`
- **示例**: `UNIFIED_PROXY_CONFIG=socks5://127.0.0.1:1080`
- **说明**: 推荐使用此配置，会同时应用到 HTTP 和 HTTPS 请求

### NO_PROXY

- **用途**: 代理绕过列表
- **类型**: 字符串（分号或逗号分隔）
- **默认值**: 空
- **示例**: `NO_PROXY=localhost;127.0.0.1;*.local`
- **说明**: 指定不通过代理的主机名或 IP 地址

---

## 日志配置

### SERVER_LOG_LEVEL

- **用途**: 服务器日志级别
- **类型**: 字符串
- **默认值**: `INFO`
- **可选值**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **示例**: `SERVER_LOG_LEVEL=DEBUG`
- **说明**: 控制 FastAPI 服务器的日志详细程度

### SERVER_REDIRECT_PRINT

- **用途**: 是否重定向 print 输出到日志
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `SERVER_REDIRECT_PRINT=true`
- **说明**: 启用后，所有 `print()` 语句会被重定向到日志系统

### DEBUG_LOGS_ENABLED

- **用途**: 启用调试日志
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `DEBUG_LOGS_ENABLED=true`
- **说明**: 启用后会输出更详细的调试信息

### TRACE_LOGS_ENABLED

- **用途**: 启用跟踪日志
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `TRACE_LOGS_ENABLED=true`
- **说明**: 启用最详细的跟踪级别日志，用于深度调试

### JSON_LOGS

- **用途**: 启用 JSON 结构化日志
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `JSON_LOGS=true`
- **说明**: 启用后以 JSON 格式输出日志，适用于 ELK/Datadog 等日志聚合工具

### LOG_FILE_MAX_BYTES

- **用途**: 单个日志文件最大字节数
- **类型**: 整数
- **默认值**: `10485760` (10MB)
- **示例**: `LOG_FILE_MAX_BYTES=20971520`
- **说明**: 日志文件达到此大小后会自动轮换

### LOG_FILE_BACKUP_COUNT

- **用途**: 保留的日志备份文件数量
- **类型**: 整数
- **默认值**: `5`
- **示例**: `LOG_FILE_BACKUP_COUNT=10`
- **说明**: 轮换时保留的备份日志文件数量

---

## 认证配置

### AUTO_SAVE_AUTH

- **用途**: 自动保存认证信息到文件
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `AUTO_SAVE_AUTH=true`
- **说明**: 启用后会自动保存 Google 认证 Cookie 到 `auth_profiles/` 目录

### AUTH_SAVE_TIMEOUT

- **用途**: 认证保存超时时间（秒）
- **类型**: 整数
- **默认值**: `30`
- **示例**: `AUTH_SAVE_TIMEOUT=60`
- **说明**: 等待认证文件保存完成的最大时间

### ONLY_COLLECT_CURRENT_USER_ATTACHMENTS

- **用途**: 仅收集当前用户附件
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `ONLY_COLLECT_CURRENT_USER_ATTACHMENTS=true`
- **说明**: 启用后，仅处理当前用户消息中的附件，忽略历史消息中的附件

---

## 浏览器配置

### CAMOUFOX_WS_ENDPOINT

- **用途**: Camoufox WebSocket 端点 URL
- **类型**: 字符串 (WebSocket URL)
- **默认值**: 空（由启动脚本自动设置）
- **示例**: `CAMOUFOX_WS_ENDPOINT=ws://127.0.0.1:9222`
- **说明**: Playwright 连接 Camoufox 浏览器的 WebSocket 地址

### LAUNCH_MODE

- **用途**: 启动模式
- **类型**: 字符串
- **默认值**: `normal`
- **可选值**:
  - `normal` - 普通模式（有 UI）
  - `headless` - 无头模式（无 UI）
  - `virtual_display` - 虚拟显示模式
  - `direct_debug_no_browser` - 直接调试模式（不启动浏览器）
- **示例**: `LAUNCH_MODE=headless`
- **说明**: 控制浏览器的启动方式

### ENDPOINT_CAPTURE_TIMEOUT

- **用途**: WebSocket 端点捕获超时（秒）
- **类型**: 整数
- **默认值**: `45`
- **示例**: `ENDPOINT_CAPTURE_TIMEOUT=60`
- **说明**: 等待 Camoufox 浏览器启动并返回 WebSocket 端点的最大时间

---

## API 默认参数

### DEFAULT_TEMPERATURE

- **用途**: 默认温度参数
- **类型**: 浮点数
- **默认值**: `1.0`
- **范围**: `0.0` - `2.0`
- **示例**: `DEFAULT_TEMPERATURE=0.7`
- **说明**: 控制模型输出的随机性，值越高越随机

### DEFAULT_MAX_OUTPUT_TOKENS

- **用途**: 默认最大输出 token 数
- **类型**: 整数
- **默认值**: `65536`
- **示例**: `DEFAULT_MAX_OUTPUT_TOKENS=8192`
- **说明**: 限制模型生成文本的最大长度

### DEFAULT_TOP_P

- **用途**: 默认 Top-P 参数（核采样）
- **类型**: 浮点数
- **默认值**: `0.95`
- **范围**: `0.0` - `1.0`
- **示例**: `DEFAULT_TOP_P=0.9`
- **说明**: 控制采样的多样性，值越小结果越集中

### DEFAULT_STOP_SEQUENCES

- **用途**: 默认停止序列
- **类型**: JSON 数组
- **默认值**: `["用户:"]`
- **示例**: `DEFAULT_STOP_SEQUENCES=["\\n\\nUser:", "\\n\\nAssistant:"]`
- **说明**: 遇到这些序列时停止生成，注意需要正确转义特殊字符

### ENABLE_URL_CONTEXT

- **用途**: 是否启用 URL Context 功能
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `ENABLE_URL_CONTEXT=true`
- **说明**: 启用后可以在请求中包含 URL 上下文（参考：https://ai.google.dev/gemini-api/docs/url-context）

### ENABLE_THINKING_BUDGET

- **用途**: 是否默认启用思考预算限制
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `ENABLE_THINKING_BUDGET=true`
- **说明**: 启用后会使用指定的思考预算，不启用时模型自行决定

### DEFAULT_THINKING_BUDGET

- **用途**: 默认思考预算量（token）
- **类型**: 整数
- **默认值**: `8192`
- **示例**: `DEFAULT_THINKING_BUDGET=16384`
- **说明**: 当 API 请求未提供 `reasoning_effort` 参数时使用此值

### DEFAULT_THINKING_LEVEL_PRO

- **用途**: Gemini Pro 模型的默认思考等级
- **类型**: 字符串
- **默认值**: `high`
- **可选值**: `high`, `low`
- **示例**: `DEFAULT_THINKING_LEVEL_PRO=low`
- **说明**: 适用于 gemini-3-pro-preview 等 Pro 模型。当 API 请求中未提供 `reasoning_effort` 参数时使用此值

### DEFAULT_THINKING_LEVEL_FLASH

- **用途**: Gemini Flash 模型的默认思考等级
- **类型**: 字符串
- **默认值**: `high`
- **可选值**: `high`, `medium`, `low`, `minimal`
- **示例**: `DEFAULT_THINKING_LEVEL_FLASH=medium`
- **说明**: 适用于 gemini-3-flash-preview 等 Flash 模型。当 API 请求中未提供 `reasoning_effort` 参数时使用此值

### ENABLE_GOOGLE_SEARCH

- **用途**: 是否默认启用 Google Search 功能
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `ENABLE_GOOGLE_SEARCH=true`
- **说明**: 当 API 请求未提供 `tools` 参数时，此配置决定是否启用 Google 搜索工具

### MCP_HTTP_ENDPOINT

- **用途**: MCP (Model Context Protocol) 服务端点
- **类型**: 字符串 (URL)
- **默认值**: 空
- **示例**: `MCP_HTTP_ENDPOINT=http://localhost:7000`
- **说明**: 指定 MCP 服务的 HTTP 端点，用于处理非内置工具调用。当请求中包含未知的工具调用时，系统会尝试将请求转发到此端点。

### MCP_HTTP_TIMEOUT

- **用途**: MCP 服务请求超时时间（秒）
- **类型**: 浮点数
- **默认值**: `15`
- **示例**: `MCP_HTTP_TIMEOUT=30`
- **说明**: 调用 MCP 服务端点时的最大等待时间

---

## 超时配置

所有超时配置单位均为毫秒（ms），除非特别说明。

### RESPONSE_COMPLETION_TIMEOUT

- **用途**: 响应完成总超时时间
- **类型**: 整数（毫秒）
- **默认值**: `300000` (5 分钟)
- **示例**: `RESPONSE_COMPLETION_TIMEOUT=600000`
- **说明**: 等待 AI Studio 完成响应的最大时间

### INITIAL_WAIT_MS_BEFORE_POLLING

- **用途**: 轮询前的初始等待时间
- **类型**: 整数（毫秒）
- **默认值**: `500`
- **示例**: `INITIAL_WAIT_MS_BEFORE_POLLING=1000`
- **说明**: 开始轮询响应状态前的等待时间

### POLLING_INTERVAL

- **用途**: 非流式模式轮询间隔
- **类型**: 整数（毫秒）
- **默认值**: `300`
- **示例**: `POLLING_INTERVAL=500`
- **说明**: 非流式请求检查响应状态的间隔

### POLLING_INTERVAL_STREAM

- **用途**: 流式模式轮询间隔
- **类型**: 整数（毫秒）
- **默认值**: `180`
- **示例**: `POLLING_INTERVAL_STREAM=200`
- **说明**: 流式请求检查响应状态的间隔

### SILENCE_TIMEOUT_MS

- **用途**: 静默超时时间
- **类型**: 整数（毫秒）
- **默认值**: `60000` (1 分钟)
- **示例**: `SILENCE_TIMEOUT_MS=120000`
- **说明**: 如果在此时间内无新内容输出，则认为请求超时

### POST_SPINNER_CHECK_DELAY_MS

- **用途**: 加载动画检查延迟
- **类型**: 整数（毫秒）
- **默认值**: `500`
- **说明**: 检查页面加载动画状态前的延迟

### FINAL_STATE_CHECK_TIMEOUT_MS

- **用途**: 最终状态检查超时
- **类型**: 整数（毫秒）
- **默认值**: `1500`
- **说明**: 等待页面达到最终状态的超时时间

### POST_COMPLETION_BUFFER

- **用途**: 完成后缓冲时间
- **类型**: 整数（毫秒）
- **默认值**: `700`
- **说明**: 响应完成后的额外等待时间，确保所有内容已加载

### CLEAR_CHAT_VERIFY_TIMEOUT_MS

- **用途**: 清空聊天验证超时
- **类型**: 整数（毫秒）
- **默认值**: `5000`
- **示例**: `CLEAR_CHAT_VERIFY_TIMEOUT_MS=6000`
- **说明**: 验证聊天是否已清空的超时时间

### CLEAR_CHAT_VERIFY_INTERVAL_MS

- **用途**: 清空聊天验证间隔
- **类型**: 整数（毫秒）
- **默认值**: `2000`
- **示例**: `CLEAR_CHAT_VERIFY_INTERVAL_MS=1000`
- **说明**: 检查聊天是否已清空的间隔

### CLICK_TIMEOUT_MS

- **用途**: 点击操作超时
- **类型**: 整数（毫秒）
- **默认值**: `3000`
- **说明**: 等待页面元素可点击的超时时间

### CLIPBOARD_READ_TIMEOUT_MS

- **用途**: 剪贴板读取超时
- **类型**: 整数（毫秒）
- **默认值**: `3000`
- **说明**: 读取浏览器剪贴板内容的超时时间

### WAIT_FOR_ELEMENT_TIMEOUT_MS

- **用途**: 元素等待超时
- **类型**: 整数（毫秒）
- **默认值**: `10000`
- **说明**: 等待页面元素出现的通用超时时间

### PSEUDO_STREAM_DELAY

- **用途**: 伪流式延迟
- **类型**: 浮点数（秒）
- **默认值**: `0.01`
- **示例**: `PSEUDO_STREAM_DELAY=0.02`
- **说明**: 伪流式输出时每个数据块之间的延迟

---

## GUI 启动器配置

> [!WARNING]
> GUI 启动器 (`gui_launcher.py`) 已移至 `deprecated/` 目录。以下配置仅供参考。

### GUI_DEFAULT_PROXY_ADDRESS

- **用途**: GUI 启动器的默认代理地址
- **类型**: 字符串 (URL)
- **默认值**: `http://127.0.0.1:7890`
- **示例**: `GUI_DEFAULT_PROXY_ADDRESS=http://127.0.0.1:1080`
- **说明**: 在 GUI 启动器中预填充的代理地址

### GUI_DEFAULT_STREAM_PORT

- **用途**: GUI 启动器的默认流式端口
- **类型**: 整数
- **默认值**: `3120`
- **示例**: `GUI_DEFAULT_STREAM_PORT=3121`
- **说明**: 在 GUI 启动器中预填充的流式代理端口

### GUI_DEFAULT_HELPER_ENDPOINT

- **用途**: GUI 启动器的默认 Helper 端点
- **类型**: 字符串 (URL)
- **默认值**: 空
- **示例**: `GUI_DEFAULT_HELPER_ENDPOINT=http://helper.example.com`
- **说明**: 外部 Helper 服务的 URL（可选）

---

## 脚本注入配置

### ENABLE_SCRIPT_INJECTION

- **用途**: 是否启用油猴脚本注入功能 (v3.0)
- **类型**: 布尔值
- **默认值**: `false`
- **示例**: `ENABLE_SCRIPT_INJECTION=true`
- **说明**: 启用后，系统将自动从油猴脚本解析模型列表并注入到 API 响应中。v3.0 版本使用 Playwright 原生网络拦截，提供更高的可靠性。

### USERSCRIPT_PATH

- **用途**: 油猴脚本文件路径
- **类型**: 字符串（相对路径）
- **默认值**: `browser_utils/more_models.js`
- **示例**: `USERSCRIPT_PATH=custom_scripts/my_script.js`
- **说明**: 相对于项目根目录的脚本文件路径

---

## 其他配置

### MODEL_NAME

- **用途**: 代理服务的模型名称标识
- **类型**: 字符串
- **默认值**: `AI-Studio_Proxy_API`
- **示例**: `MODEL_NAME=Custom_Proxy`
- **说明**: 在 `/v1/models` 端点返回的代理自身模型名称

### CHAT_COMPLETION_ID_PREFIX

- **用途**: 聊天完成 ID 前缀
- **类型**: 字符串
- **默认值**: `chatcmpl-`
- **示例**: `CHAT_COMPLETION_ID_PREFIX=custom-`
- **说明**: 生成聊天完成响应 ID 时的前缀

### DEFAULT_FALLBACK_MODEL_ID

- **用途**: 默认回退模型 ID
- **类型**: 字符串
- **默认值**: `no model list`
- **示例**: `DEFAULT_FALLBACK_MODEL_ID=gemini-pro`
- **说明**: 当无法获取模型列表时使用的回退模型名称

### EXCLUDED_MODELS_FILENAME

- **用途**: 排除模型列表文件名
- **类型**: 字符串
- **默认值**: `excluded_models.txt`
- **示例**: `EXCLUDED_MODELS_FILENAME=my_excluded.txt`
- **说明**: 包含要从模型列表中排除的模型 ID 的文件名

### AI_STUDIO_URL_PATTERN

- **用途**: AI Studio URL 匹配模式
- **类型**: 字符串
- **默认值**: `aistudio.google.com/`
- **说明**: 用于识别 AI Studio 页面的 URL 模式

### MODELS_ENDPOINT_URL_CONTAINS

- **用途**: 模型列表端点 URL 包含字符串
- **类型**: 字符串
- **默认值**: `MakerSuiteService/ListModels`
- **说明**: 用于拦截模型列表请求的 URL 特征字符串

### USER_INPUT_START_MARKER_SERVER

- **用途**: 用户输入开始标记符
- **类型**: 字符串
- **默认值**: `__USER_INPUT_START__`
- **说明**: 用于标记用户输入开始位置的内部标记

### USER_INPUT_END_MARKER_SERVER

- **用途**: 用户输入结束标记符
- **类型**: 字符串
- **默认值**: `__USER_INPUT_END__`
- **说明**: 用于标记用户输入结束位置的内部标记

---

## 流状态配置

### STREAM_MAX_INITIAL_ERRORS

- **用途**: 流超时日志的最大初始错误数
- **类型**: 整数
- **默认值**: `3`
- **示例**: `STREAM_MAX_INITIAL_ERRORS=5`
- **说明**: 在抑制重复错误日志前允许的最大错误次数

### STREAM_WARNING_INTERVAL_AFTER_SUPPRESS

- **用途**: 抑制后的警告间隔（秒）
- **类型**: 浮点数
- **默认值**: `60.0`
- **示例**: `STREAM_WARNING_INTERVAL_AFTER_SUPPRESS=120.0`
- **说明**: 错误被抑制后，再次显示警告的时间间隔

### STREAM_SUPPRESS_DURATION_AFTER_INITIAL_BURST

- **用途**: 初始爆发后的抑制持续时间（秒）
- **类型**: 浮点数
- **默认值**: `400.0`
- **示例**: `STREAM_SUPPRESS_DURATION_AFTER_INITIAL_BURST=600.0`
- **说明**: 初始错误爆发后，抑制重复日志的时长

---

## 配置最佳实践

### 1. 使用 .env 文件

将所有配置集中在项目根目录的 `.env` 文件中：

```bash
# 复制模板
cp .env.example .env

# 编辑配置
nano .env
```

### 2. 配置优先级

配置项按以下优先级顺序生效（从高到低）：

1. **命令行参数** - 临时覆盖配置
2. **环境变量** - `.env` 文件或系统环境变量
3. **默认值** - 代码中定义的默认值

### 3. 安全注意事项

- ✅ `.env` 文件已在 `.gitignore` 中，不会被提交
- ✅ 不要在 `.env.example` 中包含真实的敏感信息
- ✅ 定期更新和审查配置
- ✅ 使用足够复杂的密钥和凭据

### 4. 调试配置

启用详细日志进行调试：

```env
DEBUG_LOGS_ENABLED=true
TRACE_LOGS_ENABLED=true
SERVER_LOG_LEVEL=DEBUG
SERVER_REDIRECT_PRINT=true
```

### 5. 生产环境配置

生产环境推荐配置：

```env
SERVER_LOG_LEVEL=WARNING
DEBUG_LOGS_ENABLED=false
TRACE_LOGS_ENABLED=false
RESPONSE_COMPLETION_TIMEOUT=600000
SILENCE_TIMEOUT_MS=120000
```

---

## 相关文档

- [环境变量配置指南](environment-configuration.md) - 配置管理和使用方法
- [安装指南](installation-guide.md) - 安装和初始设置
- [故障排除指南](troubleshooting.md) - 常见配置问题解决方案
- [高级配置指南](advanced-configuration.md) - 高级配置选项

---

## 验证配置

启动服务后，检查日志确认配置是否正确加载：

```bash
# 查看启动日志
tail -f logs/app.log

# 检查配置端点
curl http://127.0.0.1:2048/api/info

# 健康检查
curl http://127.0.0.1:2048/health
```
