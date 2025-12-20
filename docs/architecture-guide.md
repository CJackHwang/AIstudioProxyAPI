# 项目架构指南

本文档详细介绍 AI Studio Proxy API 项目的模块化架构设计、组件职责和交互关系。

## 🏗️ 整体架构概览

### 核心设计原则

- **模块化分离**: 按功能领域划分模块，避免循环依赖
- **单一职责**: 每个模块专注于特定功能
- **配置统一**: `.env` 文件和 `config/` 模块统一管理配置
- **异步优先**: 全面采用异步编程模式

---

## 📁 模块结构

```
AIstudioProxyAPI/
├── api_utils/                  # FastAPI 应用核心模块
│   ├── app.py                 # 应用入口和生命周期管理
│   ├── routers/               # API 路由（按职责拆分）
│   │   ├── api_keys.py        # /api/keys* 密钥管理
│   │   ├── auth_files.py      # /api/auth-files* 认证文件管理
│   │   ├── chat.py            # /v1/chat/completions
│   │   ├── health.py          # /health 健康检查
│   │   ├── helper.py          # /api/helper* Helper 服务配置
│   │   ├── info.py            # /api/info 信息端点
│   │   ├── logs_ws.py         # /ws/logs WebSocket 日志
│   │   ├── model_capabilities.py  # /api/model-capabilities
│   │   ├── models.py          # /v1/models 模型列表
│   │   ├── ports.py           # /api/ports* 端口配置
│   │   ├── proxy.py           # /api/proxy* 代理配置
│   │   ├── queue.py           # /v1/queue, /v1/cancel
│   │   ├── server.py          # /api/server* 服务器控制
│   │   └── static.py          # /, /assets/* React SPA
│   ├── request_processor.py   # 请求处理核心逻辑
│   ├── queue_worker.py        # 异步队列工作器
│   ├── response_generators.py # SSE 响应生成器
│   ├── auth_utils.py          # 认证工具
│   ├── auth_manager.py        # 认证管理器
│   ├── dependencies.py        # FastAPI 依赖注入
│   ├── client_connection.py   # 客户端连接管理
│   ├── server_state.py        # 服务器状态管理
│   ├── model_switching.py     # 模型切换逻辑
│   ├── mcp_adapter.py         # MCP 协议适配器
│   ├── sse.py                 # SSE 流式响应处理
│   ├── utils.py               # 通用工具函数
│   └── utils_ext/             # 扩展工具模块
│       ├── files.py           # 文件/附件处理
│       ├── helper.py          # Helper 服务工具
│       ├── prompts.py         # 提示词处理
│       ├── stream.py          # 流式处理工具
│       ├── string_utils.py    # 字符串工具
│       ├── tokens.py          # Token 计算
│       ├── tools_execution.py # 工具执行
│       └── validation.py      # 请求验证
│
├── browser_utils/              # 浏览器自动化模块
│   ├── page_controller.py     # 页面控制器（聚合入口）
│   ├── page_controller_modules/  # 控制器子模块 (Mixin)
│   │   ├── base.py            # 基础控制器
│   │   ├── chat.py            # 聊天历史管理
│   │   ├── input.py           # 输入控制
│   │   ├── parameters.py      # 参数控制
│   │   ├── response.py        # 响应获取
│   │   └── thinking.py        # 思考过程控制
│   ├── initialization/        # 初始化模块
│   │   ├── core.py            # 浏览器上下文创建、导航
│   │   ├── network.py         # 网络拦截配置
│   │   ├── auth.py            # 认证状态保存/恢复
│   │   ├── scripts.py         # UserScript 脚本注入
│   │   └── debug.py           # 调试监听器
│   ├── operations_modules/    # 操作子模块
│   │   ├── parsers.py         # 数据解析
│   │   ├── interactions.py    # 页面交互
│   │   └── errors.py          # 错误处理
│   ├── model_management.py    # 模型管理
│   ├── operations.py          # 操作聚合入口
│   ├── debug_utils.py         # 调试工具
│   ├── thinking_normalizer.py # 思考过程标准化
│   └── more_models.js         # 油猴脚本模板
│
├── config/                     # 配置管理模块
│   ├── settings.py            # 主要设置和环境变量
│   ├── constants.py           # 系统常量定义
│   ├── timeouts.py            # 超时配置
│   ├── selectors.py           # CSS 选择器定义
│   ├── selector_utils.py      # 选择器工具函数
│   └── model_capabilities.json # 模型能力配置
│
├── models/                     # 数据模型定义
│   ├── chat.py                # 聊天相关模型
│   ├── exceptions.py          # 自定义异常类
│   └── logging.py             # 日志相关模型
│
├── stream/                     # 流式代理服务模块
│   ├── main.py                # 代理服务入口
│   ├── proxy_server.py        # 代理服务器实现
│   ├── proxy_connector.py     # 代理连接器
│   ├── cert_manager.py        # 证书管理
│   ├── interceptors.py        # 请求拦截器
│   └── utils.py               # 流式处理工具
│
├── launcher/                   # 启动器模块
│   ├── runner.py              # 启动逻辑核心
│   ├── config.py              # 启动配置处理
│   ├── checks.py              # 环境与依赖检查
│   ├── process.py             # Camoufox 进程管理
│   ├── frontend_build.py      # 前端构建检查
│   ├── internal.py            # 内部工具
│   ├── logging_setup.py       # 日志配置
│   └── utils.py               # 启动器工具
│
├── logging_utils/              # 日志管理模块
│   ├── setup.py               # 日志系统配置
│   └── grid_logger.py         # 网格日志器
│
├── server.py                   # 应用入口点
├── launch_camoufox.py          # 命令行启动器（主入口）
├── deprecated/                 # 已废弃的模块
│   └── gui_launcher.py         # [已废弃] GUI 启动器
└── pyproject.toml              # Poetry 配置
```

