#!/usr/bin/env python3
"""
Quick test to verify Ollama is running and responding
"""
import requests
import json

def test_ollama():
    host = "http://localhost:11434"
    
    print("Testing Ollama connection...")
    print(f"Host: {host}\n")
    
    # Test 1: Check if Ollama is running
    try:
        response = requests.get(f"{host}/api/tags", timeout=5)
        print("✅ Ollama is running!")
        models = response.json().get('models', [])
        print(f"   Available models: {len(models)}")
        for model in models:
            print(f"      - {model['name']}")
    except Exception as e:
        print(f"❌ Ollama not running: {e}")
        print("\n💡 Start Ollama with: ollama serve")
        return False
    
    # Test 2: Try a simple generation
    print("\n🤖 Testing generation with llama3.2:latest...")
    try:
        payload = {
            "model": "llama3.2:latest",
            "prompt": "Respond with only valid JSON: {\"test\": \"success\"}",
            "stream": False,
            "format": "json"
        }
        
        response = requests.post(f"{host}/api/generate", json=payload, timeout=30)
        result = response.json()
        
        print("✅ Generation successful!")
        print(f"   Response: {result.get('response', '')[:100]}")
        
        return True
    except Exception as e:
        print(f"❌ Generation failed: {e}")
        return False

if __name__ == '__main__':
    success = test_ollama()
    if success:
        print("\n🎉 Ollama is ready for location enhancement!")
    else:
        print("\n⚠️  Fix Ollama connection before running analyze_location_display.py")
