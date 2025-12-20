# 平台差异说明

本文档详细说明 AI Studio Proxy API 在不同操作系统（Windows、macOS、Linux）上的差异和注意事项。

---

## 📋 目录

- [通用要求](#通用要求)
- [Windows](#windows)
- [macOS](#macos)
- [Linux](#linux)
- [Docker 环境](#docker-环境)
- [性能对比](#性能对比)

---

## 通用要求

所有平台都需要满足以下基本要求：

- **Python**: >=3.9, <4.0 (推荐 3.10 或 3.11)
- **内存**: 建议 2GB+ 可用内存
- **磁盘**: 至少 1GB 可用空间
- **网络**: 稳定的互联网连接

---

## Windows

### 系统要求

- **操作系统**: Windows 10 或更高版本
- **架构**: x86_64
- **PowerShell**: 5.1 或更高版本（Windows 10 自带）

### 安装 Python

**方法 1: 官方安装包** (推荐)

1. 访问 [python.org](https://www.python.org/downloads/)
2. 下载 Python 3.10+ 的 Windows 安装包
3. 运行安装程序，**勾选 "Add Python to PATH"**
4. 验证安装:
   ```powershell
   python --version
   ```

**方法 2: Windows Store**

```powershell
# 从 Microsoft Store 安装 Python 3.11
# 搜索 "Python 3.11" 并安装
```

**方法 3: Chocolatey**

```powershell
choco install python311
```

### 安装 Poetry

**PowerShell**:

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

**添加 Poetry 到 PATH**:

```powershell
$env:Path += ";$env:APPDATA\Python\Scripts"
```

### 平台特定注意事项

#### 1. 虚拟环境激活

**PowerShell**:

```powershell
# Poetry Shell
poetry shell

# 或使用 poetry run
poetry run python launch_camoufox.py --headless
```

**CMD**:

```cmd
poetry shell
```

#### 2. 路径分隔符

Windows 使用反斜杠 `\`，但 Python 代码中使用 `/` 或 `os.path.join()` 自动处理。

**配置文件路径**:

```env
# .env 文件中使用正斜杠或双反斜杠
USERSCRIPT_PATH=browser_utils/more_models.js
# 或
USERSCRIPT_PATH=browser_utils\\more_models.js
```

#### 3. uvloop 不可用

uvloop 只支持 Linux 和 macOS，但项目已自动处理：

```python
# pyproject.toml 中已配置
uvloop = {version = "*", markers = "sys_platform != 'win32'"}
```

Windows 上会自动使用标准的 asyncio 事件循环，功能完全正常。

#### 4. 端口占用检查

```powershell
# 检查端口占用
netstat -ano | findstr 2048

# 结束进程
taskkill /PID <进程ID> /F
```

#### 5. 防火墙配置

首次运行可能需要允许 Python 通过防火墙：

1. Windows 防火墙会弹出提示
2. 选择 "允许访问"
3. 或手动添加规则：
   - 打开 "Windows Defender 防火墙"
   - 点击 "允许应用通过防火墙"
   - 添加 Python 和 Poetry

#### 6. 长路径支持

如果遇到路径长度限制：

1. 打开注册表编辑器 (regedit)
2. 导航到: `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`
3. 设置 `LongPathsEnabled` 为 `1`
4. 重启计算机

#### 7. 时区支持 (tzdata)

Windows 不像 Linux/macOS 那样内置 IANA 时区数据库。本项目依赖 `tzdata` 包来提供时区支持。

- **自动安装**: Poetry 会根据 `pyproject.toml` 自动安装 `tzdata`。
- **故障排除**: 如果遇到 `ZoneInfoNotFoundError` 错误，请检查 `tzdata` 是否已安装：
  ```powershell
  poetry run pip show tzdata
  ```

### 推荐终端

- **Windows Terminal** (推荐): 现代化、支持多标签页
- **PowerShell 7+**: 跨平台，功能强大
- **Git Bash**: 类 Unix 环境

### 常见问题

**问题**: `poetry` 命令未找到

**解决方案**:

```powershell
# 检查 Poetry 安装路径
$env:APPDATA\Python\Scripts\poetry --version

# 添加到 PATH
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$env:APPDATA\Python\Scripts", "User")
```

**问题**: SSL 证书错误

**解决方案**:

```powershell
# 临时禁用 SSL 验证（不推荐用于生产环境）
$env:PYTHONHTTPSVERIFY = "0"

# 或安装证书
pip install --upgrade certifi
```

---

## macOS

### 系统要求

- **操作系统**: macOS 10.15 (Catalina) 或更高版本
- **架构**: x86_64 或 ARM64 (Apple Silicon)
- **Xcode Command Line Tools**: 自动安装或手动安装

### 安装 Python

**方法 1: Homebrew** (推荐)

```bash
# 安装 Homebrew (如果尚未安装)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python 3.11
brew install python@3.11

# 验证安装
python3 --version
```

**方法 2: pyenv** (推荐开发者)

```bash
# 安装 pyenv
brew install pyenv

# 安装 Python 3.11
pyenv install 3.11

# 设置全局版本
pyenv global 3.11

# 验证
python --version
```

**方法 3: 官方安装包**

1. 访问 [python.org](https://www.python.org/downloads/)
2. 下载 macOS 通用安装包
3. 运行 `.pkg` 文件安装

### 安装 Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -

# 或使用 Homebrew
brew install poetry
```

### 平台特定注意事项

#### 1. Apple Silicon (M1/M2/M3)

大多数依赖已支持 ARM64 架构，但可能需要 Rosetta 2：

```bash
# 安装 Rosetta 2 (如果需要)
softwareupdate --install-rosetta
```

**确认架构**:

```bash
# 查看 Python 架构
python3 -c "import platform; print(platform.machine())"
# arm64 = Apple Silicon 原生
# x86_64 = Intel 或 Rosetta 2
```

**使用 x86_64 版本** (如果遇到兼容性问题):

```bash
# 在 Rosetta 2 下运行
arch -x86_64 python3 script.py
```

#### 2. 权限问题

macOS 需要授予终端权限：

```bash
# 如果遇到 "Operation not permitted" 错误
# 打开 "系统偏好设置" -> "安全性与隐私" -> "隐私" -> "完全磁盘访问权限"
# 添加 "终端" 或 "iTerm"
```

#### 3. 证书问题

```bash
# 安装 macOS 证书
/Applications/Python\ 3.11/Install\ Certificates.command

# 或手动安装
pip install --upgrade certifi
```

#### 4. 虚拟显示 (可选)

macOS 默认有图形界面，但如果需要虚拟显示：

```bash
# 安装 Xvfb (通过 XQuartz)
brew install --cask xquartz

# 重启后使用
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

#### 5. 端口占用检查

```bash
# 查看端口占用
lsof -i :2048

# 结束进程
kill -9 <PID>
```

### 推荐终端

- **iTerm2** (推荐): 功能强大、可定制
- **Terminal.app**: 系统自带，简单够用
- **Warp**: 现代化、AI 辅助

### 常见问题

**问题**: `command not found: poetry`

**解决方案**:

```bash
# 添加 Poetry 到 PATH
export PATH="$HOME/.local/bin:$PATH"

# 永久添加 (zsh)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 永久添加 (bash)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bash_profile
source ~/.bash_profile
```

**问题**: SSL 证书错误

**解决方案**:

```bash
# 安装证书
/Applications/Python\ 3.11/Install\ Certificates.command
```

---

## Linux

### 系统要求

- **发行版**: Ubuntu 20.04+, Debian 11+, Fedora 35+, Arch Linux 等
- **架构**: x86_64 或 ARM64
- **依赖**: 根据发行版而定

### 安装 Python

**Ubuntu/Debian**:

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev
```

**Fedora**:

```bash
sudo dnf install python3.11 python3.11-devel
```

**Arch Linux**:

```bash
sudo pacman -S python
```

### 安装 Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -

# 或使用包管理器
# Ubuntu/Debian
sudo apt install python3-poetry

# Fedora
sudo dnf install poetry

# Arch Linux
sudo pacman -S python-poetry
```

### 安装系统依赖

#### Ubuntu/Debian

```bash
# 安装 Playwright 依赖
sudo apt-get update
sudo apt-get install -y \
    libgbm-dev \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2

# 或使用 Playwright 自动安装
playwright install-deps
```

#### Fedora

```bash
sudo dnf install -y \
    nss \
    alsa-lib \
    at-spi2-atk \
    cups-libs \
    gtk3 \
    libdrm \
    libgbm \
    libxkbcommon \
    mesa-libgbm
```

#### Arch Linux

```bash
sudo pacman -S \
    nss \
    alsa-lib \
    at-spi2-core \
    cups \
    libdrm \
    libxkbcommon \
    mesa
```

### 平台特定注意事项

#### 1. 虚拟显示模式

无图形界面的服务器需要虚拟显示：

```bash
# 安装 Xvfb
# Ubuntu/Debian
sudo apt-get install xvfb

# Fedora
sudo dnf install xorg-x11-server-Xvfb

# Arch Linux
sudo pacman -S xorg-server-xvfb

# 启动服务时使用虚拟显示模式
python launch_camoufox.py --virtual-display
```

#### 2. 无头模式 (推荐)

```bash
# 无需 X Server，完全后台运行
python launch_camoufox.py --headless
```

#### 3. 权限问题

```bash
# 确保当前用户有权限访问必要的目录
chmod -R 755 ~/AIstudioProxyAPI

# 如果需要绑定特权端口 (<1024)
sudo setcap 'cap_net_bind_service=+ep' $(which python3)
```

#### 4. 防火墙配置

**Ubuntu/Debian (ufw)**:

```bash
sudo ufw allow 2048/tcp
sudo ufw allow 3120/tcp
sudo ufw reload
```

**Fedora/RHEL (firewalld)**:

```bash
sudo firewall-cmd --permanent --add-port=2048/tcp
sudo firewall-cmd --permanent --add-port=3120/tcp
sudo firewall-cmd --reload
```

**iptables**:

```bash
sudo iptables -A INPUT -p tcp --dport 2048 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3120 -j ACCEPT
sudo iptables-save
```

#### 5. systemd 服务 (常驻运行)

创建 `/etc/systemd/system/aistudio-proxy.service`:

```ini
[Unit]
Description=AI Studio Proxy API
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/AIstudioProxyAPI
Environment="PATH=/path/to/poetry/env/bin"
ExecStart=/path/to/poetry/env/bin/python launch_camoufox.py --headless
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**启用服务**:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aistudio-proxy
sudo systemctl start aistudio-proxy
sudo systemctl status aistudio-proxy
```

#### 6. SELinux (Fedora/RHEL)

如果启用了 SELinux：

```bash
# 临时设置为 permissive 模式
sudo setenforce 0

# 或创建自定义策略
# (需要 SELinux 管理知识)
```

### 推荐终端

- **GNOME Terminal**: GNOME 桌面默认
- **Konsole**: KDE Plasma 默认
- **tmux**: 终端复用器，适合远程服务器
- **Terminator**: 支持分屏

### 常见问题

**问题**: `libgbm.so.1: cannot open shared object file`

**解决方案**:

```bash
sudo apt-get install libgbm1
# 或
sudo dnf install libgbm
```

**问题**: Playwright 浏览器安装失败

**解决方案**:

```bash
# 使用 Playwright 自动安装依赖
playwright install-deps

# 手动安装浏览器
playwright install firefox
```

---

## Docker 环境

### 支持的平台

- **x86_64**: 完全支持
- **ARM64**: 完全支持（包括 Apple Silicon）

### 快速启动

```bash
cd docker
cp .env.docker .env
nano .env  # 编辑配置
docker compose up -d
```

### 平台差异

#### Linux (原生)

- ✅ 最佳性能
- ✅ 完全支持所有功能
- ✅ 资源占用最低

#### macOS (Docker Desktop)

- ✅ 支持所有功能
- ⚠️ 性能略低于原生 Linux
- ⚠️ 资源占用较高（虚拟机开销）
- 💡 **提示**: 分配足够的内存和 CPU

**Docker Desktop 配置**:

- 内存: 至少 4GB
- CPU: 至少 2 核

#### Windows (Docker Desktop)

- ✅ 支持所有功能
- ⚠️ 需要 WSL 2 后端
- ⚠️ 性能略低于 Linux
- 💡 **提示**: 确保启用 WSL 2

**WSL 2 配置**:

```bash
# 检查 WSL 版本
wsl --list --verbose

# 如果使用 WSL 1，升级到 WSL 2
wsl --set-version Ubuntu 2
wsl --set-default-version 2
```

### 认证文件挂载

所有平台都需要在主机上获取认证文件后挂载：

```yaml
# docker-compose.yml
volumes:
  - ./auth_profiles:/app/auth_profiles
```

**步骤**:

1. 在主机上运行调试模式获取认证。
2. 确保 `auth_profiles` 目录（包含 `active/` 子目录）已正确挂载到容器。
3. 重启容器。

---

## 性能概览

不同平台的性能表现会有所差异，主要取决于底层架构和虚拟化开销：

1.  **Linux (原生)**: 通常提供最佳性能和最低延迟，受益于 `uvloop` 支持和高效的进程管理。
2.  **macOS**: 性能良好，Apple Silicon 芯片表现优异。
3.  **Windows**: 由于缺乏 `uvloop` 支持以及文件系统差异，性能略低于 Linux/macOS，但完全满足日常使用。
4.  **Docker**:
    - **Linux**: 性能接近原生。
    - **macOS/Windows**: 由于 Docker Desktop 使用虚拟机，会有额外的 CPU 和内存开销，启动时间和响应延迟可能略高。

---

## 推荐配置

### 开发环境

- **首选**: macOS 或 Linux (原生)
- **备选**: Windows 10/11 (原生)
- **不推荐**: Docker (除非需要隔离)

### 生产环境

- **首选**: Linux (原生或 Docker)
- **备选**: Docker (跨平台部署)
- **不推荐**: Windows Server (性能和兼容性问题)

### 测试环境

- **首选**: Docker (一致性)
- **备选**: 虚拟机

---

## 相关文档

- [快速开始指南](quick-start-guide.md) - 快速部署
- [安装指南](installation-guide.md) - 详细安装步骤
- [Docker 部署指南](../docker/README-Docker.md) - Docker 部署
- [故障排除指南](troubleshooting.md) - 平台特定问题

---

如有平台特定问题，请查看故障排除指南或提交 Issue。
