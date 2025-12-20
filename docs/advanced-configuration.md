# 高级配置指南

本文档介绍项目的高级配置选项和功能。

## 代理配置管理

### 代理配置优先级

项目采用统一的代理配置管理系统，按以下优先级顺序确定代理设置：

1. **`--internal-camoufox-proxy` 命令行参数** (最高优先级)
   - 明确指定代理：`--internal-camoufox-proxy 'http://127.0.0.1:7890'`
   - 明确禁用代理：`--internal-camoufox-proxy ''`
2. **`UNIFIED_PROXY_CONFIG` 环境变量** (推荐，.env 文件配置)
3. **`HTTP_PROXY` / `HTTPS_PROXY` 环境变量**
4. **系统代理设置** (Linux 下的 gsettings，最低优先级)

**推荐配置方式**:

```env
# .env 文件中统一配置代理
UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890
# 或禁用代理
UNIFIED_PROXY_CONFIG=
```

### 统一代理配置

此代理配置会同时应用于 Camoufox 浏览器和流式代理服务的上游连接，确保整个系统的代理行为一致。

## 响应获取模式配置

### 模式 1: 优先使用集成的流式代理 (默认推荐)

**推荐使用 .env 配置方式**:

```env
# .env 文件配置
DEFAULT_FASTAPI_PORT=2048
STREAM_PORT=3120
UNIFIED_PROXY_CONFIG=
```

```bash
# 简化启动命令 (推荐)
python launch_camoufox.py --headless

# 传统命令行方式 (仍然支持)
python launch_camoufox.py --headless --server-port 2048 --stream-port 3120 --helper '' --internal-camoufox-proxy ''
```

```bash
# 启用统一代理配置（同时应用于浏览器和流式代理）
python launch_camoufox.py --headless --server-port 2048 --stream-port 3120 --helper '' --internal-camoufox-proxy 'http://127.0.0.1:7890'
```

在此模式下，主服务器会优先尝试通过端口 `3120` (或指定的 `--stream-port`) 上的集成流式代理获取响应。如果失败，则回退到 Playwright 页面交互。

### 模式 2: 优先使用外部 Helper 服务 (禁用集成流式代理)

```bash
# 基本外部Helper模式，明确禁用代理
python launch_camoufox.py --headless --server-port 2048 --stream-port 0 --helper 'http://your-helper-service.com/api/getStreamResponse' --internal-camoufox-proxy ''

# 外部Helper模式 + 统一代理配置
python launch_camoufox.py --headless --server-port 2048 --stream-port 0 --helper 'http://your-helper-service.com/api/getStreamResponse' --internal-camoufox-proxy 'http://127.0.0.1:7890'
```

在此模式下，主服务器会优先尝试通过 `--helper` 指定的端点获取响应 (需要有效的 `auth_profiles/active/*.json` 以提取 `SAPISID`)。如果失败，则回退到 Playwright 页面交互。

### 模式 3: 仅使用 Playwright 页面交互 (禁用所有流式代理和 Helper)

```bash
# 纯Playwright模式，明确禁用代理
python launch_camoufox.py --headless --server-port 2048 --stream-port 0 --helper '' --internal-camoufox-proxy ''

# Playwright模式 + 统一代理配置
python launch_camoufox.py --headless --server-port 2048 --stream-port 0 --helper '' --internal-camoufox-proxy 'http://127.0.0.1:7890'
```

在此模式下，主服务器将仅通过 Playwright 与 AI Studio 页面交互 (模拟点击"编辑"或"复制"按钮) 来获取响应。这是传统的后备方法。

## 虚拟显示模式 (Linux)

### 关于 `--virtual-display`

- **为什么使用**: 与标准的无头模式相比，虚拟显示模式通过创建一个完整的虚拟 X 服务器环境 (Xvfb) 来运行浏览器。这可以模拟一个更真实的桌面环境，从而可能进一步降低被网站检测为自动化脚本或机器人的风险
- **什么时候使用**: 当您在 Linux 环境下运行，并且希望以无头模式操作
- **如何使用**:
  1. 确保您的 Linux 系统已安装 `xvfb`
  2. 在运行时添加 `--virtual-display` 标志：
     ```bash
     python launch_camoufox.py --virtual-display --server-port 2048 --stream-port 3120 --internal-camoufox-proxy ''
     ```

## 流式代理服务配置

### 自签名证书管理

