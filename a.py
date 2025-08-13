from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import os
import psutil
import random
import logging
import threading
from datetime import datetime
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig
from langchain_openai import ChatOpenAI
import uuid
import requests
import json
import subprocess
import signal

# 1. 初始化Flask应用
app = Flask(__name__)

# 2. 配置跨域 - 允许前端和Node.js后端
allowed_origins = [
    "https://yuanfang2.paas.cmbchina.cn",
    "http://localhost:3000",  # Node.js服务
    "http://localhost:63342"  # PyCharm内置服务器
]

CORS(app, resources={
    r"/*": {
        "origins": allowed_origins,
        "supports_credentials": True,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# 3. 全局变量
browser = None
active_tasks = {}  # 存储当前活动任务 {task_id: controller}

# 4. 大模型配置 - 关键部分
api_key = "sk-683bc0b1fd804c7e306f6cb762b443b4"  # 替换为您的实际API密钥

# 创建大语言模型实例
llm = ChatOpenAI(
    model='qwen-2p5-vl-32b-instruct-mx',
    openai_api_base="http://open-llm.uat.cmbchina.cn/llm/qwen-2p5-vl-32b-instruct-mx/v1",
    openai_api_key=api_key,
    temperature=0.7,
    max_tokens=8000,
    request_timeout=120  # 增加超时时间
)


# 5. 浏览器管理功能
def kill_chrome_processes():
    """关闭所有Chrome进程"""
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            if 'chrome' in proc.info['name'].lower():
                try:
                    proc.kill()
                    app.logger.info(f"关闭进程: {proc.info['name']} (PID: {proc.info['pid']})")
                except psutil.NoSuchProcess:
                    pass
        return True
    except Exception as e:
        app.logger.error(f"关闭Chrome进程失败: {str(e)}")
        return False


def is_browser_alive(browser_instance):
    """检查浏览器实例是否还活着"""
    try:
        if not browser_instance:
            return False
        
        # 处理ChromeConnectionBrowser
        if isinstance(browser_instance, ChromeConnectionBrowser):
            return browser_instance._connected and browser_instance._playwright_browser is not None
        
        # 检查基本属性
        if not (hasattr(browser_instance, 'context') and browser_instance.context):
            return False
        
        # 更深层检查 - 尝试获取页面信息
        try:
            if hasattr(browser_instance, 'browser') and browser_instance.browser:
                # 检查是否有活跃的页面
                if hasattr(browser_instance.browser, 'contexts'):
                    contexts = browser_instance.browser.contexts
                    if contexts and len(contexts) > 0:
                        context = contexts[0]
                        if hasattr(context, 'pages') and context.pages:
                            return True
            return True
        except Exception:
            return False
        
    except Exception as e:
        app.logger.debug(f"浏览器存活检查失败: {str(e)}")
        return False

async def monitor_browser_health(browser_instance, check_interval=30):
    """异步监控浏览器健康状态"""
    while True:
        try:
            if not is_browser_alive(browser_instance):
                app.logger.warning("浏览器健康检查失败，可能需要重启")
                break
            await asyncio.sleep(check_interval)
        except Exception as e:
            app.logger.error(f"浏览器健康监控异常: {str(e)}")
            break

class BrowserMockConfig:
    """为AI Agent提供浏览器配置的模拟类，支持数学运算"""
    def __init__(self):
        self.disable_security = True
        self.headless = False
        self.viewport = {'width': 1920, 'height': 1080}
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        # 添加可能需要的数值属性
        self.operation_timeout = 60.0
        self.page_load_timeout = 30.0
        self.element_timeout = 10.0
    
    def __getattr__(self, attr_name):
        # 为任何其他配置属性返回合理的默认值
        if attr_name in ['disable_security']:
            return True
        elif attr_name in ['headless']:
            return False
        elif attr_name in ['viewport']:
            return {'width': 1920, 'height': 1080}
        elif attr_name in ['user_agent']:
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        elif 'timeout' in attr_name.lower():
            return 30.0  # 返回默认超时值
        elif attr_name in ['operation_timeout', 'page_load_timeout', 'element_timeout']:
            return 30.0
        elif attr_name.endswith('_size') or attr_name.endswith('_limit'):
            return 1000  # 返回默认大小限制
        else:
            # 对于未知属性，返回一个新的BrowserMockConfig实例，而不是原始值
            # 这确保了链式属性访问不会失败
            return BrowserMockConfig()
    
    def __sub__(self, other):
        """支持减法运算，返回新的配置实例以保持链式调用"""
        result = BrowserMockConfig()
        if isinstance(other, (int, float)):
            result.operation_timeout = max(0, 30.0 - other)
        return result
    
    def __rsub__(self, other):
        """支持右减法运算，返回新的配置实例"""
        result = BrowserMockConfig()
        if isinstance(other, (int, float)):
            result.operation_timeout = max(0, other - 30.0)
        return result
    
    def __add__(self, other):
        """支持加法运算，返回新的配置实例"""
        result = BrowserMockConfig()
        if isinstance(other, (int, float)):
            result.operation_timeout = 30.0 + other
        return result
    
    def __radd__(self, other):
        """支持右加法运算，返回新的配置实例"""
        result = BrowserMockConfig()
        if isinstance(other, (int, float)):
            result.operation_timeout = other + 30.0
        return result
    
    def __float__(self):
        """支持转换为浮点数"""
        return 30.0
    
    def __int__(self):
        """支持转换为整数"""
        return 30
    
    def __lt__(self, other):
        """支持小于比较"""
        if isinstance(other, (int, float)):
            return 30.0 < other
        return False
    
    def __le__(self, other):
        """支持小于等于比较"""
        if isinstance(other, (int, float)):
            return 30.0 <= other
        return False
    
    def __gt__(self, other):
        """支持大于比较"""
        if isinstance(other, (int, float)):
            return 30.0 > other
        return False
    
    def __ge__(self, other):
        """支持大于等于比较"""
        if isinstance(other, (int, float)):
            return 30.0 >= other
        return False
    
    def __eq__(self, other):
        """支持等于比较"""
        if isinstance(other, (int, float)):
            return 30.0 == other
        elif isinstance(other, BrowserMockConfig):
            return True  # 所有BrowserMockConfig实例都相等
        return False
    
    def __ne__(self, other):
        """支持不等于比较"""
        return not self.__eq__(other)
    
    def __rlt__(self, other):
        """支持反向小于比较 (other < self)"""
        if isinstance(other, (int, float)):
            return other < 30.0
        return False
    
    def __rle__(self, other):
        """支持反向小于等于比较 (other <= self)"""
        if isinstance(other, (int, float)):
            return other <= 30.0
        return False
    
    def __rgt__(self, other):
        """支持反向大于比较 (other > self)"""
        if isinstance(other, (int, float)):
            return other > 30.0
        return False
    
    def __rge__(self, other):
        """支持反向大于等于比较 (other >= self)"""
        if isinstance(other, (int, float)):
            return other >= 30.0
        return False
    
    def __str__(self):
        """支持字符串转换"""
        return "30.0"
    
    def __repr__(self):
        """支持repr字符串表示"""
        return "BrowserMockConfig(30.0)"
    
    def __format__(self, format_spec):
        """支持字符串格式化"""
        if format_spec == '':
            return str(30.0)
        else:
            # 使用30.0作为默认值进行格式化
            try:
                return format(30.0, format_spec)
            except (ValueError, TypeError):
                # 如果格式化失败，返回默认字符串
                return "30.0"

async def create_new_tab_in_browser(browser_instance):
    """在现有浏览器实例中创建新标签页"""
    try:
        if not browser_instance or not is_browser_alive(browser_instance):
            app.logger.warning("浏览器实例无效，无法创建新标签页")
            return None
        
        # 处理ChromeConnectionBrowser
        if isinstance(browser_instance, ChromeConnectionBrowser):
            app.logger.info("为ChromeConnectionBrowser创建新标签页")
            return await browser_instance.new_page()
        
        # 获取浏览器的context
        if hasattr(browser_instance, 'context') and browser_instance.context:
            context = browser_instance.context
        elif hasattr(browser_instance, 'browser') and browser_instance.browser:
            # 如果browser对象有contexts属性，获取第一个context
            if hasattr(browser_instance.browser, 'contexts') and browser_instance.browser.contexts:
                context = browser_instance.browser.contexts[0]
            else:
                app.logger.warning("无法找到browser context")
                return None
        else:
            app.logger.warning("浏览器实例没有可用的context")
            return None
        
        # 在context中创建新页面（新标签页）
        new_page = await context.new_page()
        app.logger.info("成功在现有浏览器中创建新标签页")
        return new_page
        
    except Exception as e:
        app.logger.error(f"创建新标签页时发生错误: {str(e)}")
        return None

class TaskBrowserWrapper:
    """为任务创建的浏览器包装器，管理新标签页"""
    def __init__(self, original_browser, new_page=None, task_id=None):
        self.original_browser = original_browser
        self.new_page = new_page
        self.task_id = task_id
        
        # 如果有新页面，使用新页面；否则使用原始浏览器
        if new_page:
            self.context = new_page.context if hasattr(new_page, 'context') else original_browser.context
            self.browser = original_browser.browser if hasattr(original_browser, 'browser') else original_browser
        else:
            self.context = original_browser.context
            self.browser = original_browser.browser if hasattr(original_browser, 'browser') else original_browser
    
    def __await__(self):
        """使TaskBrowserWrapper支持await表达式"""
        async def _awaitable():
            # 确保浏览器已连接
            if isinstance(self.original_browser, ChromeConnectionBrowser):
                await self.original_browser.ensure_connected()
            elif hasattr(self.original_browser, 'start_session'):
                if asyncio.iscoroutinefunction(self.original_browser.start_session):
                    await self.original_browser.start_session()
                else:
                    self.original_browser.start_session()
            return self
        
        return _awaitable().__await__()
    
    def get_playwright_browser(self):
        """获取Playwright浏览器实例"""
        if hasattr(self.original_browser, 'get_playwright_browser'):
            return self.original_browser.get_playwright_browser()
        elif hasattr(self.original_browser, '_playwright_browser'):
            return self.original_browser._playwright_browser
        elif hasattr(self.original_browser, 'browser'):
            return self.original_browser.browser
        else:
            return self.browser
    
    async def start_session(self):
        """启动浏览器会话 - 确保浏览器已连接"""
        try:
            # 如果原始浏览器是ChromeConnectionBrowser，确保已连接
            if isinstance(self.original_browser, ChromeConnectionBrowser):
                connected = await self.original_browser.ensure_connected()
                if not connected:
                    app.logger.error("ChromeConnectionBrowser连接失败")
                    return False
            
            # 如果原始浏览器有start_session方法，调用它
            if hasattr(self.original_browser, 'start_session'):
                if asyncio.iscoroutinefunction(self.original_browser.start_session):
                    result = await self.original_browser.start_session()
                    app.logger.info(f"浏览器start_session返回: {result}")
                    return result
                else:
                    result = self.original_browser.start_session()
                    app.logger.info(f"浏览器start_session返回: {result}")
                    return result
                    
            # 对于标准Browser对象，通常不需要特别的启动操作
            app.logger.info("浏览器会话启动成功")
            return True
            
        except Exception as e:
            app.logger.error(f"启动浏览器会话失败: {str(e)}")
            return False
    
    async def close(self):
        """关闭浏览器 - 仅关闭新页面，保留原始浏览器"""
        try:
            if self.new_page:
                await self.new_page.close()
                app.logger.info(f"任务 {self.task_id} 的标签页已关闭")
        except Exception as e:
            app.logger.warning(f"关闭任务标签页失败: {str(e)}")

    def __getattr__(self, name):
        """代理所有其他属性到原始浏览器"""
        # 对于浏览器配置相关属性，提供默认值或返回配置对象
        if name == 'config':
            return BrowserMockConfig()
        
        # 对于其他常见的浏览器配置属性，返回默认值而不是代理
        elif name in ['disable_security', 'headless', 'viewport', 'user_agent']:
            # 返回合理的默认值
            if name == 'disable_security':
                return True
            elif name == 'headless':
                return False
            elif name == 'viewport':
                return {'width': 1920, 'height': 1080}
            elif name == 'user_agent':
                return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
        # 对于常见的异步方法，确保正确处理
        elif name in ['start_session', 'close']:
            # 这些方法已经在类中定义，不应该到这里
            pass
            
        # 优先检查新页面
        if self.new_page and hasattr(self.new_page, name):
            attr = getattr(self.new_page, name)
            return attr
            
        # 然后检查原始浏览器
        if hasattr(self.original_browser, name):
            attr = getattr(self.original_browser, name)
            # 如果是异步方法，包装它以确保正确处理
            if asyncio.iscoroutinefunction(attr):
                async def wrapped_async_method(*args, **kwargs):
                    # 如果原始浏览器是ChromeConnectionBrowser，确保已连接
                    if isinstance(self.original_browser, ChromeConnectionBrowser):
                        await self.original_browser.ensure_connected()
                    return await attr(*args, **kwargs)
                return wrapped_async_method
            else:
                return attr
            
        # 如果都没有找到，抛出 AttributeError
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

async def prepare_browser_for_task(browser_instance, task_id):
    """为任务准备浏览器实例（在新标签页中）"""
    try:
        # 尝试在现有浏览器中创建新标签页
        new_page = await create_new_tab_in_browser(browser_instance)
        
        if new_page:
            app.logger.info(f"任务 {task_id} 将在新标签页中执行")
            return TaskBrowserWrapper(browser_instance, new_page, task_id)
        else:
            app.logger.info(f"任务 {task_id} 将在现有浏览器页面中执行")
            return browser_instance
            
    except Exception as e:
        app.logger.warning(f"准备任务浏览器失败: {str(e)}, 使用原始浏览器实例")
        return browser_instance

def find_existing_chrome_processes():
    """查找正在运行的Chrome进程及其调试端口"""
    chrome_processes = []
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    cmdline = proc.info['cmdline'] or []
                    # 查找带有remote-debugging-port参数的Chrome进程
                    for arg in cmdline:
                        if '--remote-debugging-port=' in str(arg):
                            port = str(arg).split('=')[1]
                            chrome_processes.append({
                                'pid': proc.info['pid'],
                                'port': port,
                                'cmdline': cmdline
                            })
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        app.logger.error(f"查找Chrome进程时出错: {str(e)}")
    
    app.logger.info(f"找到 {len(chrome_processes)} 个带调试端口的Chrome进程")
    return chrome_processes

def get_available_debug_port():
    """获取可用的调试端口，优先使用9222"""
    import socket
    
    preferred_ports = [9222, 9223, 9224, 9225]
    
    for port in preferred_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', port))
                if result == 0:  # 端口被占用，可能是Chrome
                    app.logger.info(f"端口 {port} 被占用，可能是Chrome调试端口")
                    return port
        except Exception:
            pass
    
    # 如果没有找到现有端口，返回默认端口
    return 9222

def start_chrome_with_debugging():
    """启动Chrome浏览器并开启远程调试"""
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    debug_port = 9222
    
    # 检查Chrome是否已经在运行
    existing_processes = find_existing_chrome_processes()
    if existing_processes:
        app.logger.info("发现现有Chrome进程，尝试连接...")
        return existing_processes[0]['port']
    
    try:
        # 启动Chrome并开启调试模式
        cmd = [
            chrome_path,
            f'--remote-debugging-port={debug_port}',
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--user-data-dir=C:\\temp\\chrome_debug_profile'
        ]
        
        app.logger.info(f"启动Chrome调试模式，端口: {debug_port}")
        subprocess.Popen(cmd, shell=False)
        
        # 等待Chrome启动
        import time
        time.sleep(3)
        
        return str(debug_port)
        
    except Exception as e:
        app.logger.error(f"启动Chrome调试模式失败: {str(e)}")
        return None

async def connect_to_existing_chrome(debug_port=None):
    """连接到现有的Chrome浏览器实例"""
    if debug_port is None:
        debug_port = get_available_debug_port()
    
    try:
        app.logger.info(f"尝试连接到Chrome调试端口: {debug_port}")
        
        # 获取浏览器的websocket调试URL
        response = requests.get(f'http://127.0.0.1:{debug_port}/json/version', timeout=5)
        if response.status_code == 200:
            version_info = response.json()
            websocket_url = version_info.get('webSocketDebuggerUrl')
            app.logger.info(f"Chrome调试信息获取成功: {version_info.get('Browser', 'Unknown')}")
            
            # 使用playwright连接到现有Chrome
            from playwright.async_api import async_playwright
            
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
            
            app.logger.info("成功连接到现有Chrome浏览器！")
            return browser
            
        else:
            app.logger.warning(f"无法获取Chrome调试信息，状态码: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        app.logger.warning(f"连接Chrome调试端口失败: {str(e)}")
        return None
    except Exception as e:
        app.logger.error(f"连接现有Chrome时出错: {str(e)}")
        return None

async def get_or_create_chrome_page(browser):
    """获取或创建Chrome页面"""
    try:
        # 获取现有页面
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                app.logger.info("使用现有Chrome页面")
                return pages[0]
        
        # 创建新的context和页面
        context = await browser.new_context()
        page = await context.new_page()
        app.logger.info("在现有Chrome中创建新页面")
        return page
        
    except Exception as e:
        app.logger.error(f"获取/创建Chrome页面失败: {str(e)}")
        return None

class ChromeConnectionBrowser:
    """连接现有Chrome浏览器的包装器"""
    
    def __init__(self, debug_port):
        self.debug_port = debug_port
        self._playwright_browser = None
        self._connected = False
        self.context = None
        self.browser = None
    
    def __await__(self):
        """使ChromeConnectionBrowser支持await表达式"""
        return self.ensure_connected().__await__()
        
    async def ensure_connected(self):
        """确保已连接到Chrome"""
        if not self._connected:
            app.logger.info(f"连接到Chrome调试端口: {self.debug_port}")
            self._playwright_browser = await connect_to_existing_chrome(self.debug_port)
            if self._playwright_browser:
                self._connected = True
                self.browser = self._playwright_browser
                
                # 获取或创建context
                if self._playwright_browser.contexts:
                    self.context = self._playwright_browser.contexts[0]
                else:
                    self.context = await self._playwright_browser.new_context()
                    
                app.logger.info("Chrome连接建立成功")
                return True
            else:
                app.logger.error("Chrome连接失败")
                return False
        
        app.logger.info("Chrome已连接")
        return True
    
    async def new_page(self):
        """在连接的Chrome中创建新页面"""
        if await self.ensure_connected():
            try:
                if self.context:
                    page = await self.context.new_page()
                    app.logger.info("在现有Chrome中创建新标签页")
                    return page
                else:
                    app.logger.error("Chrome context不可用")
                    return None
            except Exception as e:
                app.logger.error(f"创建新页面失败: {str(e)}")
                return None
        return None
    
    def get_playwright_browser(self):
        """获取Playwright浏览器实例"""
        if self._playwright_browser:
            return self._playwright_browser
        return None
    
    async def start_session(self):
        """启动浏览器会话 - 确保已连接到Chrome"""
        return await self.ensure_connected()
    
    async def close(self):
        """关闭浏览器连接"""
        try:
            if self._playwright_browser:
                await self._playwright_browser.close()
                app.logger.info("ChromeConnectionBrowser已关闭")
            self._connected = False
            self._playwright_browser = None
            self.context = None
            self.browser = None
        except Exception as e:
            app.logger.warning(f"关闭ChromeConnectionBrowser失败: {str(e)}")

    def __getattr__(self, name):
        """代理所有其他属性到playwright浏览器"""
        # 对于浏览器配置相关属性，提供默认值或返回配置对象
        if name == 'config':
            return BrowserMockConfig()
        
        # 对于其他常见的浏览器配置属性，返回默认值
        elif name in ['disable_security', 'headless', 'viewport', 'user_agent']:
            if name == 'disable_security':
                return True
            elif name == 'headless':
                return False
            elif name == 'viewport':
                return {'width': 1920, 'height': 1080}
            elif name == 'user_agent':
                return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
        # 如果已连接，直接代理到playwright浏览器
        if self._playwright_browser and hasattr(self._playwright_browser, name):
            attr = getattr(self._playwright_browser, name)
            # 如果是异步方法，包装它以确保连接
            if asyncio.iscoroutinefunction(attr):
                async def wrapped_async_method(*args, **kwargs):
                    await self.ensure_connected()
                    return await attr(*args, **kwargs)
                return wrapped_async_method
            else:
                return attr
            
        # 对于未连接的情况，返回一个异步函数（仅对方法调用有效）
        if not self._connected:
            async def async_placeholder(*args, **kwargs):
                if await self.ensure_connected():
                    if hasattr(self._playwright_browser, name):
                        attr = getattr(self._playwright_browser, name)
                        if asyncio.iscoroutinefunction(attr):
                            return await attr(*args, **kwargs)
                        else:
                            return attr
                return None
            return async_placeholder
            
        # 如果都没有找到，抛出 AttributeError
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


def init_browser(user_id=None):
    """初始化浏览器实例 - 优先连接现有Chrome"""
    global browser

    app.logger.info("开始初始化浏览器，优先连接现有Chrome...")
    
    # 第一步：尝试连接现有的Chrome浏览器
    try:
        existing_processes = find_existing_chrome_processes()
        if existing_processes:
            app.logger.info("发现现有Chrome进程，尝试连接...")
            # 这里需要返回一个异步任务，因为connect_to_existing_chrome是异步的
            # 我们将创建一个特殊的浏览器对象来延迟连接
            return ChromeConnectionBrowser(existing_processes[0]['port'])
        
        # 第二步：检查是否有可用的Chrome调试端口
        debug_port = get_available_debug_port()
        if debug_port != 9222:  # 如果找到了正在使用的端口
            app.logger.info(f"发现Chrome调试端口 {debug_port}，尝试连接...")
            return ChromeConnectionBrowser(debug_port)
            
    except Exception as e:
        app.logger.warning(f"检查现有Chrome失败: {str(e)}")

    # 第三步：如果没有现有Chrome，则启动新的Chrome实例 
    app.logger.info("未找到现有Chrome，创建新的浏览器实例...")

    # 浏览器可执行文件路径
    CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    # 创建独立的用户数据目录，避免与现有浏览器冲突
    if user_id:
        user_data_dir = os.path.join(os.getcwd(), f"agent_user_data_{user_id}")
    else:
        user_data_dir = os.path.join(os.getcwd(), f"agent_user_data_{random.randint(1000, 9999)}")

    os.makedirs(user_data_dir, exist_ok=True)
    app.logger.info(f"Agent浏览器用户数据目录: {user_data_dir}")

    # 浏览器配置 - 使用独立的用户数据目录
    context_config = BrowserContextConfig()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"

    browser_config = BrowserConfig(
        headless=False,
        disable_security=True,
        extra_chromium_args=[
            f'--user-data-dir={user_data_dir}',
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--new-window',  # 打开新窗口而不是新实例
            f'--user-agent={user_agent}',
            '--disable-extensions',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--disable-features=VizDisplayCompositor',
            '--disable-plugins',
            '--disable-images',  # 减少内存使用，提高稳定性
            '--disable-javascript-harmony-shipping',
            '--max_old_space_size=4096',
            '--memory-pressure-off',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-crash-reporter',
            '--disable-logging',
            '--disable-breakpad',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-web-security',  # 提高兼容性
            '--remote-debugging-port=9222'  # 固定调试端口便于连接
        ],
        chrome_instance_path=CHROME_PATH,
        new_context_config=context_config
    )

    try:
        browser = Browser(config=browser_config)
        app.logger.info("新浏览器实例创建成功")
        return browser
    except Exception as e:
        app.logger.error(f"浏览器实例创建失败: {str(e)}")
        raise e


# 6. 任务执行核心逻辑
async def run_agent_task(task: str, user_id=None, data=None):
    """执行大模型驱动的任务 - 支持并发执行"""
    global browser, active_tasks

    task_id = str(uuid.uuid4())  # 生成唯一任务ID
    app.logger.info(f"开始任务 [{task_id}]: {task} (当前活跃任务: {len(active_tasks)})")

    # 初始化浏览器（如果尚未初始化或连接已断开）
    if not browser:
        app.logger.info("初始化新的浏览器实例...")
        browser = init_browser(user_id)
    else:
        # 检查现有浏览器是否还可用
        if is_browser_alive(browser):
            app.logger.info("使用现有的浏览器实例，准备在新标签页中执行任务")
        else:
            app.logger.warning("现有浏览器不可用，创建新实例")
            browser = None
            browser = init_browser(user_id)

    try:
        # 创建任务控制器
        controller = Controller()
        controller.operation_timeout = 600.0  # 10分钟超时

        # 将控制器添加到活动任务
        active_tasks[task_id] = controller

        # 确保ChromeConnectionBrowser已连接
        if isinstance(browser, ChromeConnectionBrowser):
            await browser.ensure_connected()
        
        # 创建或获取新标签页的浏览器实例
        task_browser = await prepare_browser_for_task(browser, task_id)
        
        # 确保task_browser也完全连接
        if isinstance(task_browser, TaskBrowserWrapper):
            if isinstance(task_browser.original_browser, ChromeConnectionBrowser):
                await task_browser.original_browser.ensure_connected()

        # 创建Agent实例 - 整合大模型
        agent = Agent(
            task=task,
            llm=llm,  # 使用大语言模型
            controller=controller,
            browser=task_browser
        )

        # 执行任务，带重试机制
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                app.logger.info(f"执行任务尝试 {attempt + 1}/{max_retries + 1}")
                
                # 在每次重试前检查浏览器状态
                if attempt > 0:
                    if not is_browser_alive(browser):
                        app.logger.warning(f"重试 {attempt}: 浏览器连接丢失，重新初始化")
                        browser = init_browser(user_id)
                        # 为重试准备新的浏览器实例（新标签页）
                        task_browser = await prepare_browser_for_task(browser, task_id)
                        # 更新 agent 的浏览器实例
                        agent.browser = task_browser
                        agent.controller.browser = task_browser
                
                history = await agent.run()
                break  # 成功则退出重试循环
                
            except Exception as e:
                error_msg = str(e)
                app.logger.warning(f"任务执行尝试 {attempt + 1} 失败: {error_msg}")
                
                # 如果是浏览器相关错误且还有重试机会
                if (attempt < max_retries and 
                    ("Target page, context or browser has been closed" in error_msg or
                     "Browser is closed" in error_msg or
                     "'NoneType' object" in error_msg or
                     "Page.title" in error_msg)):
                    
                    app.logger.info("检测到浏览器连接问题，准备重试...")
                    browser = None  # 重置浏览器
                    await asyncio.sleep(2)  # 短暂等待
                    continue
                else:
                    # 非浏览器错误或已达最大重试次数
                    raise e

        # 获取最终结果
        result = history.final_result()

        app.logger.info(f"任务完成 [{task_id}]: {result[:100]}...")
        return {
            "success": True,
            "result": result,
            "task_id": task_id
        }

    except asyncio.CancelledError:
        app.logger.warning(f"任务被取消 [{task_id}]")
        return {
            "success": False,
            "error": "任务被用户取消",
            "task_id": task_id
        }

    except Exception as e:
        app.logger.error(f"任务执行失败 [{task_id}]: {str(e)}")
        error_msg = str(e)
        
        # 如果是浏览器相关错误，重置浏览器实例
        if ("'NoneType' object has no attribute" in error_msg or 
            "Browser is closed" in error_msg or
            "Target page, context or browser has been closed" in error_msg or
            "send" in error_msg.lower()):
            app.logger.warning("检测到浏览器连接错误，重置浏览器实例")
            browser = None
        
        return {
            "success": False,
            "error": f"任务执行失败: {error_msg}",
            "task_id": task_id
        }

    finally:
        # 清理任务状态
        if task_id in active_tasks:
            del active_tasks[task_id]
            app.logger.info(f"任务 [{task_id}] 已清理，剩余活跃任务: {len(active_tasks)}")
        
        # 检查浏览器状态，如果连接断开则重置
        if browser and not is_browser_alive(browser):
            app.logger.warning("浏览器连接已断开，重置浏览器实例")
            browser = None


# 7. API接口
@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    # 检查浏览器状态
    browser_status = "not_initialized"
    if browser:
        if is_browser_alive(browser):
            browser_status = "active"
        else:
            browser_status = "disconnected"
    
    return jsonify({
        "status": "running",
        "service": "agent_server",
        "llm_status": "available" if llm else "unavailable",
        "browser_status": browser_status,
        "active_tasks": len(active_tasks),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/run-agent-task', methods=['POST'])
def run_agent_task_endpoint():
    """执行大模型任务端点 - 支持并发任务执行"""
    data = request.json
    task = data.get('task')
    user_id = data.get('userId', 'default_user')
    custom_data = data.get('data', {})

    if not task:
        return jsonify({"success": False, "error": "任务不能为空"}), 400

    # 检查当前活跃任务数量，设置最大并发限制
    max_concurrent_tasks = 5  # 最多同时运行5个任务
    if len(active_tasks) >= max_concurrent_tasks:
        return jsonify({
            "success": False,
            "error": f"当前有{len(active_tasks)}个任务在运行，已达到最大并发限制({max_concurrent_tasks})，请稍后再试"
        }), 429

    try:
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 运行任务
        result = loop.run_until_complete(
            run_agent_task(task, user_id, custom_data)
        )
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"任务启动失败: {str(e)}"
        }), 500

    finally:
        if loop:
            loop.close()


@app.route('/stop-agent-task', methods=['POST'])
def stop_agent_task():
    """停止指定任务端点"""
    global active_tasks

    try:
        # 获取要停止的任务ID（从请求中获取）
        data = request.json
        task_id = data.get('task_id')

        if not task_id:
            return jsonify({
                "success": False,
                "error": "需要提供task_id参数"
            }), 400

        # 查找并取消任务
        if task_id in active_tasks:
            controller = active_tasks[task_id]
            controller.cancel()  # 取消任务
            del active_tasks[task_id]
            app.logger.info(f"任务已取消: {task_id}，剩余活跃任务: {len(active_tasks)}")

            return jsonify({
                "success": True,
                "message": f"任务 {task_id} 已停止",
                "remaining_tasks": len(active_tasks)
            })
        else:
            return jsonify({
                "success": False,
                "error": f"未找到任务ID: {task_id}"
            }), 404

    except Exception as e:
        app.logger.error(f"停止任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"停止任务失败: {str(e)}"
        }), 500


# 添加日志推送接口，用于WebSocket广播
@app.route('/log', methods=['POST'])
def log_message():
    """接收并广播日志消息"""
    try:
        data = request.json
        message = data.get('message')
        level = data.get('level', 'info')

        if message:
            # 这里会被Node.js中间层捕获并通过WebSocket广播
            app.logger.log(logging.getLevelName(level.upper()), message)
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "日志消息不能为空"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/stop-all-tasks', methods=['POST'])
def stop_all_tasks():
    """停止所有活跃任务端点"""
    global active_tasks

    try:
        if not active_tasks:
            return jsonify({
                "success": True,
                "message": "当前没有活跃任务",
                "stopped_count": 0
            })

        stopped_tasks = []
        # 复制任务ID列表，避免在迭代时修改字典
        task_ids = list(active_tasks.keys())
        
        for task_id in task_ids:
            try:
                controller = active_tasks[task_id]
                controller.cancel()  # 取消任务
                del active_tasks[task_id]
                stopped_tasks.append(task_id)
                app.logger.info(f"任务已取消: {task_id}")
            except Exception as e:
                app.logger.error(f"取消任务 {task_id} 失败: {str(e)}")

        return jsonify({
            "success": True,
            "message": f"已停止 {len(stopped_tasks)} 个任务",
            "stopped_tasks": stopped_tasks,
            "remaining_tasks": len(active_tasks)
        })

    except Exception as e:
        app.logger.error(f"停止所有任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"停止所有任务失败: {str(e)}"
        }), 500


@app.route('/list-active-tasks', methods=['GET'])
def list_active_tasks():
    """列出所有活跃任务"""
    try:
        task_list = []
        for task_id, controller in active_tasks.items():
            task_info = {
                "task_id": task_id,
                "status": "running"
            }
            task_list.append(task_info)

        return jsonify({
            "success": True,
            "active_tasks": task_list,
            "total_count": len(active_tasks)
        })

    except Exception as e:
        app.logger.error(f"获取活跃任务列表失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"获取任务列表失败: {str(e)}"
        }), 500


@app.route('/reset-browser', methods=['POST'])
def reset_browser():
    """重置浏览器实例"""
    global browser
    try:
        app.logger.info("手动重置浏览器实例...")
        
        # 关闭现有浏览器
        if browser:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # 尝试关闭浏览器
                    if hasattr(browser, 'close'):
                        loop.run_until_complete(browser.close())
                finally:
                    loop.close()
            except Exception as e:
                app.logger.warning(f"关闭旧浏览器实例时出错: {str(e)}")
        
        # 重置浏览器变量
        browser = None
        
        return jsonify({
            "success": True,
            "message": "浏览器实例已重置，下次任务将创建新实例"
        })
        
    except Exception as e:
        app.logger.error(f"重置浏览器失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"重置失败: {str(e)}"
        }), 500


