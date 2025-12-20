# 安装指南

本文档提供基于 Poetry 的详细安装步骤和环境配置说明。

## 🔧 系统要求

### 基础要求

- **Python**: 3.9+ (推荐 3.10+ 或 3.11+)
  - **推荐版本**: Python 3.11+ 以获得最佳性能和兼容性
  - **最低要求**: Python 3.9
  - **完全支持**: Python 3.9, 3.10, 3.11, 3.12, 3.13
- **Poetry**: 1.4+ (现代化 Python 依赖管理工具)
- **Git**: 用于克隆仓库 (推荐)
- **Google AI Studio 账号**: 需能正常访问和使用
- **Node.js**: 18+ (可选，用于前端开发。如不需要，可使用 `--skip-frontend-build` 跳过构建)

### 系统依赖

- **Linux**: `xvfb` (虚拟显示，可选)
  - Debian/Ubuntu: `sudo apt-get update && sudo apt-get install -y xvfb`
  - Fedora: `sudo dnf install -y xorg-x11-server-Xvfb`
- **macOS**: 通常无需额外依赖
- **Windows**: 通常无需额外依赖

## 🚀 快速安装 (推荐)

### 一键安装脚本

```bash
# macOS/Linux 用户
curl -sSL https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.sh | bash

# Windows 用户 (PowerShell)
iwr -useb https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.ps1 | iex
```

## 📋 手动安装步骤

### 1. 安装 Poetry

如果您尚未安装 Poetry，请先安装：

```bash
# macOS/Linux
curl -sSL https://install.python-poetry.org | python3 -

# Windows (PowerShell)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -

# 或使用包管理器
# macOS: brew install poetry
# Ubuntu/Debian: apt install python3-poetry
# Windows: winget install Python.Poetry
```

### 2. 克隆仓库

```bash
git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
cd AIstudioProxyAPI
```

### 3. 安装依赖

Poetry 会自动创建虚拟环境并安装所有依赖：

```bash
# 安装生产依赖
poetry install

# 安装包括开发依赖 (推荐开发者)
poetry install --with dev
```

**Poetry 优势**:

- ✅ 自动创建和管理虚拟环境
- ✅ 依赖解析和版本锁定 (`poetry.lock`)
- ✅ 区分生产依赖和开发依赖
- ✅ 语义化版本控制

### 4. 激活虚拟环境

```bash
# 激活 Poetry 创建的虚拟环境
poetry env activate

# 或者在每个命令前加上 poetry run
poetry run python --version
```

### 5. 下载 Camoufox 浏览器

```bash
# 在 Poetry 环境中下载 Camoufox 浏览器
poetry run camoufox fetch

# 或在激活的环境中
camoufox fetch
```

**关键依赖说明** (由 Poetry 自动管理版本):

- **FastAPI**: 高性能 Web 框架，提供 API 服务
- **Pydantic**: 现代数据验证库
- **Uvicorn**: 高性能 ASGI 服务器
- **Playwright**: 浏览器自动化、页面交互和网络拦截
- **Camoufox**: 反指纹检测浏览器，包含 geoip 数据和增强隐蔽性
- **WebSockets**: 用于实时日志传输、状态监控和 Web UI 通信
- **aiohttp**: 异步 HTTP 客户端
- **python-dotenv**: 环境变量管理

### 6. 安装 Playwright 依赖与浏览器（可选）

虽然 Camoufox 使用自己的 Firefox，但在某些 Linux 发行版上可能需要安装系统依赖，或者开发者可能需要标准 Playwright 浏览器进行调试：

```bash
# 1. 安装系统依赖 (Linux 用户推荐)
poetry run playwright install-deps firefox

# 2. 安装标准 Playwright 浏览器 (仅用于调试或开发)
poetry run playwright install
```

如果 `camoufox fetch` 因网络问题失败，可以尝试运行项目中的 [`fetch_camoufox_data.py`](../fetch_camoufox_data.py) 脚本 (详见[故障排除指南](troubleshooting.md))。

## 🔍 验证安装

### 检查 Poetry 环境

```bash
# 查看 Poetry 环境信息
poetry env info

# 查看已安装的依赖
poetry show

# 检查 Python 版本
poetry run python --version
```

### 检查关键组件

```bash
# 检查 Camoufox
poetry run camoufox --version

# 检查 FastAPI
poetry run python -c "import fastapi; print(f'FastAPI: {fastapi.__version__}')"

# 检查 Playwright
poetry run python -c "import playwright; print('Playwright: OK')"
```

## 🚀 如何启动服务