集成的流式代理服务会在 `certs` 文件夹内生成自签名的根证书。

#### 证书删除与重新生成

- 可以删除 `certs` 目录下的根证书 (`ca.crt`, `ca.key`)，代码会在下次启动时重新生成
- **重要**: 删除根证书时，**强烈建议同时删除 `certs` 目录下的所有其他文件**，避免信任链错误

#### 手动生成证书

如果需要重新生成证书，可以使用以下命令：

```bash
openssl genrsa -out certs/ca.key 2048
openssl req -new -x509 -days 3650 -key certs/ca.key -out certs/ca.crt -subj "/C=US/ST=State/L=City/O=AiStudioProxyHelper/OU=CA/CN=AiStudioProxyHelper CA/emailAddress=ca@example.com"
openssl rsa -in certs/ca.key -out certs/ca.key
```

### 工作原理

流式代理服务的特性：

- 创建一个 HTTP 代理服务器（默认端口：3120）
- 拦截针对 Google 域名的 HTTPS 请求
- 使用自签名 CA 证书动态自动生成服务器证书
- 将 AIStudio 响应解析为 OpenAI 兼容格式

## 模型排除配置

### excluded_models.txt

项目根目录下的 `excluded_models.txt` 文件可用于从 `/v1/models` 端点返回的列表中排除特定的模型 ID。

每行一个模型 ID，例如：

```
gemini-1.0-pro
gemini-1.0-pro-vision
deprecated-model-id
```

## 脚本注入配置

脚本注入功能允许您动态挂载油猴脚本来增强 AI Studio 的模型列表。该功能使用 Playwright 原生网络拦截技术，确保可靠性。

详细的使用指南、工作原理和故障排除请参考 [脚本注入指南](script_injection_guide.md)。

### 关键配置

```env
# 启用脚本注入功能
ENABLE_SCRIPT_INJECTION=true

# 指定自定义脚本路径 (默认为 browser_utils/more_models.js)
USERSCRIPT_PATH=custom_scripts/my_enhanced_script.js
```

### 调试

如果遇到问题，可以启用详细日志：

```env
DEBUG_LOGS_ENABLED=true
```

## 功能特性开关 (Feature Flags)

以下环境变量可用于启用实验性功能或调整特定行为：

### 思考模型预算控制

```env
# 启用思考模型的 Token 预算控制
ENABLE_THINKING_BUDGET=true
# 设置默认思考预算 (Token数)
DEFAULT_THINKING_BUDGET=8192
```

### 联网搜索增强

```env
# 启用 Google 搜索工具 (如果模型支持)
ENABLE_GOOGLE_SEARCH=true
```

### URL 上下文获取

```env
# 允许解析 Prompt 中的 URL 内容
ENABLE_URL_CONTEXT=true
```

### 附件处理优化

```env
# 仅收集当前用户消息中的附件 (忽略历史消息中的附件，减少 Token 消耗)
ONLY_COLLECT_CURRENT_USER_ATTACHMENTS=true
```

### 前端构建控制

```env
# 跳过启动时的前端资源构建检查 (适用于无 Node.js 环境或使用预构建资源)
SKIP_FRONTEND_BUILD=true
```

也可以通过命令行参数设置：

```bash
python launch_camoufox.py --headless --skip-frontend-build
```

## 模型能力配置

### config/model_capabilities.json

模型能力配置已外部化到 `config/model_capabilities.json` 文件。此配置定义了各模型的：

- **thinkingType**: 思考模式类型 (`none`, `level`, `budget`)
- **supportsGoogleSearch**: 是否支持 Google Search 工具
- **levels/budgetRange**: 思考等级或预算范围

**优势**：当 Google 发布新模型时，只需编辑 JSON 文件，无需修改代码。

示例结构：

```json
{
  "categories": {
    "gemini3Flash": {
      "thinkingType": "level",
      "levels": ["minimal", "low", "medium", "high"],
      "supportsGoogleSearch": true
    }
  },
  "matchers": [{ "pattern": "gemini-3.*-flash", "category": "gemini3Flash" }]
}
```

## GUI 启动器高级功能

### 本地 LLM 模拟服务

GUI 集成了启动和管理一个本地 LLM 模拟服务的功能：

