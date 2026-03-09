# 部署与运维指南

本文档聚焦“可落地部署”和“稳定运行”两件事：

- 本机/服务器长期运行
- Docker 部署与升级
- 日常运维检查与常见操作

---

## 1. 部署模式选择

### 模式 A：直接运行（推荐调试、灵活控制）

适合：首次接入、需要手动登录、需要快速排障。

核心命令：

```bash
poetry run python launch_camoufox.py --debug
poetry run python launch_camoufox.py --headless
```

### 模式 B：Docker（推荐稳定托管）

适合：长期驻留、标准化部署、跨机器迁移。

核心命令：

```bash
cd docker
docker compose up -d --build
```

---

## 2. 直接运行：生产化建议

## 2.1 必要目录与文件

确保以下目录存在（程序会自动创建，但建议提前理解结构）：

- `auth_profiles/active/`：当前启用认证
- `auth_profiles/saved/`：可切换认证池
- `auth_profiles/emergency/`：紧急认证池
- `logs/`：应用日志

## 2.2 启动参数建议

- 首次登录：`--debug`
- 日常运行：`--headless`
- 无 GUI Linux：`--virtual-display`
- 关闭流代理：`--stream-port 0`
- 指定端口：`--server-port 2048 --stream-port 3120`

## 2.3 systemd（Linux）示例

可使用如下服务文件（示例路径 `/etc/systemd/system/aistudio-proxy.service`）：

```ini
[Unit]
Description=AI Studio Proxy API
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/AIstudioProxyAPI
ExecStart=/usr/bin/env poetry run python launch_camoufox.py --headless
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启用与查看：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aistudio-proxy
sudo systemctl status aistudio-proxy
journalctl -u aistudio-proxy -f
```

---

## 3. Docker 部署

## 3.1 关键前提

Docker 方式通常运行在无头模式，不适合做首次交互登录。因此请先准备认证文件：

- 在宿主机本地执行一次 `--debug` 登录
- 确保 `auth_profiles/active/*.json` 存在

## 3.2 首次启动

```bash
cd docker
cp .env.docker .env
# 编辑 docker/.env

docker compose up -d --build
```

## 3.3 运行与检查

```bash
docker compose ps
docker compose logs -f
curl http://127.0.0.1:2048/health
```

## 3.4 常用维护命令

```bash
# 重启
docker compose restart

# 停止
docker compose down

# 更新（项目提供脚本）
bash update.sh

# 进入容器排查
docker compose exec ai-studio-proxy /bin/bash
```

## 3.5 多实例扩展

如需为多个已保存认证同时启动隔离容器，可使用外部管理脚本 [`scripts/multi-instance-manager/README.md`](../scripts/multi-instance-manager/README.md)。

当前 multi-instance 管理器会为每个容器显式设置独立的 `ACTIVE_AUTH_JSON_PATH`，并把选中的 profile 复制到 [`.multi-instance-runtime/active/`](../.multi-instance-runtime/) 后再挂载为容器内的 [`auth_profiles/active/`](../auth_profiles/active/) 单文件。默认同时关闭启动时自动轮转与运行时自动轮转，这样既能维持一容器一认证隔离，也能满足 Docker headless 启动阶段对 active-dir 的运行时要求。

镜像名方面，管理器默认仍优先查找 `ai-studio-proxy:latest`。但如果你是通过 `cd docker && docker compose build` 构建，Compose 常见产物会是 `docker-ai-studio-proxy:latest`；在未显式覆盖镜像名时，脚本会自动回退到该 Compose 镜像并打印提示。若你通过 `--image` 或 `IMAGE_NAME` 指定了其他镜像名，则脚本会严格使用该值，不会静默改写。

如需让单个容器重新参与跨 profile 轮转，可在脚本中使用 `--enable-auth-rotation`，但这会放宽默认的一容器一认证隔离约束。

该方案面向高级用户，不修改主应用、Dockerfile 或默认 Docker 启动流程。

---

## 4. 生产配置建议（重点）

## 4.1 网络与代理

- 优先使用 `UNIFIED_PROXY_CONFIG`
- 仅在兼容场景下再使用 `HTTP_PROXY` / `HTTPS_PROXY`
- 有内网例外地址时补充 `NO_PROXY`

## 4.2 稳定性参数

- `RESPONSE_COMPLETION_TIMEOUT`
- `SILENCE_TIMEOUT_MS`
- `WAIT_FOR_ELEMENT_TIMEOUT_MS`
- `STREAM_MAX_INITIAL_ERRORS`

建议逐步小幅调整，并通过 `logs/` 观察变化。

## 4.3 认证与轮转

推荐开启：

- `AUTO_ROTATE_AUTH_PROFILE=true`
- `COOKIE_REFRESH_ENABLED=true`
- `COOKIE_REFRESH_ON_SHUTDOWN=true`

如配额波动明显，再结合：

- `QUOTA_SOFT_LIMIT`
- `QUOTA_HARD_LIMIT`
- `QUOTA_LIMIT_<MODEL_ID>`（按模型单独阈值）

---

## 5. 运维巡检清单

- `/health` 是否为 200
- `/v1/models` 是否返回有效模型
- 队列积压是否异常：`/v1/queue`
- 浏览器与页面状态是否 ready（`/health.details`）
- 日志中是否持续出现 quota / reconnect / timeout

建议至少做一个简单定时巡检：

```bash
curl -sf http://127.0.0.1:2048/health >/dev/null || echo "health check failed"
```

---

## 6. 版本升级建议流程

1. 备份 `.env`、`auth_profiles/`。
2. 拉取新代码并更新依赖。
3. 先在 `--debug` 或测试环境验证关键模型。
4. 再切到生产 headless。
5. 观察 15~30 分钟日志后再宣告升级完成。

