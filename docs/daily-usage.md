# 日常运行指南

本指南介绍如何在完成首次认证设置后进行日常运行。项目提供了多种启动方式，推荐使用基于 `.env` 配置文件的简化启动方式。

## 概述

完成首次认证设置后，您可以选择以下方式进行日常运行：

- **命令行启动**: 直接使用 [`launch_camoufox.py`](../launch_camoufox.py) 命令行工具
- **Docker 部署**: 使用容器化部署方式

## ⭐ 简化启动方式（推荐）

**基于 `.env` 配置文件的统一配置管理，启动变得极其简单！**

### 配置优势

- ✅ **一次配置，终身受益**: 配置好 `.env` 文件后，启动命令极其简洁
- ✅ **版本更新无忧**: `git pull` 后无需重新配置，直接启动
- ✅ **参数集中管理**: 所有配置项统一在 `.env` 文件中
- ✅ **环境隔离**: 不同环境可使用不同的配置文件

### 基本启动（推荐）

```bash
# 命令行启动（推荐日常使用）
python launch_camoufox.py --headless

# 调试模式（首次设置或故障排除）
python launch_camoufox.py --debug
```

**就这么简单！** 所有配置都在 `.env` 文件中预设好了，无需复杂的命令行参数。

## 启动器说明

### 关于 `--virtual-display` (Linux 虚拟显示无头模式)

- **为什么使用?** 与标准的无头模式相比，虚拟显示模式通过创建一个完整的虚拟 X 服务器环境 (Xvfb) 来运行浏览器。这可以模拟一个更真实的桌面环境，从而可能进一步降低被网站检测为自动化脚本或机器人的风险，特别适用于对反指纹和反检测有更高要求的场景，同时确保无桌面的环境下能正常运行服务
- **什么时候使用?** 当您在 Linux 环境下运行，并且希望以无头模式操作。
- **如何使用?**
  1. 确保您的 Linux 系统已安装 `xvfb` (参见 [安装指南](installation-guide.md) 中的安装说明)。
  2. 在运行 [`launch_camoufox.py`](../launch_camoufox.py) 时添加 `--virtual-display` 标志。例如:
     ```bash
     python launch_camoufox.py --virtual-display --server-port 2048 --stream-port 3120 --internal-camoufox-proxy ''
     ```

## 代理配置优先级

项目采用统一的代理配置管理系统，按以下优先级顺序确定代理设置：

1. **`--internal-camoufox-proxy` 命令行参数** (最高优先级)
   - 明确指定代理：`--internal-camoufox-proxy 'http://127.0.0.1:7890'`
   - 明确禁用代理：`--internal-camoufox-proxy ''`
2. **`UNIFIED_PROXY_CONFIG` 环境变量** (推荐，.env 文件配置)
3. **`HTTP_PROXY` 环境变量**
4. **`HTTPS_PROXY` 环境变量**
5. **系统代理设置** (Linux 下的 gsettings，最低优先级)

**推荐配置方式**:

```env
# .env 文件中统一配置代理
UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890
# 或禁用代理
UNIFIED_PROXY_CONFIG=
```

**重要说明**：此代理配置会同时应用于 Camoufox 浏览器和流式代理服务的上游连接，确保整个系统的代理行为一致。

## 三层响应获取机制配置

项目采用三层响应获取机制，确保高可用性和最佳性能。详细说明请参见 [流式处理模式详解](streaming-modes.md)。

### 模式 1: 优先使用集成的流式代理 (默认推荐)

**使用 `.env` 配置（推荐）:**

```env
# 在 .env 文件中配置
STREAM_PORT=3120
UNIFIED_PROXY_CONFIG=http://127.0.0.1:7890  # 如需代理
```

```bash
# 然后简单启动
python launch_camoufox.py --headless
```

**命令行覆盖（高级用户）:**

