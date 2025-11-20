# API 使用指南

本指南详细介绍如何使用 AI Studio Proxy API 的各种功能和端点。

## 服务器配置

代理服务器默认监听在 `http://127.0.0.1:2048`。端口可以通过以下方式配置：

- **环境变量**: 在 `.env` 文件中设置 `PORT=2048` 或 `DEFAULT_FASTAPI_PORT=2048`
- **命令行参数**: 使用 `--server-port` 参数
- **GUI 启动器**: 在图形界面中直接配置端口

推荐使用 `.env` 文件进行配置管理，详见 [环境变量配置指南](environment-configuration.md)。

## API 密钥配置

### key.txt 文件配置

项目使用 `auth_profiles/key.txt` 文件来管理 API 密钥：

**文件位置**: 项目根目录下的 `key.txt` 文件

**文件格式**: 每行一个 API 密钥，支持空行和注释

```
your-api-key-1
your-api-key-2
# 这是注释行，会被忽略

another-api-key
```

**自动创建**: 如果 `key.txt` 文件不存在，系统会自动创建一个空文件

### 密钥管理方法

#### 手动编辑文件

直接编辑 `key.txt` 文件添加或删除密钥：

```bash
# 添加密钥
echo "your-new-api-key" >> key.txt

# 查看当前密钥（注意安全）
cat key.txt
```

#### 通过 Web UI 管理

在 Web UI 的"设置"标签页中可以：

- 验证密钥有效性
- 查看服务器上配置的密钥列表（需要先验证）
- 测试特定密钥

### 密钥验证机制

**验证逻辑**:

- 如果 `key.txt` 为空或不存在，则不需要 API 密钥验证
- 如果配置了密钥，则所有 API 请求都需要提供有效的密钥
- 密钥验证支持两种认证头格式

**安全特性**:

- 密钥在日志中会被打码显示（如：`abcd****efgh`）
- Web UI 中的密钥列表也会打码显示
- 支持最小长度验证（至少 8 个字符）

## API 认证流程

### Bearer Token 认证

项目支持标准的 OpenAI 兼容认证方式：

**主要认证方式** (推荐):

```bash
Authorization: Bearer your-api-key
```

**备用认证方式** (向后兼容):

```bash
X-API-Key: your-api-key
```

### 认证行为

**无密钥配置时**:

- 所有 API 请求都不需要认证
- `/api/info` 端点会显示 `"api_key_required": false`

**有密钥配置时**:

- 所有 `/v1/*` 路径的 API 请求都需要有效的密钥
- 除外路径：`/v1/models`, `/health`, `/docs` 等公开端点
- 认证失败返回 `401 Unauthorized` 错误

### 客户端配置示例

#### curl 示例

```bash
# 使用 Bearer token
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# 使用 X-API-Key 头
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

#### Python requests 示例

```python
import requests

headers = {
    "Authorization": "Bearer your-api-key",
    "Content-Type": "application/json"
}

data = {
    "messages": [{"role": "user", "content": "Hello"}]
}

