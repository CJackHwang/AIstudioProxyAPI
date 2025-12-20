# 快速开始指南

本指南将帮助您快速部署和运行 AI Studio Proxy API，适合新用户快速上手。

---

## 🎯 目标

完成本指南后，您将能够：

- ✅ 在本地成功运行 AI Studio Proxy API 服务器
- ✅ 通过 OpenAI 兼容的 API 访问 Google AI Studio
- ✅ 使用内置 Web UI 进行测试
- ✅ 了解基本配置和故障排查

**预计时间**: 15-30 分钟

---

## 📋 前置条件

在开始之前，请确保您的系统满足以下要求：

- ✅ **Python 3.9+** (推荐 3.10 或 3.11)
- ✅ **稳定的互联网连接** (访问 Google AI Studio)
- ✅ **2GB+ 可用内存**
- ✅ **Google 账号** (用于访问 AI Studio)

### 检查 Python 版本

```bash
python --version
# 或
python3 --version
```

如果版本低于 3.9，请先升级 Python。

---

## 🚀 方式一：一键安装（推荐新手）

### macOS / Linux

```bash
# 下载并执行安装脚本
curl -sSL https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.sh | bash

# 进入项目目录
cd AIstudioProxyAPI

# 跳到"配置服务"步骤
```

### Windows (PowerShell)

```powershell
# 下载并执行安装脚本
iwr -useb https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.ps1 | iex

# 进入项目目录
cd AIstudioProxyAPI

# 跳到"配置服务"步骤
```

---

## 📦 方式二：手动安装

### 步骤 1: 安装 Poetry

**Poetry** 是现代化的 Python 依赖管理工具，项目使用它管理所有依赖。

#### macOS / Linux

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

#### Windows (PowerShell)

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

#### 使用包管理器（可选）

```bash
# macOS (Homebrew)
brew install poetry

# Ubuntu/Debian
apt install python3-poetry

# Fedora
dnf install poetry
```

**验证安装**:

```bash
poetry --version
```

### 步骤 2: 克隆项目

```bash
git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
cd AIstudioProxyAPI
```

### 步骤 3: 安装依赖

```bash
# Poetry 会自动创建虚拟环境并安装所有依赖
poetry install
```

这个过程可能需要几分钟，请耐心等待。

### 步骤 4: 激活虚拟环境

有两种方式激活虚拟环境：

**方式 A: 进入 Shell (推荐日常使用)**

```bash
poetry shell
```

激活后，您的命令提示符会显示虚拟环境名称。

**方式 B: 使用 `poetry run` (推荐自动化)**

```bash
# 每次运行命令时加上 poetry run 前缀
poetry run python launch_camoufox.py --headless
```

---

## ⚙️ 配置服务

### 步骤 1: 创建配置文件

```bash
# 复制配置模板
cp .env.example .env
```

### 步骤 2: 编辑配置 (可选)

```bash
# 使用您喜欢的编辑器
nano .env
# 或
code .env
# 或
vim .env
```

**基本配置示例**:

```env
# 服务端口（默认 2048）
PORT=2048

# 流式代理端口（默认 3120，设为 0 禁用）
STREAM_PORT=3120

# 代理配置（如果需要）
UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890

# 日志级别（DEBUG, INFO, WARNING, ERROR）
SERVER_LOG_LEVEL=INFO
```

**💡 提示**: 首次运行可以使用默认配置，稍后根据需要调整。

---

## 🔐 首次认证

首次运行需要进行 Google 账号认证，获取访问 AI Studio 所需的 Cookie。

### 使用调试模式认证

```bash
# 启动调试模式（会打开浏览器窗口）
poetry run python launch_camoufox.py --debug
```

### 认证步骤

1. **浏览器窗口打开** - Camoufox 浏览器会自动打开
2. **登录 Google 账号** - 在浏览器中登录您的 Google 账号
3. **访问 AI Studio** - 浏览器会自动导航到 AI Studio 页面
4. **等待保存** - 认证信息会自动保存到 `auth_profiles/active/` 目录
5. **查看日志** - 终端会显示认证文件保存成功的消息

**成功标志**:

```
✅ 认证文件已保存到: auth_profiles/active/XXXXXXXX.json
```

### 关闭调试模式

认证完成后，按 `Ctrl+C` 停止调试模式服务器。

---

## 🎮 日常运行

认证完成后，您有多种方式启动服务：

### 方式 1: 命令行启动（推荐）

**无头模式**（推荐，后台运行浏览器）:

```bash
poetry run python launch_camoufox.py --headless
```

**普通模式**（显示浏览器窗口）:

```bash
poetry run python launch_camoufox.py
```

**虚拟显示模式**（Linux 无显示环境）:

```bash
poetry run python launch_camoufox.py --virtual-display
```

### 方式 2: 直接启动 FastAPI (开发调试)

```bash
# 仅启动 API 服务器（不启动浏览器）
poetry run python -m uvicorn server:app --host 0.0.0.0 --port 2048
```

**注意**: 这种方式需要手动配置 `CAMOUFOX_WS_ENDPOINT` 环境变量。

