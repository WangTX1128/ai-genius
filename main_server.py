#!/usr/bin/env python3
"""
Flask Server for AI-Genius Browser Agent
Provides HTTP API endpoints to execute browser automation tasks
"""

import os
import asyncio
import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import the existing agent components
from src.agent.browser_use.browser_use_agent import BrowserUseAgent
from src.controller.custom_controller import CustomController
from src.webui.webui_manager import WebuiManager
from src.browser.user_browser_pool import UserBrowserPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variables to store running tasks
running_tasks: Dict[str, Dict[str, Any]] = {}
task_results: Dict[str, Dict[str, Any]] = {}

class FlaskAgentManager:
    """Manages browser agents and tasks for Flask server"""
    
    def __init__(self):
        self.webui_manager = None
        self.user_browser_pool = None
        self.is_initialized = False
        
    async def initialize(self):
        """Initialize the WebUI manager and browser components"""
        if self.is_initialized:
            return
            
        try:
            logger.info("Initializing Flask Agent Manager...")
            
            # Create WebUI manager instance
            self.webui_manager = WebuiManager()
            
            # Initialize browser use agent
            self.webui_manager.init_browser_use_agent()
            
            # Initialize browser settings from environment variables
            browser_settings = {
                'headless': os.getenv('HEADLESS_MODE', 'false').lower() == 'true',
                'disable_security': True,
                'chrome_instance_path': os.getenv('CHROME_PATH'),
                'user_agent': os.getenv('USER_AGENT'),
                'window_width': int(os.getenv('WINDOW_WIDTH', '1280')),
                'window_height': int(os.getenv('WINDOW_HEIGHT', '720')),
                'save_recording_path': os.getenv('RECORDING_PATH'),
            }
            
            # Initialize user browser pool instead of single browser
            self.user_browser_pool = UserBrowserPool(
                browser_settings=browser_settings,
                max_idle_time=int(os.getenv('BROWSER_IDLE_TIME', '1800')),  # 30分钟
                cleanup_interval=int(os.getenv('BROWSER_CLEANUP_INTERVAL', '300')),  # 5分钟
                max_browsers=int(os.getenv('MAX_BROWSERS', '10'))  # 最大10个浏览器
            )
            
            # 启动清理任务
            await self.user_browser_pool.start_cleanup_task()
            
            # Initialize controller
            controller = CustomController(
                exclude_actions=[],
                ask_assistant_callback=self._ask_assistant_callback
            )
            self.webui_manager.bu_controller = controller
            
            self.is_initialized = True
            logger.info("Flask Agent Manager with UserBrowserPool initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Flask Agent Manager: {e}")
            self.is_initialized = False
            # Don't raise the error, just log it and continue
            # This allows the server to start even if browser initialization fails
    
    async def _ask_assistant_callback(self, query: str, browser_context) -> Dict[str, Any]:
        """Callback for when agent needs assistance"""
        logger.info(f"Agent requests assistance: {query}")
        # For API mode, we'll return a default response
        # In a real implementation, you might want to store this and provide an endpoint
        # for users to respond to assistance requests
        return {
            "response": "Proceeding without human assistance in API mode. Please try alternative approaches."
        }
    
    # Note: Browser management is now handled by UserBrowserPool
    # Individual browser initialization is no longer needed
    
    async def create_and_run_agent(self, task: str, task_id: str, 
                                  request_headers: Dict[str, str] = None, 
                                  client_ip: str = None, **kwargs) -> Dict[str, Any]:
        """Create and run a browser agent for the given task"""
        try:
            if not self.is_initialized:
                await self.initialize()
            
            # Check if initialization was successful
            if not self.is_initialized:
                raise Exception("Agent manager failed to initialize. Please check browser configuration.")
            
            # 获取用户专属的浏览器实例
            request_headers = request_headers or {}
            browser, context, user_id = await self.user_browser_pool.get_browser_for_user(
                request_headers, client_ip
            )
            
            logger.info(f"Starting task {task_id} for user {user_id}: {task}")
            
            # Get agent settings with defaults
            max_steps = kwargs.get('max_steps', 100)
            use_vision = kwargs.get('use_vision', True)
            max_actions = kwargs.get('max_actions_per_step', 10)
            
            # 定义agent工厂函数
            async def create_agent(browser, context):
                # Get LLM configuration from environment or use defaults
                llm_provider = os.getenv('LLM_PROVIDER', 'openai')
                
                # Initialize LLM based on provider
                if llm_provider == 'openai':
                    from langchain_openai import ChatOpenAI
                    
                    # Base configuration
                    llm_config = {
                        'model': os.getenv('OPENAI_MODEL', 'gpt-4o'),
                        'api_key': os.getenv('OPENAI_API_KEY'),
                        'temperature': 0.1
                    }
                    
                    # Add custom base URL if provided (for OpenAI-compatible endpoints)
                    if os.getenv('OPENAI_BASE_URL'):
                        llm_config['base_url'] = os.getenv('OPENAI_BASE_URL')
                    
                    llm = ChatOpenAI(**llm_config)
                    
                elif llm_provider == 'alibaba':
                    from langchain_openai import ChatOpenAI
                    
                    # Use Alibaba Cloud through OpenAI-compatible interface
                    llm = ChatOpenAI(
                        model=os.getenv('ALIBABA_MODEL', 'qwen-max'),
                        api_key=os.getenv('ALIBABA_API_KEY'),
                        base_url=os.getenv('ALIBABA_ENDPOINT', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                        temperature=0.1
                    )
                    
                else:
                    raise ValueError(f"Unsupported LLM provider: {llm_provider}")
                
                # Create agent with user's browser
                return BrowserUseAgent(
                    task=task,
                    llm=llm,
                    browser=browser,
                    browser_context=context,
                    controller=self.webui_manager.bu_controller,
                    use_vision=use_vision
                )
            
            # 获取或创建用户的agent实例
            agent, is_new_agent = await self.user_browser_pool.get_or_create_agent_for_user(
                user_id, task, create_agent
            )
            
            # 如果Agent创建失败，尝试重新创建浏览器
            if not agent:
                logger.warning(f"Failed to get or create agent for user {user_id}, trying to recreate browser")
                
                # 重新获取或创建浏览器
                browser, context, _ = await self.user_browser_pool.get_browser_for_user(
                    kwargs.get('request_headers', {}), kwargs.get('client_ip')
                )
                
                # 再次尝试创建Agent
                agent, is_new_agent = await self.user_browser_pool.get_or_create_agent_for_user(
                    user_id, task, create_agent
                )
                
                if not agent:
                    raise Exception(f"Failed to create agent for user {user_id} even after browser recreation")
            
            logger.info(f"Using {'new' if is_new_agent else 'existing'} agent for user {user_id}")
            
            # Set agent ID
            agent.state.agent_id = task_id
            
            # Store task info
            running_tasks[task_id] = {
                'task': task,
                'status': 'running',
                'started_at': datetime.now().isoformat(),
                'agent': agent,
                'user_id': user_id
            }
            
            # Run agent
            logger.info(f"Running agent for task {task_id}")
            history = await agent.run(max_steps=max_steps)
            
            # Process results
            result = {
                'task_id': task_id,
                'task': task,
                'status': 'completed',
                'started_at': running_tasks[task_id]['started_at'],
                'completed_at': datetime.now().isoformat(),
                'history': [step.model_dump() if hasattr(step, 'model_dump') else str(step) for step in history],
                'success': True
            }
            
            # Store result
            task_results[task_id] = result
            
            # Clean up running task and release browser
            if task_id in running_tasks:
                del running_tasks[task_id]
            
            # Release browser task count for this user and clear agent
            await self.user_browser_pool.release_browser_for_user(user_id)
            
            # Clear the agent after task completion to allow proper browser reuse
            await self.user_browser_pool.clear_agent_for_user(user_id)
            
            logger.info(f"Task {task_id} completed successfully for user {user_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error running task {task_id}: {e}")
            
            # Try to release browser resources even on error
            try:
                if 'user_id' in locals():
                    await self.user_browser_pool.release_browser_for_user(user_id)
                    # Also clear agent on error
                    await self.user_browser_pool.clear_agent_for_user(user_id)
            except Exception as cleanup_error:
                logger.error(f"Error releasing browser for task {task_id}: {cleanup_error}")
            
            # Store error result
            error_result = {
                'task_id': task_id,
                'task': task,
                'status': 'failed',
                'started_at': running_tasks.get(task_id, {}).get('started_at'),
                'completed_at': datetime.now().isoformat(),
                'error': str(e),
                'success': False
            }
            
            task_results[task_id] = error_result
            
            # Clean up running task
            if task_id in running_tasks:
                del running_tasks[task_id]
            
            return error_result

# Global agent manager
agent_manager = FlaskAgentManager()

def run_async_task(coro, task_id: str):
    """Run async task in a new event loop with proper cleanup"""
    loop = None
    try:
        # Create new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the task
        result = loop.run_until_complete(coro)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in async task {task_id}: {e}")
        return None
    finally:
        # Clean up event loop properly
        if loop:
            try:
                # Cancel any remaining tasks
                pending = asyncio.all_tasks(loop)
                if pending:
                    for task in pending:
                        task.cancel()
                    
                    # Give tasks a chance to complete cancellation
                    try:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception as cleanup_error:
                        logger.warning(f"Error during task cancellation: {cleanup_error}")
                
                # Close the loop
                loop.close()
                logger.debug(f"Event loop cleaned up for task {task_id}")
                
            except Exception as cleanup_error:
                logger.warning(f"Error during event loop cleanup for task {task_id}: {cleanup_error}")
            finally:
                # Ensure loop is removed from thread
                try:
                    asyncio.set_event_loop(None)
                except:
                    pass

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'initialized': agent_manager.is_initialized
    })

