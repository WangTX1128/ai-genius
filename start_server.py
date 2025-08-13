#!/usr/bin/env python3
"""
Startup script for AI-Genius Flask API Server
Handles environment setup and server initialization
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from dotenv import load_dotenv

def check_requirements():
    """Check if required packages are installed"""
    required_packages = [
        'flask',
        'flask_cors',
        'browser_use',
        'langchain_openai',
        'dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nPlease install them with:")
        print("pip install -r requirements.txt")
        return False
    
    return True

def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(".env")
    if env_file.exists():
        print(f"📄 Loading configuration from {env_file}")
        load_dotenv(env_file)
        return True
    else:
        env_example = Path("env.example")
        if env_example.exists():
            print(f"💡 No .env file found. Please copy {env_example} to .env and configure it.")
        else:
            print("💡 No .env file found. You can create one or set environment variables manually.")
        return False

def check_environment():
    """Check if required environment variables are set"""
    llm_provider = os.getenv('LLM_PROVIDER', 'alibaba').lower()
    
    if llm_provider == 'openai':
        required_env = {'OPENAI_API_KEY': 'OpenAI API key'}
    elif llm_provider == 'alibaba':
        required_env = {'ALIBABA_API_KEY': 'Alibaba Cloud API key'}
    else:
        print(f"❌ Unsupported LLM provider: {llm_provider}")
        return False
    
    missing_env = []
    
    for env_var, description in required_env.items():
        if not os.getenv(env_var):
            missing_env.append((env_var, description))
    
    if missing_env:
        print("❌ Missing required environment variables:")
        for env_var, description in missing_env:
            print(f"  - {env_var}: {description}")
        print("\nPlease set them in your .env file or as environment variables.")
        print("Example .env file:")
        if llm_provider == 'openai':
            print("OPENAI_API_KEY=your-api-key-here")
        elif llm_provider == 'alibaba':
            print("ALIBABA_API_KEY=your-api-key-here")
        return False
    
    return True

def setup_environment():
    """Setup default environment variables"""
    llm_provider = os.getenv('LLM_PROVIDER', 'alibaba').lower()
    
    # Base defaults
    defaults = {
        'LLM_PROVIDER': llm_provider,
        'SERVER_HOST': '127.0.0.1',
        'SERVER_PORT': '5000',
        'DEBUG_MODE': 'false',
        'MAX_STEPS': '100',
        'USE_VISION': 'true',
        'HEADLESS_MODE': 'false'
    }
    
    # Provider-specific defaults
    if llm_provider == 'openai':
        defaults.update({
            'OPENAI_MODEL': 'gpt-4o',
        })
    elif llm_provider == 'alibaba':
        defaults.update({
            'ALIBABA_MODEL': 'qwen-max',
            'ALIBABA_ENDPOINT': 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        })
    
    for key, value in defaults.items():
        if not os.getenv(key):
            os.environ[key] = value
            print(f"📝 Set {key}={value}")
    
    # Show current configuration
    print(f"🔧 Current Configuration:")
    print(f"   Provider: {os.getenv('LLM_PROVIDER')}")
    if llm_provider == 'openai':
        print(f"   Model: {os.getenv('OPENAI_MODEL')}")
        if os.getenv('OPENAI_BASE_URL'):
            print(f"   Endpoint: {os.getenv('OPENAI_BASE_URL')}")
        else:
            print(f"   Endpoint: Default OpenAI")
    elif llm_provider == 'alibaba':
        print(f"   Model: {os.getenv('ALIBABA_MODEL')}")
        print(f"   Endpoint: {os.getenv('ALIBABA_ENDPOINT')}")
    print(f"   Server: {os.getenv('SERVER_HOST')}:{os.getenv('SERVER_PORT')}")
    print(f"   Debug: {os.getenv('DEBUG_MODE')}")
    print(f"   Vision: {os.getenv('USE_VISION')}")
    print(f"   Headless: {os.getenv('HEADLESS_MODE')}")

def main():
    parser = argparse.ArgumentParser(description="Start AI-Genius Flask API Server")
    parser.add_argument("--host", type=str, help="Host to bind to (overrides .env)")
    parser.add_argument("--port", type=int, help="Port to listen on (overrides .env)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--skip-checks", action="store_true", help="Skip dependency and environment checks")
    
    args = parser.parse_args()
    
    print("🚀 AI-Genius Flask API Server Startup")
    print("=" * 40)
    
    # Load .env file first
    print("📄 Loading environment configuration...")
    load_env_file()
    
    if not args.skip_checks:
        print("🔍 Checking requirements...")
        if not check_requirements():
            sys.exit(1)
        
        print("🔍 Checking environment...")
        if not check_environment():
            sys.exit(1)

    print("⚙️  Setting up environment...")
    setup_environment()
    
    # Use command line args to override .env values
    host = args.host or os.getenv('SERVER_HOST', '127.0.0.1')
    port = args.port or int(os.getenv('SERVER_PORT', '5000'))
    debug = args.debug or os.getenv('DEBUG_MODE', 'false').lower() == 'true'
    
    print("🌟 Starting server...")
    print(f"📍 Server will be available at: http://{host}:{port}")
    print("📚 API documentation: API_USAGE.md")
    print("🛠️  Test client: python test_client.py")
    print()
    
    # Prepare command
    cmd = [
        sys.executable, 
        "main_server.py",
        "--host", host,
        "--port", str(port)
    ]
    
    if debug:
        cmd.append("--debug")
    
    try:
        # Start the server
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Server failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
