# AI-Genius Flask API Server Usage Guide

## Overview

The Flask API server provides HTTP endpoints to execute browser automation tasks programmatically. This allows you to integrate the AI-Genius browser agent into your applications via REST API calls.

## Starting the Server

```bash
# Basic usage
python main_server.py

# Custom host and port
python main_server.py --host 0.0.0.0 --port 8080

# Debug mode
python main_server.py --debug
```

## Environment Variables

Make sure to set the following environment variables:

```bash
# OpenAI Configuration
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_MODEL="gpt-4o"  # optional, defaults to gpt-4o
export LLM_PROVIDER="openai"  # optional, defaults to openai
```

## API Endpoints

### 1. Health Check

Check if the server is running and initialized.

```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-20T10:30:00",
  "initialized": true
}
```

### 2. Create Task (Synchronous)

Execute a browser automation task and wait for completion.

```bash
POST /tasks
Content-Type: application/json

{
  "task": "Go to google.com and search for 'AI automation'",
  "max_steps": 50,
  "use_vision": true,
  "max_actions_per_step": 10
}
```

**Response (Success):**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "task": "Go to google.com and search for 'AI automation'",
  "status": "completed",
  "started_at": "2024-01-20T10:30:00",
  "completed_at": "2024-01-20T10:32:15",
  "history": [...],
  "success": true
}
```

**Response (Error):**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "task": "Go to google.com and search for 'AI automation'",
  "status": "failed",
  "started_at": "2024-01-20T10:30:00",
  "completed_at": "2024-01-20T10:32:15",
  "error": "Navigation timeout",
  "success": false
}
```

### 3. Create Task (Asynchronous)

Start a task asynchronously and get immediate response with task ID.

```bash
POST /tasks
Content-Type: application/json

{
  "task": "Fill out a form on example.com",
  "async": true,
  "max_steps": 100
}
```

**Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "started",
  "message": "Task started asynchronously. Use /tasks/{task_id} to check status."
}
```

### 4. Get Task Status

Check the status of a specific task.

```bash
GET /tasks/123e4567-e89b-12d3-a456-426614174000
```

**Response (Running):**
```json
{
  "task": "Fill out a form on example.com",
  "status": "running",
  "started_at": "2024-01-20T10:30:00"
}
```

**Response (Completed):**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "task": "Fill out a form on example.com",
  "status": "completed",
  "started_at": "2024-01-20T10:30:00",
  "completed_at": "2024-01-20T10:35:22",
  "history": [...],
  "success": true
}
```

### 5. List All Tasks

Get a summary of all running and completed tasks.

```bash
GET /tasks
```

**Response:**
```json
{
  "running_tasks": {
    "task-id-1": {
      "task": "Task description",
      "status": "running",
      "started_at": "2024-01-20T10:30:00"
    }
  },
  "completed_tasks": {
    "task-id-2": {
      "task_id": "task-id-2",
      "task": "Completed task",
      "status": "completed",
      "started_at": "2024-01-20T10:25:00",
      "completed_at": "2024-01-20T10:28:15",
      "success": true
    }
  },
  "total_running": 1,
  "total_completed": 1
}
```

### 6. Stop Task

Stop a running task.

```bash
DELETE /tasks/123e4567-e89b-12d3-a456-426614174000
```

**Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "task": "Task description",
  "status": "stopped",
  "started_at": "2024-01-20T10:30:00",
  "stopped_at": "2024-01-20T10:32:00",
  "success": false
}
```

### 7. Get Browser Screenshot

Get current browser screenshot (placeholder endpoint).

```bash
GET /browser/screenshot
```

## Python Client Example

```python
import requests
import time

# Server URL
BASE_URL = "http://127.0.0.1:5000"

def check_health():
    """Check server health"""
    response = requests.get(f"{BASE_URL}/health")
    return response.json()

def create_task_sync(task, **kwargs):
    """Create and execute task synchronously"""
    data = {"task": task, **kwargs}
    response = requests.post(f"{BASE_URL}/tasks", json=data)
    return response.json()

def create_task_async(task, **kwargs):
    """Create task asynchronously"""
    data = {"task": task, "async": True, **kwargs}
    response = requests.post(f"{BASE_URL}/tasks", json=data)
    return response.json()

def get_task_status(task_id):
    """Get task status"""
    response = requests.get(f"{BASE_URL}/tasks/{task_id}")
    return response.json()