- **功能**: 监听 `11434` 端口，模拟部分 Ollama API 端点和 OpenAI 兼容的 `/v1/chat/completions` 端点
- **启动**: 在 GUI 的"启动选项"区域，点击"启动本地 LLM 模拟服务"按钮
- **依赖检测**: 启动前会自动检测 `localhost:2048` 端口是否可用
- **用途**: 主要用于测试客户端与 Ollama 或 OpenAI 兼容 API 的对接

### 端口进程管理

GUI 提供端口进程管理功能：

- 查询指定端口上当前正在运行的进程
- 选择并尝试停止在指定端口上找到的进程
- 手动输入 PID 终止进程

**安全机制**：进程终止功能会验证 PID 是否属于配置的端口（FastAPI、Camoufox、Stream Proxy），防止意外终止无关进程。

## 环境变量配置

### 代理配置

```bash
# 使用环境变量配置代理（不推荐，建议明确指定）
export UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890
python launch_camoufox.py --headless --server-port 2048 --stream-port 3120 --helper ''
```

### 日志控制

详见 [日志控制指南](logging-control.md)。

## 重要提示

### 代理配置建议

**强烈建议在所有 `launch_camoufox.py` 命令中明确指定 `--internal-camoufox-proxy` 参数，即使其值为空字符串 (`''`)，以避免意外使用系统环境变量中的代理设置。**

### 参数控制限制

API 请求中的模型参数（如 `temperature`, `max_output_tokens`, `top_p`, `stop`）**仅在通过 Playwright 页面交互获取响应时生效**。当使用集成的流式代理或外部 Helper 服务时，这些参数的传递和应用方式取决于这些服务自身的实现。

### 首次访问性能

当通过流式代理首次访问一个新的 HTTPS 主机时，服务需要为该主机动态生成并签署一个新的子证书。这个过程可能会比较耗时，导致对该新主机的首次连接请求响应较慢。一旦证书生成并缓存后，后续访问同一主机将会显著加快。

## 下一步

高级配置完成后，请参考：

- [脚本注入指南](script_injection_guide.md) - 详细的脚本注入功能使用说明
- [日志控制指南](logging-control.md)
- [故障排除指南](troubleshooting.md)

## Toolcall / MCP 兼容性说明

- 请求结构需遵循 OpenAI Completions 兼容格式：
  - `messages`: 标准消息数组，含 `role` 与 `content`
  - `tools`: 工具声明数组，元素形如 `{ "type": "function", "function": { "name": "sum", "parameters": { ... } } }`
  - `tool_choice`: 可为具体函数名或 `{ "type": "function", "function": { "name": "sum" } }`；当为 `"auto"` 且仅声明一个工具时自动执行
- 工具执行行为：
  - 内置工具（`get_current_time`, `echo`, `sum`）直接执行；结果以 JSON 字符串注入
  - 非内置但在本次请求 `tools` 中声明的工具，若提供 MCP 端点（请求字段 `mcp_endpoint` 或环境变量 `MCP_HTTP_ENDPOINT`），则调用 MCP 服务并返回结果
  - 未声明或端点缺失时返回 `Unknown tool`
- 响应兼容：
  - 流式与非流式均输出 OpenAI 兼容的 `tool_calls` 结构与 `finish_reason: "tool_calls"`；最终包含 `usage` 统计和 `[DONE]`

### 请求示例（Python requests）

```python
import requests

API_URL = "http://localhost:2048/v1/chat/completions"

data = {
  "model": "AI-Studio_Proxy_API",
  "stream": True,
  "messages": [
    {"role": "user", "content": "请计算这组数的和: {\"values\": [1, 2.5, 3]}"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "sum",
        "parameters": {
          "type": "object",
          "properties": {
            "values": {"type": "array", "items": {"type": "number"}}
          },
          "required": ["values"]
        }
      }
    }
  ],
  "tool_choice": {"type": "function", "function": {"name": "sum"}},
  # 可选：本次请求的 MCP 端点（非内置工具时启用）
  # "mcp_endpoint": "http://127.0.0.1:7000"
}

resp = requests.post(API_URL, json=data, stream=data["stream"])
for line in resp.iter_lines():
  if not line:
    continue
  print(line.decode("utf-8"))
```

### 行为说明

- 当工具执行发生时，响应中会包含 `tool_calls` 片段与 `finish_reason: "tool_calls"`；客户端需按 OpenAI Completions 的解析方式处理。
- 若声明非内置工具且提供 `mcp_endpoint`（或设置环境 `MCP_HTTP_ENDPOINT`），服务器会将调用转发到 MCP 服务并返回其结果。