```bash
# 使用自定义流式代理端口
python launch_camoufox.py --headless --stream-port 3125

# 启用代理配置
python launch_camoufox.py --headless --internal-camoufox-proxy 'http://127.0.0.1:7890'

# 明确禁用代理（覆盖 .env 中的设置）
python launch_camoufox.py --headless --internal-camoufox-proxy ''
```

在此模式下，主服务器会优先尝试通过端口 `3120` (或 `.env` 中配置的 `STREAM_PORT`) 上的集成流式代理获取响应。如果失败，则回退到 Playwright 页面交互。

### 模式 2: 优先使用外部 Helper 服务 (禁用集成流式代理)

**使用 `.env` 配置（推荐）:**

```bash
# 在 .env 文件中配置
STREAM_PORT=0  # 禁用集成流式代理
GUI_DEFAULT_HELPER_ENDPOINT=http://your-helper-service.com/api/getStreamResponse

# 然后简单启动
python launch_camoufox.py --headless
```

**命令行覆盖（高级用户）:**

```bash
# 外部 Helper 模式
python launch_camoufox.py --headless --stream-port 0 --helper 'http://your-helper-service.com/api/getStreamResponse'
```

在此模式下，主服务器会优先尝试通过 Helper 端点获取响应 (需要有效的 `auth_profiles/active/*.json` 以提取 `SAPISID`)。如果失败，则回退到 Playwright 页面交互。

### 模式 3: 仅使用 Playwright 页面交互 (禁用所有流式代理和 Helper)

**使用 `.env` 配置（推荐）:**

```bash
# 在 .env 文件中配置
STREAM_PORT=0  # 禁用集成流式代理
GUI_DEFAULT_HELPER_ENDPOINT=  # 禁用 Helper 服务

# 然后简单启动
python launch_camoufox.py --headless
```

**命令行覆盖（高级用户）:**

```bash
# 纯 Playwright 模式
python launch_camoufox.py --headless --stream-port 0 --helper ''
```

在此模式下，主服务器将仅通过 Playwright 与 AI Studio 页面交互 (模拟点击"编辑"或"复制"按钮) 来获取响应。这是传统的后备方法。

## 图形界面启动器 (已废弃)

> [!WARNING]
> GUI 启动器 (`gui_launcher.py`) 已移至 `deprecated/` 目录。推荐使用命令行方式 `python launch_camoufox.py`。

项目曾提供一个基于 Tkinter 的图形用户界面 (GUI) 启动器，但现已废弃。

该工具的功能可通过以下命令行改写实现：

- **有头模式**: `python launch_camoufox.py --debug`
- **无头模式**: `python launch_camoufox.py --headless`

### 使用建议

- **首次运行**: 使用 `python launch_camoufox.py --debug` 并手动完成登录
- **日常后台运行**: `python launch_camoufox.py --headless`
- **故障排查**: 使用 `--debug` 模式观察浏览器行为

## 重要注意事项

### 配置优先级

1. **`.env` 文件配置** - 推荐的配置方式，一次设置长期使用
2. **命令行参数** - 可以覆盖 `.env` 文件中的设置，适用于临时调整
3. **环境变量** - 最低优先级，主要用于系统级配置

### 使用建议

- **日常使用**: 配置好 `.env` 文件后，使用简单的 `python launch_camoufox.py --headless` 即可
- **临时调整**: 需要临时修改配置时，使用命令行参数覆盖，无需修改 `.env` 文件
- **首次设置**: 推荐使用 GUI 的"创建新认证文件"功能，或者使用 `python launch_camoufox.py --debug` 手动设置

**只有当你确认使用调试模式一切运行正常（特别是浏览器内的登录和认证保存），并且 `auth_profiles/active/` 目录下有有效的认证文件后，才推荐使用无头模式作为日常后台运行的标准方式。**

## 下一步

日常运行设置完成后，请参考：

- [API 使用指南](api-usage.md)
- [Web UI 使用指南](webui-guide.md)
- [故障排除指南](troubleshooting.md)