---

## 🔧 核心模块详解

### 1. api_utils/ - FastAPI 应用核心

**职责**: API 路由、认证、请求处理。

#### app.py - 应用入口

- FastAPI 应用创建和配置
- 生命周期管理 (startup/shutdown)
- 中间件配置 (API 密钥认证)

#### routers/ - API 路由

路由按职责拆分为独立模块:

| 模块                    | 端点                      | 职责               |
| ----------------------- | ------------------------- | ------------------ |
| `chat.py`               | `/v1/chat/completions`    | 聊天完成接口       |
| `models.py`             | `/v1/models`              | 模型列表           |
| `model_capabilities.py` | `/api/model-capabilities` | 模型能力查询       |
| `health.py`             | `/health`                 | 健康检查           |
| `queue.py`              | `/v1/queue`, `/v1/cancel` | 队列管理           |
| `api_keys.py`           | `/api/keys*`              | 密钥管理           |
| `logs_ws.py`            | `/ws/logs`                | 实时日志流         |
| `static.py`             | `/`, `/assets/*`          | React SPA 静态资源 |
| `info.py`               | `/api/info`               | API 信息           |
| `auth_files.py`         | `/api/auth-files*`        | 认证文件管理       |
| `ports.py`              | `/api/ports*`             | 端口配置和进程管理 |
| `proxy.py`              | `/api/proxy*`             | 代理配置管理       |
| `server.py`             | `/api/server*`            | 服务器控制         |
| `helper.py`             | `/api/helper*`            | Helper 服务配置    |

#### queue_worker.py - 队列工作器

- 异步请求队列处理 (FIFO)
- 并发控制和资源管理
- **分级错误恢复机制**:
  - **Tier 1**: 页面快速刷新 (处理临时性 DOM 错误)
  - **Tier 2**: 认证配置文件切换 (处理配额耗尽)

### 2. browser_utils/ - 浏览器自动化

**职责**: 浏览器控制、页面交互、脚本注入。

#### page_controller.py - 页面控制器

基于 Mixin 模式的聚合控制器，继承自 `page_controller_modules/` 子模块。

#### initialization/ - 初始化模块

| 模块         | 职责                             |
| ------------ | -------------------------------- |
| `core.py`    | 浏览器上下文创建、导航、登录检测 |
| `network.py` | 网络拦截、模型列表注入           |
| `auth.py`    | 认证状态保存/恢复                |
| `scripts.py` | UserScript 脚本注入              |
| `debug.py`   | 调试监听器设置                   |

#### 脚本注入机制

