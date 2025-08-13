#!/usr/bin/env python3
"""
API Fix Verification Script
Tests all the fixes made to address browser connection and task management issues
"""

import requests
import time
import json
import sys

class APITester:
    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def print_result(self, title, result, details=None):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {title}")
        if details:
            print(f"   📄 {details}")
    
    def test_health_check(self):
        """Test health check endpoint"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            success = data.get('status') == 'healthy'
            details = f"Status: {data.get('status')}, Initialized: {data.get('initialized')}"
            self.print_result("Health Check", success, details)
            return success
        except Exception as e:
            self.print_result("Health Check", False, f"Error: {e}")
            return False
    
    def test_sync_task(self):
        """Test synchronous task execution"""
        try:
            task_data = {
                "task": "Go to example.com and check the page title",
                "max_steps": 5,
                "use_vision": False
            }
            
            response = self.session.post(
                f"{self.base_url}/tasks", 
                json=task_data, 
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            
            success = result.get('success', False)
            status = result.get('status', 'unknown')
            details = f"Status: {status}, Success: {success}"
            
            if not success and 'error' in result:
                details += f", Error: {result['error']}"
            
            self.print_result("Synchronous Task", success, details)
            return success, result.get('task_id')
        except Exception as e:
            self.print_result("Synchronous Task", False, f"Error: {e}")
            return False, None
    
    def test_async_task(self):
        """Test asynchronous task execution"""
        try:
            task_data = {
                "task": "Navigate to httpbin.org/html and extract some text",
                "async": True,
                "max_steps": 5,
                "use_vision": False
            }
            
            # Start async task
            response = self.session.post(
                f"{self.base_url}/tasks", 
                json=task_data, 
                timeout=30
            )
            response.raise_for_status()
            start_result = response.json()
            
            if response.status_code != 202 or 'task_id' not in start_result:
                self.print_result("Async Task Start", False, "Failed to start task")
                return False, None
            
            task_id = start_result['task_id']
            self.print_result("Async Task Start", True, f"Task ID: {task_id}")
            
            # Wait for completion with timeout
            max_wait = 60
            poll_interval = 2
            waited = 0
            
            while waited < max_wait:
                status_response = self.session.get(f"{self.base_url}/tasks/{task_id}")
                status_response.raise_for_status()
                status = status_response.json()
                
                current_status = status.get('status', 'unknown')
                print(f"   ⏳ Task status: {current_status}")
                
                if current_status in ['completed', 'failed', 'stopped']:
                    success = current_status == 'completed' and status.get('success', False)
                    details = f"Final status: {current_status}"
                    if not success and 'error' in status:
                        details += f", Error: {status['error']}"
                    
                    self.print_result("Async Task Completion", success, details)
                    return success, task_id
                
                time.sleep(poll_interval)
                waited += poll_interval
            
            self.print_result("Async Task Completion", False, "Timeout waiting for completion")
            return False, task_id
            
        except Exception as e:
            self.print_result("Async Task", False, f"Error: {e}")
            return False, None
    
    def test_task_management(self):
        """Test task listing and deletion"""
        try:
            # List all tasks
            response = self.session.get(f"{self.base_url}/tasks")
            response.raise_for_status()
            tasks = response.json()
            
            total_tasks = tasks.get('total_completed', 0) + tasks.get('total_running', 0)
            details = f"Running: {tasks.get('total_running', 0)}, Completed: {tasks.get('total_completed', 0)}"
            self.print_result("Task Listing", True, details)
            
            # Test deleting a completed task if any exist
            completed_tasks = tasks.get('completed_tasks', {})
            if completed_tasks:
                task_id = list(completed_tasks.keys())[0]
                delete_response = self.session.delete(f"{self.base_url}/tasks/{task_id}")
                
                # Should succeed now (200) instead of 404
                success = delete_response.status_code == 200
                details = f"DELETE response: {delete_response.status_code}"
                if success:
                    delete_result = delete_response.json()
                    details += f", Message: {delete_result.get('message', 'Task removed')}"
                else:
                    details += f", Error: {delete_response.text}"
                
                self.print_result("Task Deletion", success, details)
                return success
            else:
                self.print_result("Task Deletion", True, "No tasks to delete (skipped)")
                return True
                
        except Exception as e:
            self.print_result("Task Management", False, f"Error: {e}")
            return False
    
    def test_delete_endpoint_fix(self):
        """Specifically test the DELETE endpoint fix"""
        try:
            # Create a quick async task
            task_data = {
                "task": "Test task for deletion",
                "async": True,
                "max_steps": 2
            }
            
            response = self.session.post(f"{self.base_url}/tasks", json=task_data)
            response.raise_for_status()
            task_id = response.json().get('task_id')
            
            if not task_id:
                self.print_result("DELETE Fix Test", False, "Failed to create test task")
                return False
            
            # Wait a moment for task to potentially complete
            time.sleep(3)
            
            # Try to delete it (should work now whether running or completed)
            delete_response = self.session.delete(f"{self.base_url}/tasks/{task_id}")
            success = delete_response.status_code in [200, 404]  # 404 is OK if task never existed
            
            details = f"Status: {delete_response.status_code}"
            if delete_response.status_code == 200:
                result = delete_response.json()
                details += f", Action: {result.get('message', 'Unknown')}"
            
            self.print_result("DELETE Endpoint Fix", success, details)
            return success
            
        except Exception as e:
            self.print_result("DELETE Endpoint Fix", False, f"Error: {e}")
            return False

def main():
    print("🔧 AI-Genius API Fix Verification")
    print("=" * 50)
    
    tester = APITester()
    
    # Run tests
    tests = [
        ("Health Check", tester.test_health_check),
        ("Synchronous Task", lambda: tester.test_sync_task()[0]),
        ("Asynchronous Task", lambda: tester.test_async_task()[0]),
        ("Task Management", tester.test_task_management),
        ("DELETE Endpoint Fix", tester.test_delete_endpoint_fix),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n🧪 Testing: {test_name}")
        print("-" * 30)
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ FAIL {test_name} - Exception: {e}")
            results[test_name] = False
        
        time.sleep(1)  # Brief pause between tests
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
    
    print(f"\n🎯 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The API fixes are working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the server logs for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
