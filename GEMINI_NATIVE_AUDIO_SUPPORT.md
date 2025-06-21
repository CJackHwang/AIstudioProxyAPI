# Gemini 2.5 Flash Preview Native Audio Dialog 模型支持

## 概述

本文档记录了为 AI Studio Proxy API 项目添加 `gemini-2.5-flash-preview-native-audio-dialog` 模型支持所做的更改。

## 问题描述

用户在尝试使用 `gemini-2.5-flash-preview-native-audio-dialog` 模型时遇到以下错误：

```
2025-06-21 22:46:03,544 - ERROR [SERVER] - [s15u4pr] (Worker) _process_request_refactored execution error: 400: [s15u4pr] Invalid model 'gemini-2.5-flash-preview-native-audio-dialog'. Available models: gemini-2.0-flash, gemini-2.0-flash-preview-image-generation, gemini-2.0-flash-lite, gemini-2.5-flash, gemini-2.5-flash-lite-preview-06-17, gemini-2.5-flash-preview-04-17, gemini-2.5-pro, gemini-2.5-pro-preview-05-06, gemma-3-12b-it, gemma-3-1b-it, gemma-3-27b-it, gemma-3-4b-it, gemma-3n-e4b-it, learnlm-2.0-flash-experimental, gemini-2.5-pro-preview-03-25, frostwind-ab-test, calmriver-ab-test, blacktooth-ab-test, claybrook-ab-test, goldmane-ab-test, jfdksal98a
```

## 根本原因

该模型被错误地列在了 `excluded_models.txt` 文件中，导致它被从可用模型列表中排除。

## 解决方案

### 1. 修改排除列表

**文件**: `excluded_models.txt`

**更改**: 从排除列表中移除 `gemini-2.5-flash-preview-native-audio-dialog`

**修改前**:
```
gemini-2.5-flash-preview-tts
gemini-2.5-pro-preview-tts
gemini-2.5-flash-preview-native-audio-dialog  # <- 这一行被移除
gemini-2.5-flash-exp-native-audio-thinking-dialog
```

**修改后**:
```
gemini-2.5-flash-preview-tts
gemini-2.5-pro-preview-tts
gemini-2.5-flash-exp-native-audio-thinking-dialog
```

### 2. 更新模拟服务器配置

**文件**: `llm.py`

**更改**: 在 `ENABLED_MODELS` 集合中添加新模型

**修改前**:
```python
ENABLED_MODELS = {
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
}
```

**修改后**:
```python
ENABLED_MODELS = {
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.5-flash-preview-native-audio-dialog",  # <- 新增
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
}
```

## 工作原理

1. **模型发现**: AI Studio Proxy API 通过拦截 Google AI Studio 的模型列表 API 响应来获取可用模型
2. **模型过滤**: 系统会根据 `excluded_models.txt` 文件中的列表过滤掉不需要的模型
3. **模型验证**: 当用户请求使用特定模型时，系统会验证该模型是否在可用列表中

## 测试

创建了测试脚本 `test_model_support.py` 来验证模型支持：

```bash
# 运行测试
python test_model_support.py

# 或指定自定义服务器和API密钥
python test_model_support.py http://localhost:2048 your_api_key
```

测试脚本会：
1. 检查模型是否在 `/v1/models` 端点的响应中
2. 尝试使用该模型发送测试请求
3. 验证请求是否成功处理

## 注意事项

1. **服务器重启**: 更改 `excluded_models.txt` 后需要重启服务器才能生效
2. **模型可用性**: 该模型的实际可用性取决于 Google AI Studio 的后端支持
3. **功能特性**: 作为 native audio dialog 模型，它可能支持特殊的音频对话功能

## 相关文件

- `excluded_models.txt` - 模型排除列表
- `llm.py` - 模拟 Ollama 服务器配置
- `api_utils/routes.py` - 模型列表 API 端点
- `api_utils/request_processor.py` - 请求处理和模型验证
- `browser_utils/model_management.py` - 模型管理工具函数

## 验证步骤

### 步骤 1: 配置文件验证 ✅

运行配置验证脚本：
```bash
python test_model_support.py
```

这将检查：
- ✅ 模型已从 `excluded_models.txt` 中移除
- ✅ 模型已添加到 `llm.py` 的 `ENABLED_MODELS` 中

### 步骤 2: 启动服务器

选择以下方式之一启动服务器：

**方式 A: 图形界面启动**
```bash
python gui_launcher.py
```

**方式 B: 命令行启动**
```bash
python launch_camoufox.py --headless
```

**方式 C: 使用现有浏览器会话**
```bash
python launch_camoufox.py --use-existing-session
```

### 步骤 3: 验证模型列表

服务器启动后，检查模型是否在可用列表中：

```bash
curl -X GET http://localhost:2048/v1/models \
     -H "Authorization: Bearer 123456" \
     -H "Content-Type: application/json" | jq '.data[] | select(.id == "gemini-2.5-flash-preview-native-audio-dialog")'
```

预期输出应包含：
```json
{
  "id": "gemini-2.5-flash-preview-native-audio-dialog",
  "object": "model",
  "display_name": "Gemini 2.5 Flash Preview (Native Audio Dialog)",
  "description": "...",
  ...
}
```

### 步骤 4: 测试模型使用

发送测试请求：

```bash
curl -X POST http://localhost:2048/v1/chat/completions \
     -H "Authorization: Bearer 123456" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "gemini-2.5-flash-preview-native-audio-dialog",
       "messages": [
         {
           "role": "user",
           "content": "Hello! Please respond to test the native audio dialog model."
         }
       ],
       "max_tokens": 100,
       "temperature": 0.7
     }'
```

### 步骤 5: 监控服务器日志

在服务器日志中查找：
- 模型切换日志：`切换模型: 当前=xxx -> 目标=gemini-2.5-flash-preview-native-audio-dialog`
- 成功响应：`✅ 成功获取响应内容`

### 步骤 6: 验证浏览器操作

由于项目通过浏览器自动化工作，确认：
1. 浏览器成功打开 Google AI Studio
2. 模型选择器中显示正确的模型名称
3. 能够成功发送消息并获得响应

## 故障排除

如果模型仍然不可用：

1. 检查服务器日志中的错误信息
2. 确认 Google AI Studio 后端是否支持该模型
3. 验证浏览器会话是否正常
4. 检查网络连接和代理设置
