#!/usr/bin/env python3
"""
测试脚本：验证 gemini-2.5-flash-preview-native-audio-dialog 模型支持
"""

import json
import sys
import os
from typing import Dict, Any, List

# 尝试导入 requests，如果失败则提供替代方案
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("⚠️  警告: 'requests' 模块未安装，将只进行配置文件验证")

def verify_config_files() -> bool:
    """
    验证配置文件中的模型支持

    Returns:
        bool: 配置是否正确
    """
    target_model = "gemini-2.5-flash-preview-native-audio-dialog"
    success = True

    print("🔍 验证配置文件...")

    # 检查 excluded_models.txt
    try:
        with open("excluded_models.txt", "r", encoding="utf-8") as f:
            excluded_models = [line.strip() for line in f if line.strip()]

        if target_model in excluded_models:
            print(f"❌ 模型 '{target_model}' 仍在排除列表中")
            success = False
        else:
            print(f"✅ 模型 '{target_model}' 已从排除列表中移除")
    except FileNotFoundError:
        print("⚠️  excluded_models.txt 文件未找到")
        success = False
    except Exception as e:
        print(f"❌ 读取 excluded_models.txt 失败: {e}")
        success = False

    # 检查 llm.py
    try:
        with open("llm.py", "r", encoding="utf-8") as f:
            llm_content = f.read()

        if target_model in llm_content:
            print(f"✅ 模型 '{target_model}' 已添加到 llm.py 中")
        else:
            print(f"⚠️  模型 '{target_model}' 未在 llm.py 中找到（这可能不影响主要功能）")
    except FileNotFoundError:
        print("⚠️  llm.py 文件未找到")
    except Exception as e:
        print(f"❌ 读取 llm.py 失败: {e}")

    return success

def test_model_availability(base_url: str = "http://localhost:2048", api_key: str = "123456") -> bool:
    """
    测试模型是否在可用模型列表中
    
    Args:
        base_url: API服务器基础URL
        api_key: API密钥
        
    Returns:
        bool: 模型是否可用
    """
    target_model = "gemini-2.5-flash-preview-native-audio-dialog"

    if not HAS_REQUESTS:
        print("❌ 无法测试模型可用性：缺少 'requests' 模块")
        return False

    try:
        # 获取模型列表
        print(f"正在从 {base_url}/v1/models 获取模型列表...")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(f"{base_url}/v1/models", headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if "data" not in data:
            print("❌ 响应格式错误：缺少 'data' 字段")
            return False
            
        models = data["data"]
        model_ids = [model.get("id", "") for model in models]
        
        print(f"✅ 成功获取到 {len(models)} 个模型")
        print("可用模型列表：")
        for i, model_id in enumerate(model_ids, 1):
            status = "✅" if model_id == target_model else "  "
            print(f"{status} {i:2d}. {model_id}")
        
        if target_model in model_ids:
            print(f"\n🎉 成功！模型 '{target_model}' 现在可用！")
            return True
        else:
            print(f"\n❌ 模型 '{target_model}' 仍然不在可用列表中")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False

def test_model_usage(base_url: str = "http://localhost:2048", api_key: str = "123456") -> bool:
    """
    测试使用该模型进行聊天

    Args:
        base_url: API服务器基础URL
        api_key: API密钥

    Returns:
        bool: 测试是否成功
    """
    target_model = "gemini-2.5-flash-preview-native-audio-dialog"

    if not HAS_REQUESTS:
        print("❌ 无法测试模型使用：缺少 'requests' 模块")
        return False

    try:
        print(f"\n正在测试模型 '{target_model}' 的使用...")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": target_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Hello! This is a test message to verify the model is working."
                }
            ],
            "max_tokens": 100,
            "temperature": 0.7
        }
        
        print("发送测试请求...")
        response = requests.post(f"{base_url}/v1/chat/completions", 
                               headers=headers, 
                               json=payload, 
                               timeout=60)
        
        if response.status_code == 200:
            print("✅ 模型使用测试成功！")
            try:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0].get("message", {}).get("content", "")
                    print(f"模型响应: {content[:100]}...")
                return True
            except:
                print("✅ 请求成功，但响应解析可能有问题")
                return True
        elif response.status_code == 400:
            print(f"❌ 模型使用失败 (400): {response.text}")
            return False
        else:
            print(f"❌ 模型使用失败 ({response.status_code}): {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("测试 gemini-2.5-flash-preview-native-audio-dialog 模型支持")
    print("=" * 60)
    
    # 从环境变量或命令行参数获取配置
    base_url = os.environ.get("API_BASE_URL", "http://localhost:2048")
    api_key = os.environ.get("API_KEY", "123456")
    
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    if len(sys.argv) > 2:
        api_key = sys.argv[2]
    
    print(f"API服务器: {base_url}")
    print(f"API密钥: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else api_key}")
    print()

    # 首先验证配置文件
    config_test = verify_config_files()

    if not config_test:
        print("\n❌ 配置文件验证失败，请检查配置")
        sys.exit(1)

    print("\n✅ 配置文件验证通过！")

    if not HAS_REQUESTS:
        print("\n⚠️  由于缺少 'requests' 模块，无法进行在线测试")
        print("配置文件验证已通过，模型应该可以使用")
        print("\n要进行完整测试，请安装 requests 模块：")
        print("pip install requests")
        print("或使用 poetry: poetry add requests")
        sys.exit(0)

    # 测试模型可用性
    availability_test = test_model_availability(base_url, api_key)
    
    if availability_test:
        # 如果模型可用，测试使用
        usage_test = test_model_usage(base_url, api_key)
        
        if usage_test:
            print("\n🎉 所有测试通过！模型已成功支持！")
            sys.exit(0)
        else:
            print("\n⚠️  模型在列表中但使用时出现问题")
            sys.exit(1)
    else:
        print("\n❌ 模型不可用，请检查配置")
        sys.exit(1)

if __name__ == "__main__":
    main()