def wait_for_task(task_id, poll_interval=2):
    """Wait for async task to complete"""
    while True:
        status = get_task_status(task_id)
        if status.get('status') in ['completed', 'failed', 'stopped']:
            return status
        time.sleep(poll_interval)

# Example usage
if __name__ == "__main__":
    # Check server health
    health = check_health()
    print(f"Server health: {health}")
    
    # Execute synchronous task
    result = create_task_sync(
        task="Go to google.com and search for 'Python automation'",
        max_steps=50,
        use_vision=True
    )
    print(f"Sync task result: {result}")
    
    # Execute asynchronous task
    async_task = create_task_async(
        task="Navigate to github.com and find trending repositories",
        max_steps=100
    )
    print(f"Async task started: {async_task}")
    
    # Wait for async task completion
    if 'task_id' in async_task:
        final_result = wait_for_task(async_task['task_id'])
        print(f"Async task completed: {final_result}")
```

## JavaScript/Node.js Client Example

```javascript
const axios = require('axios');

const BASE_URL = 'http://127.0.0.1:5000';

class AIGeniusClient {
    async checkHealth() {
        const response = await axios.get(`${BASE_URL}/health`);
        return response.data;
    }

    async createTaskSync(task, options = {}) {
        const data = { task, ...options };
        const response = await axios.post(`${BASE_URL}/tasks`, data);
        return response.data;
    }

    async createTaskAsync(task, options = {}) {
        const data = { task, async: true, ...options };
        const response = await axios.post(`${BASE_URL}/tasks`, data);
        return response.data;
    }

    async getTaskStatus(taskId) {
        const response = await axios.get(`${BASE_URL}/tasks/${taskId}`);
        return response.data;
    }

    async waitForTask(taskId, pollInterval = 2000) {
        while (true) {
            const status = await this.getTaskStatus(taskId);
            if (['completed', 'failed', 'stopped'].includes(status.status)) {
                return status;
            }
            await new Promise(resolve => setTimeout(resolve, pollInterval));
        }
    }
}

// Example usage
(async () => {
    const client = new AIGeniusClient();
    
    // Check health
    const health = await client.checkHealth();
    console.log('Server health:', health);
    
    // Execute task
    const result = await client.createTaskSync(
        "Go to example.com and extract the page title",
        { max_steps: 20, use_vision: true }
    );
    console.log('Task result:', result);
})();
```

## cURL Examples

```bash
# Health check
curl -X GET http://127.0.0.1:5000/health

# Create synchronous task
curl -X POST http://127.0.0.1:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Go to google.com and search for AI",
    "max_steps": 50,
    "use_vision": true
  }'

# Create asynchronous task
curl -X POST http://127.0.0.1:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Navigate to news website and summarize headlines",
    "async": true,
    "max_steps": 100
  }'

# Get task status
curl -X GET http://127.0.0.1:5000/tasks/123e4567-e89b-12d3-a456-426614174000

# List all tasks
curl -X GET http://127.0.0.1:5000/tasks

# Stop task
curl -X DELETE http://127.0.0.1:5000/tasks/123e4567-e89b-12d3-a456-426614174000
```

## Error Handling

The API returns appropriate HTTP status codes:

- `200` - Success
- `202` - Accepted (for async tasks)
- `400` - Bad Request (invalid input)
- `404` - Not Found (task not found)
- `500` - Internal Server Error

Error responses include an `error` field with a descriptive message:

```json
{
  "error": "Missing task in request body"
}
```

## Configuration

The server can be configured through environment variables and command-line arguments:

### Environment Variables

- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `OPENAI_MODEL` - OpenAI model to use (default: gpt-4o)
- `LLM_PROVIDER` - LLM provider (default: openai)

### Command Line Arguments

- `--host` - Host to bind to (default: 127.0.0.1)
- `--port` - Port to listen on (default: 5000)
- `--debug` - Enable debug mode

## Limitations

1. The browser runs in non-headless mode by default for better debugging
2. Only one browser instance is shared across all tasks
3. Tasks run sequentially (no parallel execution)
4. No authentication/authorization implemented
5. No rate limiting
6. Results are stored in memory (lost on server restart)

## Security Considerations

- Run the server in a secure environment
- Consider implementing authentication for production use
- Validate and sanitize all user inputs
- Use HTTPS in production
- Implement rate limiting to prevent abuse
