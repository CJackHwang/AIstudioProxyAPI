# 开发者指南

本文档面向希望参与项目开发、贡献代码或深度定制功能的开发者。

## 🛠️ 开发环境设置

### 前置要求

- **Python**: ≥3.9, <4.0 (推荐 3.10+)
- **Poetry**: 依赖管理工具
- **Node.js**: ≥18 (用于前端开发，可选)
- **Git**: 版本控制

> **提示**: 如果不进行前端开发，可以使用 `--skip-frontend-build` 或设置 `SKIP_FRONTEND_BUILD=1` 跳过前端构建。

### 快速开始

```bash
# 克隆项目
git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
cd AIstudioProxyAPI

# 安装 Poetry
curl -sSL https://install.python-poetry.org | python3 -

# 安装依赖 (包括开发依赖)
poetry install --with dev

# 激活虚拟环境
poetry shell
```

---

## 📁 项目结构

> 详细架构说明请参阅 [项目架构指南](architecture-guide.md)

```
AIstudioProxyAPI/
├── api_utils/              # FastAPI 应用核心
│   ├── app.py             # 应用入口
│   ├── routers/           # API 路由 (chat, health, models 等)
│   ├── request_processor.py
│   └── queue_worker.py
├── browser_utils/          # 浏览器自动化
│   ├── page_controller.py
│   ├── page_controller_modules/  # Mixin 子模块
│   ├── initialization/    # 初始化模块
│   └── operations_modules/ # 操作子模块
├── launcher/               # 启动器模块
├── config/                 # 配置管理
├── models/                 # 数据模型
├── stream/                 # 流式代理
├── logging_utils/          # 日志工具
├── tests/                  # 测试目录
├── pyproject.toml         # Poetry 配置
└── pyrightconfig.json     # Pyright 配置
```

---

## 🔧 依赖管理 (Poetry)

### 常用命令

```bash
# 查看依赖树
poetry show --tree

# 添加依赖
poetry add package_name
poetry add --group dev package_name  # 开发依赖

# 更新依赖
poetry update

# 导出 requirements.txt
poetry export -f requirements.txt --output requirements.txt
```

### 虚拟环境

```bash
# 查看环境信息
poetry env info

# 激活环境
poetry shell

# 运行命令
poetry run python script.py
```

---

## 🎨 前端开发 (React)

前端使用 React + Vite + TypeScript 构建。

### 开发模式

```bash
cd static/frontend

# 安装依赖
npm install

# 开发服务器 (热重载)
npm run dev

# 构建生产版本
npm run build

# 运行测试
npm run test
```

### 跳过前端构建

如果只进行后端开发，可以跳过前端构建：

```bash
# 命令行方式
python -m launcher.runner --skip-frontend-build

# 环境变量方式
SKIP_FRONTEND_BUILD=1 python -m launcher.runner
```

### 配置文件

| 文件                               | 用途            |
| ---------------------------------- | --------------- |
| `static/frontend/package.json`     | 依赖和脚本配置  |
| `static/frontend/vite.config.ts`   | Vite 构建配置   |
| `static/frontend/tsconfig.json`    | TypeScript 配置 |
| `static/frontend/vitest.config.ts` | Vitest 测试配置 |

---

## 🔍 类型检查 (Pyright)

项目使用 Pyright 进行类型检查。

### 运行检查

```bash
# 检查整个项目
pyright

# 检查特定文件
pyright api_utils/app.py

# 监视模式
pyright --watch
```

### 配置

`pyrightconfig.json`:

```json
{
  "pythonVersion": "3.13",
  "typeCheckingMode": "off",
  "extraPaths": ["./api_utils", "./browser_utils", "./config", ...]
}
```

---

## 🧪 测试

### ⚠️ 防挂起协议

项目严格执行防挂起协议：

1. **强制超时**: 全局 `timeout = 120` (在 `pyproject.toml`)
2. **资源清理**: Fixtures 必须在 `yield` 后关闭资源
3. **Async 安全**: 禁止吞掉 `asyncio.CancelledError`

### 运行测试

```bash
# 运行所有测试
poetry run pytest

# 运行特定测试
poetry run pytest tests/test_api.py

# 覆盖率报告
poetry run pytest --cov=api_utils --cov-report=html
```

---

## 🔄 开发工作流程

### 1. 代码格式化

```bash
# Ruff 格式化和 Lint
poetry run ruff check .
poetry run ruff format .
```

### 2. 类型检查

```bash
pyright
```

### 3. 运行测试

```bash
poetry run pytest
```

### 4. 提交代码

```bash
git add .
git commit -m "feat: 添加新功能"
git push origin feature-branch
```

---

## 📝 代码规范

### 命名规范

| 类型   | 规范         | 示例                   |
| ------ | ------------ | ---------------------- |
| 文件名 | `snake_case` | `request_processor.py` |
| 类名   | `PascalCase` | `QueueManager`         |
| 函数名 | `snake_case` | `process_request`      |
| 常量   | `UPPER_CASE` | `DEFAULT_PORT`         |

### 文档字符串

```python
def process_request(request: ChatRequest) -> ChatResponse:
    """
    处理聊天请求

    Args:
        request: 聊天请求对象

    Returns:
        ChatResponse: 聊天响应对象

    Raises:
        ValidationError: 当请求数据无效时
    """
    pass
```

---

## 🧭 新增端点规范

1. 在 `api_utils/routers/` 下创建对应模块
2. 在 `api_utils/routers/__init__.py` 中重导出
3. 使用 `api_utils.error_utils` 构造错误
4. 环境变量使用 `config.get_environment_variable`

### 错误码规范

| 错误码 | 场景                 |
| ------ | -------------------- |
| 499    | 客户端断开/取消      |
| 502    | 上游/Playwright 失败 |
| 503    | 服务不可用           |
| 504    | 处理超时             |

---

## 🤝 贡献指南

### 提交 Pull Request

1. Fork 项目
2. 创建分支: `git checkout -b feature/amazing-feature`
3. 提交: `git commit -m 'feat: 添加功能'`
4. 推送: `git push origin feature/amazing-feature`
5. 创建 Pull Request

### 代码审查清单

- [ ] 代码遵循项目规范
- [ ] 添加了必要测试
- [ ] 测试通过
- [ ] 类型检查通过
- [ ] 文档已更新

---

## 🔗 相关资源

- [Poetry 文档](https://python-poetry.org/docs/)
- [Pyright 文档](https://github.com/microsoft/pyright)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Playwright 文档](https://playwright.dev/python/)
