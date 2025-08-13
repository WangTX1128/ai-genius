#!/usr/bin/env python3
"""
Test client for AI-Genius Flask API Server
Demonstrates how to use the API endpoints
"""

import requests
import time
import json
import argparse
from typing import Dict, Any

class AIGeniusClient:
    """Client for interacting with AI-Genius Flask API"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:5000"):
        self.base_url = base_url.rstrip('/')
        
    def check_health(self) -> Dict[str, Any]:
        """Check server health"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def create_task_sync(self, task: str, **kwargs) -> Dict[str, Any]:
        """Create and execute task synchronously"""
        try:
            data = {"task": task, **kwargs}
            response = requests.post(f"{self.base_url}/tasks", json=data, timeout=300)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def create_task_async(self, task: str, **kwargs) -> Dict[str, Any]:
        """Create task asynchronously"""
        try:
            data = {"task": task, "async": True, **kwargs}
            response = requests.post(f"{self.base_url}/tasks", json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get task status"""
        try:
            response = requests.get(f"{self.base_url}/tasks/{task_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def list_tasks(self) -> Dict[str, Any]:
        """List all tasks"""
        try:
            response = requests.get(f"{self.base_url}/tasks", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def stop_task(self, task_id: str) -> Dict[str, Any]:
        """Stop a running task"""
        try:
            response = requests.delete(f"{self.base_url}/tasks/{task_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def wait_for_task(self, task_id: str, poll_interval: int = 2, max_wait: int = 300) -> Dict[str, Any]:
        """Wait for async task to complete"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status = self.get_task_status(task_id)
            
            if "error" in status:
                return status
            
            if status.get('status') in ['completed', 'failed', 'stopped']:
                return status
            
            print(f"Task {task_id} status: {status.get('status', 'unknown')}")
            time.sleep(poll_interval)
        
        return {"error": "Timeout waiting for task completion"}

def print_json(data: Dict[str, Any], title: str = ""):
    """Pretty print JSON data"""
    if title:
        print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2, default=str))

def test_health_check(client: AIGeniusClient):
    """Test health check endpoint"""
    print("Testing health check...")
    health = client.check_health()
    print_json(health, "Health Check")
    return health.get('status') == 'healthy'

def test_sync_task(client: AIGeniusClient):
    """Test synchronous task execution"""
    print("\nTesting synchronous task...")
    
    task = "Go to www.baidu.com and take a screenshot"
    result = client.create_task_sync(
        task=task,
        max_steps=10,
        use_vision=True,
        max_actions_per_step=5
    )
    
    print_json(result, "Synchronous Task Result")
    return result.get('success', False)

def test_async_task(client: AIGeniusClient):
    """Test asynchronous task execution"""
    print("\nTesting asynchronous task...")
    
    task = "Navigate to example.com and extract the page title"
    
    # Start async task
    start_result = client.create_task_async(
        task=task,
        max_steps=15,
        use_vision=True
    )
    
    print_json(start_result, "Async Task Started")
    
    if "task_id" not in start_result:
        print("Failed to start async task")
        return False
    
    task_id = start_result["task_id"]
    
    # Wait for completion
    print(f"Waiting for task {task_id} to complete...")
    final_result = client.wait_for_task(task_id, poll_interval=3, max_wait=120)
    
    print_json(final_result, "Async Task Final Result")
    return final_result.get('success', False)

def test_task_management(client: AIGeniusClient):
    """Test task listing and stopping"""
    print("\nTesting task management...")
    
    # List all tasks
    tasks = client.list_tasks()
    print_json(tasks, "All Tasks")
    
    # Start a long-running task to test stopping
    long_task = client.create_task_async(
        task="Go to reddit.com and browse the front page for detailed information",
        max_steps=50
    )
    
    if "task_id" in long_task:
        task_id = long_task["task_id"]
        print(f"Started long-running task: {task_id}")
        
        # Wait a bit then stop it
        time.sleep(5)
        
        stop_result = client.stop_task(task_id)
        print_json(stop_result, "Task Stop Result")
        
        return stop_result.get('status') == 'stopped'
    
    return False

def run_all_tests(client: AIGeniusClient):
    """Run all test cases"""
    tests = [
        ("Health Check", test_health_check),
        ("Synchronous Task", test_sync_task),
        ("Asynchronous Task", test_async_task),
        ("Task Management", test_task_management),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running: {test_name}")
        print('='*50)
        
        try:
            success = test_func(client)
            results[test_name] = "PASS" if success else "FAIL"
        except Exception as e:
            print(f"Error in {test_name}: {e}")
            results[test_name] = "ERROR"
        
        time.sleep(2)  # Brief pause between tests
    
    # Print summary
    print(f"\n{'='*50}")
    print("TEST SUMMARY")
    print('='*50)
    
    for test_name, result in results.items():
        status_symbol = "✓" if result == "PASS" else "✗" if result == "FAIL" else "⚠"
        print(f"{status_symbol} {test_name}: {result}")

def main():
    parser = argparse.ArgumentParser(description="Test client for AI-Genius Flask API")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:5000", 
                        help="Base URL of the API server")
    parser.add_argument("--test", type=str, choices=["health", "sync", "async", "management", "all"],
                        default="all", help="Specific test to run")
    parser.add_argument("--task", type=str, help="Custom task to execute")
    
    args = parser.parse_args()
    
    # Create client
    client = AIGeniusClient(args.url)
    
    if args.task:
        # Execute custom task
        print(f"Executing custom task: {args.task}")
        result = client.create_task_sync(args.task, max_steps=50, use_vision=True)
        print_json(result, "Custom Task Result")
        
    elif args.test == "health":
        test_health_check(client)
    elif args.test == "sync":
        test_sync_task(client)
    elif args.test == "async":
        test_async_task(client)
    elif args.test == "management":
        test_task_management(client)
    else:
        run_all_tests(client)

if __name__ == "__main__":
    main()