response = requests.post(
    "http://127.0.0.1:2048/v1/chat/completions",
    headers=headers,
    json=data
)
```

## API 端点

### 聊天接口

**端点**: `POST /v1/chat/completions`

- 请求体与 OpenAI API 兼容，需要 `messages` 数组。
- `model` 字段现在用于指定目标模型，代理会尝试在 AI Studio 页面切换到该模型。如果为空或为代理的默认模型名，则使用 AI Studio 当前激活的模型。
- `stream` 字段控制流式 (`true`) 或非流式 (`false`) 输出。
- 现在支持 `temperature`, `max_output_tokens`, `top_p`, `stop`, `reasoning_effort` 等参数，代理会尝试在 AI Studio 页面上应用它们。
- **需要认证**: 如果配置了 API 密钥，此端点需要有效的认证头。

#### 思考模式控制 (reasoning_effort 参数)

`reasoning_effort` 参数用于控制 AI Studio 的思考模式和预算。支持以下三种使用场景：

**场景1: 关闭思考模式**

```json
{
  "reasoning_effort": 0     // 整数 0
}
```
或
```json
{
  "reasoning_effort": "0"   // 字符串 "0"
}
```

行为:
- 关闭主思考开关，完全禁用思考模式
- 如果主开关不可用（某些模型版本），将预算设置为 0 作为降级方案，网页会自动设置成最低的budget

**场景2: 开启思考并限制预算**

使用预设值:
```json
{
  "reasoning_effort": 1000       // 使用具体数值限制预算
  // 或 8000
  // 或 32768
}
```

使用具体数值:
```json
{
  "reasoning_effort": 5000       // 整数，设置具体的 token 预算
}
```
或
```json
{
  "reasoning_effort": "3000"     // 字符串数值也支持
}
```

行为:
- 开启主思考开关
- 开启手动预算限制
- 设置具体的预算值

**场景3: 开启思考但不限制预算**

```json
{
  "reasoning_effort": "none"     // 字符串 "none"
}
```
或
```json
{
  "reasoning_effort": -1         // 整数 -1
}
```
或
```json
{
  "reasoning_effort": "-1"       // 字符串 "-1"
}
```

行为:
- 开启主思考开关
- 关闭手动预算限制，让模型自由思考

**默认行为**

如果不指定 `reasoning_effort` 参数，将使用服务器默认配置（由环境变量 `ENABLE_THINKING_BUDGET` 和 `DEFAULT_THINKING_BUDGET` 控制）。

**参数格式说明**

- 大小写不敏感: `"low"`, `"Low"`, `"LOW"` 效果相同
- 支持空格: `" medium "`, `" 3000 "` 会自动去除空格
- 类型灵活: 数值可以是整数或字符串格式

#### 示例 (curl, 非流式, 带参数)

```bash
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{
  "model": "gemini-2.5-pro",
  "messages": [
    {"role": "system", "content": "Be concise."},
    {"role": "user", "content": "What is the capital of France?"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_output_tokens": 150,
  "top_p": 0.9,
  "stop": ["\n\nUser:"],
  "reasoning_effort": "medium"
}'
```

#### 示例 (curl, 使用思考模式, 不限制预算)

```bash
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{
  "model": "gemini-flash-latest",
  "messages": [
    {"role": "user", "content": "解释量子纠缠的原理，并思考其在量子计算中的应用"}
  ],
  "stream": false,
  "reasoning_effort": "none"
}'
```

#### 示例 (curl, 流式, 带参数)

```bash
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{
  "model": "gemini-2.5-pro",
  "messages": [
    {"role": "user", "content": "Write a short story about a cat."}
  ],
  "stream": true,
  "temperature": 0.9,
  "top_p": 0.95,
  "stop": []
}' --no-buffer
```

#### 示例 (Python requests)

```python
import requests
import json

API_URL = "http://127.0.0.1:2048/v1/chat/completions"
headers = {"Content-Type": "application/json"}
data = {
    "model": "gemini-2.5-flash-latest",
    "messages": [
        {"role": "user", "content": "Translate 'hello' to Spanish."}
    ],
    "stream": False, # or True for streaming
    "temperature": 0.5,
    "max_output_tokens": 100,
    "top_p": 0.9,
    "stop": ["\n\nHuman:"]
}

response = requests.post(API_URL, headers=headers, json=data, stream=data["stream"])

if data["stream"]:
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith('data: '):
                content = decoded_line[len('data: '):]
                if content.strip() == '[DONE]':
                    print("\nStream finished.")
                    break
                try:
                    chunk = json.loads(content)
                    delta = chunk.get('choices', [{}])[0].get('delta', {})
                    print(delta.get('content', ''), end='', flush=True)
                except json.JSONDecodeError:
                    print(f"\nError decoding JSON: {content}")
            elif decoded_line.startswith('data: {'): # Handle potential error JSON
                try:
                    error_data = json.loads(decoded_line[len('data: '):])
                    if 'error' in error_data:
                        print(f"\nError from server: {error_data['error']}")
                        break
                except json.JSONDecodeError:
                     print(f"\nError decoding error JSON: {decoded_line}")
else:
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code}\n{response.text}")
```

### 模型列表

**端点**: `GET /v1/models`

- 返回 AI Studio 页面上检测到的可用模型列表，以及一个代理本身的默认模型条目。
- 现在会尝试从 AI Studio 动态获取模型列表。如果获取失败，会返回一个后备模型。
- 支持 [`excluded_models.txt`](../excluded_models.txt) 文件，用于从列表中排除特定的模型 ID。
- 注入模型功能已不再支持
<!-- - **🆕 脚本注入模型**: 如果启用了脚本注入功能，列表中还会包含通过油猴脚本注入的自定义模型，这些模型会标记为 `"injected": true`。

**脚本注入模型特点**:

- 模型 ID 格式：注入的模型会自动移除 `models/` 前缀，如 `models/kingfall-ab-test` 变为 `kingfall-ab-test`
- 标识字段：包含 `"injected": true` 字段用于识别
- 所有者标识：`"owned_by": "ai_studio_injected"`
- 完全兼容：可以像普通模型一样通过 API 调用

**示例响应**:

```json
{
  "object": "list",
  "data": [
    {
      "id": "kingfall-ab-test",
      "object": "model",
      "created": 1703123456,
      "owned_by": "ai_studio_injected",
      "display_name": "👑 Kingfall",
      "description": "Kingfall model - Advanced reasoning capabilities",
      "injected": true
    }
  ]
}
``` -->

### API 信息

**端点**: `GET /api/info`

- 返回 API 配置信息，如基础 URL 和模型名称。

### 健康检查

**端点**: `GET /health`

- 返回服务器运行状态（Playwright, 浏览器连接, 页面状态, Worker 状态, 队列长度）。

### 队列状态

**端点**: `GET /v1/queue`

- 返回当前请求队列的详细信息。

### 取消请求

**端点**: `POST /v1/cancel/{req_id}`

- 尝试取消仍在队列中等待处理的请求。

### API 密钥管理端点

#### 获取密钥列表

**端点**: `GET /api/keys`

- 返回服务器上配置的所有 API 密钥列表
- **注意**: 服务器返回完整密钥，打码显示由 Web UI 前端处理
- **无需认证**: 此端点不需要 API 密钥认证

#### 测试密钥

**端点**: `POST /api/keys/test`

- 验证指定的 API 密钥是否有效
- 请求体：`{"key": "your-api-key"}`
- 返回：`{"success": true, "valid": true/false, "message": "..."}`
- **无需认证**: 此端点不需要 API 密钥认证

#### 添加密钥

**端点**: `POST /api/keys`

- 向服务器添加新的 API 密钥
- 请求体：`{"key": "your-new-api-key"}`
- 密钥要求：至少 8 个字符，不能重复
- **无需认证**: 此端点不需要 API 密钥认证

#### 删除密钥

**端点**: `DELETE /api/keys`

- 从服务器删除指定的 API 密钥
- 请求体：`{"key": "key-to-delete"}`
- **无需认证**: 此端点不需要 API 密钥认证

## 配置客户端 (以 Open WebUI 为例)

1. 打开 Open WebUI。
2. 进入 "设置" -> "连接"。
3. 在 "模型" 部分，点击 "添加模型"。
4. **模型名称**: 输入你想要的名字，例如 `aistudio-gemini-py`。
5. **API 基础 URL**: 输入代理服务器的地址，例如 `http://127.0.0.1:2048/v1` (如果服务器在另一台机器，用其 IP 替换 `127.0.0.1`，并确保端口可访问)。
6. **API 密钥**: 留空或输入任意字符 (服务器不验证)。
7. 保存设置。
8. 现在，你应该可以在 Open WebUI 中选择你在第一步中配置的模型名称并开始聊天了。如果之前配置过，可能需要刷新或重新选择模型以应用新的 API 基地址。

## 重要提示

### 三层响应获取机制与参数控制

- **响应获取优先级**: 项目采用三层响应获取机制，确保高可用性和最佳性能：

  1. **集成流式代理服务 (Stream Proxy)**:
     - 默认启用，监听端口 `3120` (可通过 `.env` 文件的 `STREAM_PORT` 配置)
     - 提供最佳性能和稳定性，直接处理 AI Studio 请求
     - 支持基础参数传递，无需浏览器交互
  2. **外部 Helper 服务**:
     - 可选配置，通过 `--helper <endpoint_url>` 参数或 `.env` 配置启用
     - 需要有效的认证文件 (`auth_profiles/active/*.json`) 提取 `SAPISID` Cookie
     - 作为流式代理的备用方案
  3. **Playwright 页面交互**:
     - 最终后备方案，通过浏览器自动化获取响应
     - 支持完整的参数控制和模型切换
     - 通过模拟用户操作（编辑/复制按钮）获取响应

- **参数控制详解**:

  - **流式代理模式**: 支持基础参数 (`model`, `temperature`, `max_tokens` 等)，性能最优
  - **Helper 服务模式**: 参数支持取决于外部 Helper 服务的具体实现
  - **Playwright 模式**: 完整支持所有参数，包括 `temperature`, `max_output_tokens`, `top_p`, `stop`, `reasoning_effort`, `tools` 等

- **模型管理**:

  - API 请求中的 `model` 字段用于在 AI Studio 页面切换模型
  - 支持动态模型列表获取和模型 ID 验证
  - [`excluded_models.txt`](../excluded_models.txt) 文件可排除特定模型 ID

- **🆕 脚本注入功能 v3.0**:
  - 使用 Playwright 原生网络拦截，100% 可靠性
  - 直接从油猴脚本解析模型数据，无需配置文件维护
  - 前后端模型数据完全同步，注入模型标记为 `"injected": true`
  - 详见 [脚本注入指南](script_injection_guide.md)

### 客户端管理历史

**客户端管理历史，代理不支持 UI 内编辑**: 客户端负责维护完整的聊天记录并将其发送给代理。代理服务器本身不支持在 AI Studio 界面中对历史消息进行编辑或分叉操作；它总是处理客户端发送的完整消息列表，然后将其发送到 AI Studio 页面。

## 兼容性说明

### Python 版本兼容性

- **推荐版本**: Python 3.10+ 或 3.11+ (生产环境推荐)
- **最低要求**: Python 3.9 (所有功能完全支持)
- **Docker 环境**: Python 3.10 (容器内默认版本)
- **完全支持**: Python 3.9, 3.10, 3.11, 3.12, 3.13
- **依赖管理**: 使用 Poetry 管理，确保版本一致性

### API 兼容性

- **OpenAI API**: 完全兼容 OpenAI v1 API 标准，支持所有主流客户端
- **FastAPI**: 基于 0.115.12 版本，包含最新性能优化和功能增强
- **HTTP 协议**: 支持 HTTP/1.1 和 HTTP/2，完整的异步处理
- **认证方式**: 支持 Bearer Token 和 X-API-Key 头部认证，OpenAI 标准兼容
- **流式响应**: 完整支持 Server-Sent Events (SSE) 流式输出
- **FastAPI**: 基于 0.111.0 版本，支持现代异步特性
- **HTTP 协议**: 支持 HTTP/1.1 和 HTTP/2
- **认证方式**: 支持 Bearer Token 和 X-API-Key 头部认证

## 下一步

API 使用配置完成后，请参考：

- [Web UI 使用指南](webui-guide.md)
- [故障排除指南](troubleshooting.md)
- [日志控制指南](logging-control.md)
