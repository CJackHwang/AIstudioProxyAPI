# Roo Code 配置指南 / Roo Code Configuration

本文档说明如何在 VS Code 的 Roo Code 插件中连接 AI Studio Proxy API。

This guide shows how to connect the Roo Code VS Code extension to AI Studio Proxy API.

## 前置条件 / Prerequisites

- 已按 [快速开始](quick-start.md) 启动服务。
- `http://127.0.0.1:2048/health` 返回正常状态。
- `http://127.0.0.1:2048/v1/models` 能返回可用模型列表。

## 配置步骤 / Setup

1. 打开 Roo Code 设置页。
2. Provider 选择 `OpenAI Compatible`。
3. Base URL 填写：

   ```text
   http://127.0.0.1:2048/v1
   ```

   如果服务部署在其他机器或域名，请把主机和端口替换为你的实际地址，但保留末尾的 `/v1`。

4. API Key：
   - 如果项目中未启用 API Key 鉴权，可以填写任意非空字符串。
   - 如果已启用鉴权，请填写在项目管理接口中创建的有效 Key。
5. Model 选择 `/v1/models` 返回的模型 ID，例如 `gemini-2.5-pro`。实际可用模型以你的 AI Studio 页面和模型列表接口为准。
6. API format 使用传统 OpenAI Chat Completions 格式，不要选择 Azure OpenAI。
7. 启用 streaming，以获得更接近原生客户端的逐步输出体验。
8. 保存后，用一个简短提示词测试连接。

English summary:

1. Open Roo Code settings.
2. Select `OpenAI Compatible` as the provider.
3. Set Base URL to `http://127.0.0.1:2048/v1` or your deployed endpoint ending with `/v1`.
4. Use any non-empty API key when project-level key authentication is disabled; otherwise use a valid project API key.
5. Pick a model ID from `/v1/models`, for example `gemini-2.5-pro`.
6. Use the standard OpenAI Chat Completions format, not Azure OpenAI.
7. Enable streaming, save the profile, then test with a short prompt.

## 推荐上下文设置 / Suggested Context Settings

Roo Code 的上下文配置会影响请求大小和响应稳定性。可以从以下保守值开始，再按机器性能和模型窗口调整：

| 设置 | 建议值 | 说明 |
| --- | --- | --- |
| Open tabs context limit | `30` | 控制打开标签页注入数量 |
| Workspace file context limit | `230` | 大仓库可适当降低 |
| File read auto-truncate threshold | `-1` | 允许 Roo Code 自行控制文件读取 |
| Context window | `1000000` | 不应超过实际模型上下文能力 |

如遇到请求过大、响应变慢或浏览器端不稳定，优先降低打开标签页和工作区文件数量。

## 排查 / Troubleshooting

- 连接失败：确认 AI Studio Proxy API 仍在运行，并检查 Base URL 是否包含 `/v1`。
- 401/403：确认 API Key 设置是否和项目鉴权配置一致。
- 模型不可用：重新请求 `/v1/models`，并使用返回列表中的完整模型 ID。
- 流式输出异常：先在 Roo Code 中关闭 streaming 验证基础请求是否可用，再检查项目日志。
