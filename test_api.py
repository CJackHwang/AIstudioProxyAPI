#!/usr/bin/env python3
"""
Simple test script to verify AI Studio Proxy API functionality
"""
import requests
import json
import time

def test_health_endpoint():
    """Test the health endpoint"""
    try:
        response = requests.get("http://localhost:2048/health", timeout=5)
        print(f"Health check: {response.status_code} - {response.text}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Health check failed: {e}")
        return False

def test_models_endpoint():
    """Test the models endpoint"""
    try:
        response = requests.get("http://localhost:2048/v1/models", timeout=10)
        print(f"Models endpoint: {response.status_code}")
        if response.status_code == 200:
            models = response.json()
            print(f"Available models: {len(models.get('data', []))}")
            for model in models.get('data', [])[:3]:  # Show first 3 models
                print(f"  - {model.get('id', 'Unknown')}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Models endpoint failed: {e}")
        return False

def test_chat_completion():
    """Test a simple chat completion"""
    try:
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Hello! Please respond with a brief greeting."}
            ],
            "max_tokens": 100,
            "stream": False
        }
        
        response = requests.post(
            "http://localhost:2048/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        print(f"Chat completion: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            print(f"Response: {content[:100]}...")
            return True
        else:
            print(f"Error: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Chat completion failed: {e}")
        return False

def main():
    print("🧪 Testing AI Studio Proxy API...")
    print("=" * 50)
    
    # Wait a moment for server to be ready
    print("Waiting for server to be ready...")
    time.sleep(2)
    
    # Test endpoints
    health_ok = test_health_endpoint()
    models_ok = test_models_endpoint()
    chat_ok = test_chat_completion()
    
    print("=" * 50)
    print("📊 Test Results:")
    print(f"  Health endpoint: {'✅' if health_ok else '❌'}")
    print(f"  Models endpoint: {'✅' if models_ok else '❌'}")
    print(f"  Chat completion: {'✅' if chat_ok else '❌'}")
    
    if health_ok and models_ok:
        print("\n🎉 API is ready for RooCode configuration!")
        print("\n📝 Recommended RooCode settings:")
        print("   Base URL: http://localhost:2048/v1")
        print("   API Key: sk-aistudio-proxy-key")
        print("   Model: gemini-2.5-pro")
    else:
        print("\n⚠️  API not ready yet. Please wait for server startup to complete.")

if __name__ == "__main__":
    main()