@app.route('/tasks', methods=['POST'])
def create_task():
    """Create and execute a new browser automation task"""
    try:
        data = request.get_json()
        
        if not data or 'task' not in data:
            return jsonify({'error': 'Missing task in request body'}), 400
        
        task = data['task'].strip()
        if not task:
            return jsonify({'error': 'Task cannot be empty'}), 400
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Get optional parameters
        max_steps = data.get('max_steps', 100)
        use_vision = data.get('use_vision', True)
        max_actions_per_step = data.get('max_actions_per_step', 10)
        async_execution = data.get('async', False)
        
        logger.info(f"Received task request: {task_id} - {task}")
        
        # Extract user identification information
        request_headers = dict(request.headers)
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')
        
        if async_execution:
            # Run task asynchronously
            coro = agent_manager.create_and_run_agent(
                task=task,
                task_id=task_id,
                request_headers=request_headers,
                client_ip=client_ip,
                max_steps=max_steps,
                use_vision=use_vision,
                max_actions_per_step=max_actions_per_step
            )
            
            # Start task in background thread
            thread = threading.Thread(
                target=run_async_task,
                args=(coro, task_id)
            )
            thread.daemon = True
            thread.start()
            
            return jsonify({
                'task_id': task_id,
                'status': 'started',
                'message': 'Task started asynchronously. Use /tasks/{task_id} to check status.'
            }), 202
        else:
            # Run task synchronously
            coro = agent_manager.create_and_run_agent(
                task=task,
                task_id=task_id,
                request_headers=request_headers,
                client_ip=client_ip,
                max_steps=max_steps,
                use_vision=use_vision,
                max_actions_per_step=max_actions_per_step
            )
            
            result = run_async_task(coro, task_id)
            
            if result and result.get('success'):
                return jsonify(result), 200
            else:
                return jsonify(result or {'error': 'Task execution failed'}), 500
                
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """Get status of a specific task"""
    try:
        # Check if task is still running
        if task_id in running_tasks:
            task_info = running_tasks[task_id].copy()
            # Remove agent object from response
            task_info.pop('agent', None)
            return jsonify(task_info), 200
        
        # Check if task is completed
        if task_id in task_results:
            return jsonify(task_results[task_id]), 200
        
        # Task not found
        return jsonify({'error': 'Task not found'}), 404
        
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/tasks', methods=['GET'])
def list_tasks():
    """List all tasks (running and completed)"""
    try:
        # Get running tasks (without agent objects)
        running = {}
        for tid, info in running_tasks.items():
            running[tid] = {k: v for k, v in info.items() if k != 'agent'}
        
        # Get completed tasks
        completed = task_results.copy()
        
        return jsonify({
            'running_tasks': running,
            'completed_tasks': completed,
            'total_running': len(running_tasks),
            'total_completed': len(task_results)
        }), 200
        
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/tasks/<task_id>', methods=['DELETE'])
def stop_task(task_id: str):
    """Stop a running task or remove a completed task"""
    try:
        # Check if task is currently running
        if task_id in running_tasks:
            # Get the agent and stop it
            task_info = running_tasks[task_id]
            agent = task_info.get('agent')
            
            if agent:
                agent.state.stopped = True
                logger.info(f"Stopped running task {task_id}")
            
            # Move to results with stopped status
            result = {
                'task_id': task_id,
                'task': task_info['task'],
                'status': 'stopped',
                'started_at': task_info['started_at'],
                'stopped_at': datetime.now().isoformat(),
                'success': False
            }
            
            task_results[task_id] = result
            del running_tasks[task_id]
            
            return jsonify(result), 200
        
        # Check if task is completed
        elif task_id in task_results:
            # Task is already completed, just remove it from results
            result = task_results[task_id].copy()
            del task_results[task_id]
            logger.info(f"Removed completed task {task_id}")
            return jsonify({
                'message': f'Completed task {task_id} removed from results',
                'task_info': result
            }), 200
        
        else:
            return jsonify({'error': 'Task not found'}), 404
        
    except Exception as e:
        logger.error(f"Error stopping/removing task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/browser-pool/status', methods=['GET'])
def get_browser_pool_status():
    """Get status of the user browser pool"""
    try:
        if not agent_manager.is_initialized or not agent_manager.user_browser_pool:
            return jsonify({'error': 'Browser pool not initialized'}), 503
        
        status = agent_manager.user_browser_pool.get_pool_status()
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Error getting browser pool status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/browser-pool/cleanup', methods=['POST'])
def force_browser_pool_cleanup():
    """Force cleanup of idle browsers in the pool"""
    try:
        if not agent_manager.is_initialized or not agent_manager.user_browser_pool:
            return jsonify({'error': 'Browser pool not initialized'}), 503
        
        # Get status before cleanup
        before_status = agent_manager.user_browser_pool.get_pool_status()
        
        # Run cleanup in background
        async def cleanup():
            await agent_manager.user_browser_pool._cleanup_idle_browsers()
        
        thread = threading.Thread(target=run_async_task, args=(cleanup(), 'cleanup'))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'message': 'Browser pool cleanup initiated',
            'browsers_before_cleanup': before_status['total_browsers']
        }), 200
        
    except Exception as e:
        logger.error(f"Error forcing browser pool cleanup: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/browser/screenshot', methods=['GET'])
def get_screenshot():
    """Get current browser screenshot"""
    try:
        if not agent_manager.is_initialized:
            return jsonify({'error': 'Browser not initialized'}), 400
        
        # This would need to be implemented based on your browser context
        # For now, return a placeholder
        return jsonify({
            'message': 'Screenshot endpoint - implementation needed',
            'browser_initialized': agent_manager.is_initialized
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting screenshot: {e}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Flask API Server for AI-Genius Browser Agent")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    logger.info(f"Starting Flask server on {args.host}:{args.port}")
    logger.info("Available endpoints:")
    logger.info("  POST /tasks - Create and execute a task")
    logger.info("  GET /tasks/<task_id> - Get task status")
    logger.info("  GET /tasks - List all tasks")
    logger.info("  DELETE /tasks/<task_id> - Stop a running task")
    logger.info("  GET /health - Health check")
    logger.info("  GET /browser/screenshot - Get browser screenshot")
    logger.info("  GET /browser-pool/status - Get browser pool status")
    logger.info("  POST /browser-pool/cleanup - Force browser pool cleanup")
    
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal, cleaning up...")
    finally:
        # Cleanup browser pool on shutdown
        if agent_manager.is_initialized and agent_manager.user_browser_pool:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(agent_manager.user_browser_pool.shutdown())
                loop.close()
                logger.info("Browser pool shutdown completed")
            except Exception as e:
                logger.error(f"Error during browser pool shutdown: {e}")