---

## 🧪 测试服务

### 1. 健康检查

打开浏览器或使用 `curl`:

```bash
# 检查服务状态
curl http://127.0.0.1:2048/health

# 预期输出（成功）
{
  "status": "OK",
  "message": "服务运行中;队列长度: 0。",
  "details": {
    "isPlaywrightReady": true,
    "isBrowserConnected": true,
    "isPageReady": true,
    "workerRunning": true,
    "queueLength": 0
  }
}
```

### 2. 查看模型列表

```bash
curl http://127.0.0.1:2048/v1/models

# 预期输出
{
  "object": "list",
  "data": [
    {
      "id": "gemini-1.5-pro",
      "object": "model",
      "created": 1699999999,
      "owned_by": "google"
    },
    ...
  ]
}
```

### 3. 测试聊天接口

**非流式请求**:

```bash
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-1.5-pro",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": false
  }'
```

**流式请求**:

```bash
curl -X POST http://127.0.0.1:2048/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-1.5-pro",
    "messages": [
      {"role": "user", "content": "Tell me a short story"}
    ],
    "stream": true
  }' --no-buffer
```

### 4. 使用内置 Web UI

打开浏览器访问:

```
http://127.0.0.1:2048
```

**Web UI 功能**:

- 💬 实时聊天测试
- 📊 服务状态监控
- 🔑 API 密钥管理
- 📝 实时日志查看

---

## 🔧 常见问题

### 问题 1: 端口被占用

**错误信息**:

```
Error: Address already in use
```

**解决方案**:

```bash
# 查找占用端口的进程
# Windows
netstat -ano | findstr 2048

# macOS/Linux
lsof -i :2048

# 修改 .env 文件使用其他端口
PORT=3048
```

### 问题 2: 认证文件过期

**现象**: 服务启动后无法访问 AI Studio，日志显示认证错误。

**解决方案**:

```bash
# 1. 删除旧的认证文件
rm -rf auth_profiles/active/*.json

# 2. 重新运行调试模式认证
poetry run python launch_camoufox.py --debug

# 3. 重新登录 Google 账号
```

### 问题 3: 无法安装 Camoufox

**错误信息**:

```
Error downloading Camoufox binary
```

**解决方案**:

```bash
# 方案 A: 使用项目提供的下载脚本
poetry run python fetch_camoufox_data.py

# 方案 B: 手动下载（需要代理）
export HTTPS_PROXY=http://127.0.0.1:7890
poetry run camoufox fetch

# 方案 C: 使用不带 geoip 的版本
pip install camoufox --no-deps
```

### 问题 4: Playwright 依赖缺失（Linux）

**错误信息**:

```
Error: libgbm-dev not found
```

**解决方案**:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y libgbm-dev libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2

# 或使用 Playwright 自动安装
playwright install-deps
```

### 问题 5: 模型列表为空

**现象**: `/v1/models` 返回空列表或只有默认模型。

**解决方案**:

```bash
# 1. 检查服务状态
curl http://127.0.0.1:2048/health

# 2. 查看日志
tail -f logs/app.log

# 3. 检查认证文件
ls -la auth_profiles/active/

# 4. 等待服务完全启动（可能需要 30-60 秒）
```

---

## 📚 下一步

恭喜！您已经成功运行了 AI Studio Proxy API。

### 推荐阅读

1. **[环境变量配置指南](environment-configuration.md)** - 了解所有配置选项
2. **[API 使用指南](api-usage.md)** - 学习如何使用 API
3. **[OpenAI 兼容性说明](openai-compatibility.md)** - 了解与 OpenAI API 的差异
4. **[Web UI 使用指南](webui-guide.md)** - 探索 Web UI 功能

### 高级话题

- **[Docker 部署](../docker/README-Docker.md)** - 使用 Docker 容器化部署
- **[流式处理模式详解](streaming-modes.md)** - 理解三层响应获取机制
- **[高级配置](advanced-configuration.md)** - 性能优化和高级功能
- **[故障排除指南](troubleshooting.md)** - 更多问题解决方案

---

## 🆘 获取帮助

如果遇到问题，可以：

1. **查看文档** - 本项目包含详细的文档
2. **查看日志** - `logs/app.log` 包含详细的运行日志
3. **检查快照** - `errors_py/` 目录包含错误时的页面快照
4. **提交 Issue** - [GitHub Issues](https://github.com/CJackHwang/AIstudioProxyAPI/issues)
5. **社区讨论** - [Linux.do 社区](https://linux.do/)

---

## 🎉 成功运行检查清单

- [ ] 服务成功启动，无错误日志
- [ ] `/health` 端点返回 `"status": "OK"`
- [ ] `/v1/models` 返回模型列表
- [ ] 成功完成一次聊天请求（非流式）
- [ ] 成功完成一次聊天请求（流式）
- [ ] Web UI 可以正常访问
- [ ] 能够查看实时日志

全部勾选？🎊 恭喜您已经掌握了基本用法！

---

祝您使用愉快！如有问题，欢迎反馈。
