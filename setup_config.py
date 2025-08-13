#!/usr/bin/env python3
"""
Configuration setup script for AI-Genius
Helps users create and configure their .env file
"""

import os
import shutil
from pathlib import Path

def main():
    """Interactive configuration setup"""
    print("🔧 AI-Genius Configuration Setup")
    print("=" * 40)
    
    # Check if .env already exists
    env_file = Path(".env")
    env_example = Path("env.example")
    
    if env_file.exists():
        print(f"⚠️  .env file already exists!")
        choice = input("Do you want to overwrite it? (y/N): ").strip().lower()
        if choice not in ['y', 'yes']:
            print("❌ Configuration setup cancelled.")
            return
    
    if not env_example.exists():
        print("❌ env.example file not found! Please make sure you're in the correct directory.")
        return
    
    # Copy example file
    print(f"📄 Creating .env from {env_example}")
    shutil.copy(env_example, env_file)
    
    print("\n🚀 Configuration Guide:")
    print("=" * 40)
    
    # Get LLM provider choice
    print("\n1. Choose your LLM provider:")
    print("   a) OpenAI (default)")
    print("   b) Alibaba Cloud (Qwen)")
    print("   c) Custom OpenAI-compatible endpoint")
    
    provider_choice = input("\nChoose (a/b/c): ").strip().lower()
    
    # Read current .env content
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if provider_choice == 'b':
        # Alibaba configuration
        print("\n📝 Configuring for Alibaba Cloud...")
        content = content.replace('LLM_PROVIDER=openai', 'LLM_PROVIDER=alibaba')
        
        api_key = input("Enter your Alibaba Cloud API key: ").strip()
        if api_key:
            content = content.replace('ALIBABA_API_KEY=your-alibaba-api-key-here', f'ALIBABA_API_KEY={api_key}')
        
        model = input("Enter model name (default: qwen-max): ").strip()
        if model:
            content = content.replace('ALIBABA_MODEL=qwen-max', f'ALIBABA_MODEL={model}')
        
        endpoint = input("Enter endpoint URL (default: https://dashscope.aliyuncs.com/compatible-mode/v1): ").strip()
        if endpoint:
            content = content.replace('ALIBABA_ENDPOINT=https://dashscope.aliyuncs.com/compatible-mode/v1', f'ALIBABA_ENDPOINT={endpoint}')
    
    elif provider_choice == 'c':
        # Custom endpoint configuration
        print("\n📝 Configuring for custom OpenAI-compatible endpoint...")
        
        api_key = input("Enter your API key: ").strip()
        if api_key:
            content = content.replace('OPENAI_API_KEY=your-openai-api-key-here', f'OPENAI_API_KEY={api_key}')
        
        base_url = input("Enter base URL: ").strip()
        if base_url:
            content = content.replace('# OPENAI_BASE_URL=https://api.openai.com/v1', f'OPENAI_BASE_URL={base_url}')
        
        model = input("Enter model name (default: gpt-4o): ").strip()
        if model:
            content = content.replace('OPENAI_MODEL=gpt-4o', f'OPENAI_MODEL={model}')
    
    else:
        # OpenAI configuration (default)
        print("\n📝 Configuring for OpenAI...")
        
        api_key = input("Enter your OpenAI API key: ").strip()
        if api_key:
            content = content.replace('OPENAI_API_KEY=your-openai-api-key-here', f'OPENAI_API_KEY={api_key}')
        
        model = input("Enter model name (default: gpt-4o): ").strip()
        if model:
            content = content.replace('OPENAI_MODEL=gpt-4o', f'OPENAI_MODEL={model}')
    
    # Server configuration
    print("\n2. Server Configuration:")
    host = input("Server host (default: 127.0.0.1): ").strip()
    if host:
        content = content.replace('SERVER_HOST=127.0.0.1', f'SERVER_HOST={host}')
    
    port = input("Server port (default: 5000): ").strip()
    if port:
        content = content.replace('SERVER_PORT=5000', f'SERVER_PORT={port}')
    
    # Browser configuration
    print("\n3. Browser Configuration:")
    headless = input("Run browser in headless mode? (y/N): ").strip().lower()
    if headless in ['y', 'yes']:
        content = content.replace('HEADLESS_MODE=false', 'HEADLESS_MODE=true')
    
    # Write updated content
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✅ Configuration saved to {env_file}")
    print("\n🎉 Setup complete! You can now start the server with:")
    print("   python start_server.py")
    print("\n💡 You can manually edit .env file to fine-tune other settings.")

if __name__ == "__main__":
    main()
