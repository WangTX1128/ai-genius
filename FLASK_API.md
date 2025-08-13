# AI-Genius Flask API Server

This document describes the Flask API server that allows you to execute browser automation tasks via HTTP requests.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

#### Option A: Using .env file (recommended)
```bash
# Copy the example configuration file
cp env.example .env

# Edit .env file with your settings
# or use the interactive setup script
python setup_config.py
```

#### Option B: Environment variables
```bash
export OPENAI_API_KEY="your-openai-api-key"
export LLM_PROVIDER="openai"  # or "alibaba"
export OPENAI_MODEL="gpt-4o"  # Optional
```

#### Option C: Alibaba Cloud configuration
```bash
export LLM_PROVIDER="alibaba"
export ALIBABA_API_KEY="your-alibaba-api-key"
export ALIBABA_MODEL="qwen-max"
export ALIBABA_ENDPOINT="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### 3. Start the Server

#### Option A: Using the startup script (recommended)
```bash
python start_server.py
```

#### Option B: Direct server start
```bash
python main_server.py
```

#### Option C: Custom configuration
```bash
python main_server.py --host 0.0.0.0 --port 8080 --debug
```

### 4. Test the Server

```bash
# Health check
curl http://127.0.0.1:5000/health

# Run test client
python test_client.py
```

## Basic Usage

### Execute a Simple Task

```python
import requests

# Synchronous execution
response = requests.post('http://127.0.0.1:5000/tasks', json={
    "task": "Go to google.com and search for 'AI automation'",
    "max_steps": 20,
    "use_vision": True
})

result = response.json()
print(f"Task completed: {result['success']}")
```

### Execute an Asynchronous Task

```python
import requests
import time

# Start async task
response = requests.post('http://127.0.0.1:5000/tasks', json={
    "task": "Browse news website and summarize top headlines",
    "async": True,
    "max_steps": 50
})

task_id = response.json()['task_id']

# Poll for completion
while True:
    status = requests.get(f'http://127.0.0.1:5000/tasks/{task_id}').json()
    if status['status'] in ['completed', 'failed', 'stopped']:
        print(f"Task finished: {status}")
        break
    time.sleep(2)
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health check |
| POST | `/tasks` | Create and execute task |
| GET | `/tasks` | List all tasks |
| GET | `/tasks/{id}` | Get task status |
| DELETE | `/tasks/{id}` | Stop running task |
| GET | `/browser/screenshot` | Get browser screenshot |

## Features

- ✅ Synchronous and asynchronous task execution
- ✅ Real-time task status monitoring
- ✅ Task management (start, stop, list)
- ✅ CORS support for web applications
- ✅ Comprehensive error handling
- ✅ Vision support for better page understanding
- ✅ Configurable execution parameters

## Configuration

### Using .env File

The easiest way to configure AI-Genius is using a `.env` file:

```bash
# Copy the example configuration
cp env.example .env

# Use interactive setup (recommended)
python setup_config.py

# Or manually edit .env file
```

### Environment Variables

#### LLM Provider Configuration
- `LLM_PROVIDER` - LLM provider (`openai` or `alibaba`)

#### OpenAI Configuration
- `OPENAI_API_KEY` - Your OpenAI API key (required for OpenAI)
- `OPENAI_MODEL` - OpenAI model (default: gpt-4o)
- `OPENAI_BASE_URL` - Custom OpenAI-compatible endpoint (optional)

#### Alibaba Cloud Configuration
- `ALIBABA_API_KEY` - Your Alibaba Cloud API key (required for Alibaba)
- `ALIBABA_MODEL` - Alibaba model (default: qwen-max)
- `ALIBABA_ENDPOINT` - Alibaba endpoint (default: https://dashscope.aliyuncs.com/compatible-mode/v1)

#### Server Configuration
- `SERVER_HOST` - Server host (default: 127.0.0.1)
- `SERVER_PORT` - Server port (default: 5000)
- `DEBUG_MODE` - Enable debug mode (default: false)

#### Browser Configuration
- `HEADLESS_MODE` - Run browser in headless mode (default: false)
- `WINDOW_WIDTH` - Browser window width (default: 1280)
- `WINDOW_HEIGHT` - Browser window height (default: 720)
- `CHROME_PATH` - Custom Chrome/Chromium path (optional)
- `USER_AGENT` - Custom user agent (optional)

### Task Parameters

- `task` - Task description (required)
- `max_steps` - Maximum execution steps (default: 100)
- `use_vision` - Enable vision capabilities (default: true)
- `max_actions_per_step` - Actions per step (default: 10)
- `async` - Asynchronous execution (default: false)

## Examples

### Web Scraping
```json
{
  "task": "Go to news.ycombinator.com and extract the top 5 story titles",
  "max_steps": 30,
  "use_vision": true
}
```

### Form Filling
```json
{
  "task": "Navigate to contact form at example.com and fill with test data",
  "max_steps": 25,
  "async": true
}
```

### Research Tasks
```json
{
  "task": "Search for 'machine learning trends 2024' and summarize key findings",
  "max_steps": 50,
  "use_vision": true
}
```

## Files

- `main_server.py` - Main Flask server implementation
- `start_server.py` - Server startup script with checks
- `test_client.py` - Test client and examples
- `API_USAGE.md` - Detailed API documentation

## Troubleshooting

### Server Won't Start
1. Check if all dependencies are installed: `pip install -r requirements.txt`
2. Verify OpenAI API key is set: `echo $OPENAI_API_KEY`
3. Check if port is available: `netstat -an | grep :5000`

### Tasks Fail to Execute
1. Check server logs for error messages
2. Verify browser can start (display available)
3. Ensure task description is clear and specific
4. Try reducing max_steps or disabling vision

### Browser Issues
1. Make sure you have Chrome/Chromium installed
2. Check display settings (X11 forwarding for remote)
3. Try running in headless mode (modify browser_settings in main_server.py)

For detailed API documentation, see `API_USAGE.md`.