脚本注入通过 `initialization/network.py` 实现：

- Playwright 原生路由拦截 `/api/models`
- 从油猴脚本 (`more_models.js`) 解析模型数据
- 模型数据自动同步到页面

### 3. stream/ - 流式代理服务

**职责**: 高性能的流式响应代理。

- **proxy_server.py**: HTTP/HTTPS 代理实现
- **interceptors.py**: AI Studio 请求拦截和响应解析
- **cert_manager.py**: 自签名证书管理

### 4. launcher/ - 启动器模块

**职责**: 应用启动和进程管理。

| 模块         | 职责              |
| ------------ | ----------------- |
| `runner.py`  | 启动逻辑核心      |
| `config.py`  | 启动配置处理      |
| `checks.py`  | 环境与依赖检查    |
| `process.py` | Camoufox 进程管理 |

---

## 🔄 响应获取机制

项目实现三层响应获取机制，确保高可用性：

```
请求 → 第一层: 流式代理 → 第二层: Helper → 第三层: Playwright
```

| 层级           | 类型             | 延迟 | 参数支持   | 适用场景        |
| -------------- | ---------------- | ---- | ---------- | --------------- |
| **流式代理**   | True Streaming   | 最低 | 基础参数   | 生产环境 (推荐) |
| **Helper**     | 取决于实现       | 中等 | 取决于实现 | 特殊网络环境    |
| **Playwright** | Pseudo-Streaming | 最高 | 所有参数   | 调试、参数测试  |

### 请求处理路径

**辅助流路径 (STREAM)**:

- 入口: `_handle_auxiliary_stream_response`
- 从 `STREAM_QUEUE` 消费，产出 OpenAI 兼容 SSE

**Playwright 路径**:

- 入口: `_handle_playwright_response`
- 通过 `PageController.get_response` 拉取文本，按块输出

---

## 🔐 认证系统

### API 密钥管理

- **存储**: `auth_profiles/key.txt`
- **验证**: Bearer Token 和 X-API-Key 双重支持
- **管理**: Web UI 分级权限查看

### 浏览器认证

- **文件**: `auth_profiles/active/*.json`
- **内容**: 浏览器会话和 Cookie
- **更新**: 通过 `--debug` 模式重新获取

---

## 📊 配置管理

### 优先级

1. **命令行参数** (最高)
2. **环境变量** (`.env` 文件)
3. **默认值** (代码定义)

### config/ 模块

| 文件                      | 职责                                           |
| ------------------------- | ---------------------------------------------- |
| `settings.py`             | 环境变量加载和解析                             |
| `constants.py`            | 系统常量定义                                   |
| `timeouts.py`             | 超时配置                                       |
| `selectors.py`            | CSS 选择器定义                                 |
| `selector_utils.py`       | 选择器工具函数                                 |
| `model_capabilities.json` | 模型能力配置（思考类型、Google Search 支持等） |

> **注意**: `model_capabilities.json` 是外部化的 JSON 配置文件，用于定义各模型的能力参数。
> 当 Google 发布新模型时，只需编辑 JSON 文件，无需修改代码。

---

## 🚀 脚本注入 v3.0

### 工作流程

1. **脚本解析**: 从油猴脚本解析 `MODELS_TO_INJECT` 数组
2. **网络拦截**: Playwright 拦截 `/api/models` 请求
3. **数据合并**: 注入模型添加 `__NETWORK_INJECTED__` 标记
4. **脚本注入**: 脚本注入到页面上下文

### 技术优势

- ✅ **100% 可靠**: Playwright 原生拦截，无时序问题
- ✅ **零维护**: 脚本更新自动生效
- ✅ **完全同步**: 前后端使用相同数据源

---

## 📈 开发工具

| 工具        | 用途              |
| ----------- | ----------------- |
| **Poetry**  | 依赖管理          |
| **Pyright** | 类型检查          |
| **Ruff**    | 代码格式化和 Lint |
| **pytest**  | 测试框架          |

---

## 相关文档

- [开发者指南](development-guide.md) - Poetry、Pyright 工作流程
- [流式处理模式详解](streaming-modes.md) - 三层响应机制详解
- [脚本注入指南](script_injection_guide.md) - 油猴脚本功能