在您完成安装和环境配置后，强烈建议您先将 `.env.example` 文件复制为 `.env` 并根据您的需求进行修改。这会极大地简化后续的启动命令。

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env  # 或使用其他编辑器
```

完成配置后，您可以选择以下几种方式启动服务：

### 1. 命令行启动 (推荐)

对于熟悉命令行的用户，可以直接使用 `launch_camoufox.py` 脚本启动服务。

```bash
# 启动无头 (headless) 模式，这是服务器部署的常用方式
poetry run python launch_camoufox.py --headless

# 启动调试 (debug) 模式，会显示浏览器界面
poetry run python launch_camoufox.py --debug
```

您可以通过添加不同的参数来控制启动行为，例如：

- `--headless`: 在后台运行浏览器，不显示界面。
- `--debug`: 启动时显示浏览器界面，方便调试。
- 更多参数请参阅[高级配置指南](advanced-configuration.md)。

### 2. Docker 启动

如果您熟悉 Docker，也可以使用容器化方式部署服务。这种方式可以提供更好的环境隔离。

详细的 Docker 启动指南，请参阅：

- **[Docker 部署指南](../docker/README-Docker.md)**

## 多平台指南

### macOS / Linux

- 通常安装过程比较顺利。确保 Python 和 pip 已正确安装并配置在系统 PATH 中。
- 使用 `source venv/bin/activate` 激活虚拟环境 (如果未使用 Poetry shell)。
- `playwright install-deps firefox` 可能需要系统包管理器（如 `apt`, `dnf`, `brew`）安装一些依赖库。如果命令失败，请根据错误提示安装缺失的系统包。
- 防火墙通常不会阻止本地访问，但如果从其他机器访问，需要确保端口（默认 2048）是开放的。
- 对于 Linux 用户，可以考虑使用 `--virtual-display` 标志启动 (需要预先安装 `xvfb`)，它会利用 Xvfb 创建一个虚拟显示环境来运行浏览器，这可能有助于进一步降低被检测的风险。

### Windows

#### 原生 Windows

- 确保在安装 Python 时勾选了 "Add Python to PATH" 选项。
- Windows 防火墙可能会阻止 Uvicorn/FastAPI 监听端口。如果遇到连接问题，请检查防火墙设置。
- `playwright install-deps` 命令在原生 Windows 上作用有限，但运行 `camoufox fetch` 会确保下载正确的浏览器。
- **推荐使用 `python launch_camoufox.py --headless` 启动**。

#### WSL (Windows Subsystem for Linux)

- **推荐**: 对于习惯 Linux 环境的用户，WSL (特别是 WSL2) 提供了更好的体验。
- 在 WSL 环境内，按照 **macOS / Linux** 的步骤进行安装。
- 网络访问注意：
  - 从 Windows 访问 WSL 服务：通常可以通过 `localhost` 访问。
  - 从局域网访问：可能需要配置 Windows 防火墙及 WSL 网络设置。
- 所有命令都应在 WSL 终端内执行。
- 在 WSL 中运行 `--debug` 模式：如果配置了 WSLg 或 X Server，可以看到浏览器界面。否则建议使用无头模式。

## 配置环境变量（推荐）

安装完成后，强烈建议配置 `.env` 文件来简化后续使用：

### 创建配置文件

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env  # 或使用其他编辑器
```

### 基本配置示例

```env
# 服务端口配置
DEFAULT_FASTAPI_PORT=2048
STREAM_PORT=3120

# 代理配置（如需要）
# UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890

# 日志配置
SERVER_LOG_LEVEL=INFO
DEBUG_LOGS_ENABLED=false
```

配置完成后，启动命令将变得非常简单：

```bash
# 简单启动，无需复杂参数
python launch_camoufox.py --headless
```

详细配置说明请参见 [环境变量配置指南](environment-configuration.md)。

## 可选：配置 API 密钥

您也可以选择配置 API 密钥来保护您的服务：

### 创建密钥文件

在 `auth_profiles` 目录中创建 `key.txt` 文件（如果它不存在）：

```bash
# 创建目录和密钥文件
mkdir -p auth_profiles && touch auth_profiles/key.txt

# 添加密钥（每行一个）
echo "your-first-api-key" >> auth_profiles/key.txt
```

### 密钥格式要求

- 每行一个密钥
- 至少 8 个字符
- 支持空行和注释行（以 `#` 开头）
- 使用 UTF-8 编码

### 安全说明

- **无密钥文件**: 服务不需要认证，任何人都可以访问 API
- **有密钥文件**: 所有 API 请求都需要提供有效的密钥
- **密钥保护**: 请妥善保管密钥文件，不要提交到版本控制系统

## 下一步

安装完成后，请参考：

- **[环境变量配置指南](environment-configuration.md)** - ⭐ 推荐先配置
- [首次运行与认证指南](authentication-setup.md)
- [日常运行指南](daily-usage.md)
- [API 使用指南](api-usage.md)
- [故障排除指南](troubleshooting.md)