@app.route('/force-close-browsers', methods=['POST'])
def force_close_browsers():
    """强制关闭所有Chrome浏览器进程 - 仅在紧急情况下使用"""
    try:
        data = request.json
        confirm = data.get('confirm', False)
        
        if not confirm:
            return jsonify({
                "success": False,
                "error": "需要确认参数 'confirm': true 才能执行此操作"
            }), 400
        
        app.logger.warning("执行强制关闭所有Chrome浏览器进程...")
        result = kill_chrome_processes()
        
        if result:
            return jsonify({
                "success": True,
                "message": "已强制关闭所有Chrome浏览器进程"
            })
        else:
            return jsonify({
                "success": False,
                "error": "关闭浏览器进程时出现错误"
            }), 500
            
    except Exception as e:
        app.logger.error(f"强制关闭浏览器失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"操作失败: {str(e)}"
        }), 500


# 8. 浏览器维护线程
def browser_maintenance():
    """定期清理浏览器资源"""
    global browser, active_tasks
    
    while True:
        # 每30分钟检查一次
        threading.Event().wait(1800)

        # 如果没有活动任务，关闭Agent专用浏览器释放资源
        # 注意：这只会关闭Agent创建的浏览器实例，不会影响用户的其他浏览器窗口
        if not active_tasks and browser:
            try:
                app.logger.info(f"执行定期Agent浏览器清理，当前活跃任务数: {len(active_tasks)}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(browser.close())
                browser = None
                app.logger.info("Agent浏览器已关闭")
            except Exception as e:
                app.logger.error(f"Agent浏览器清理失败: {str(e)}")
            finally:
                if loop:
                    loop.close()


# 9. 启动服务
if __name__ == '__main__':
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("agent_service.log"),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)

    # 启动浏览器维护线程
    maintenance_thread = threading.Thread(
        target=browser_maintenance,
        daemon=True
    )
    maintenance_thread.start()

    # 启动参数
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=False,
        threaded=True
    )