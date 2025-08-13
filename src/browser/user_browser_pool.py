#!/usr/bin/env python3
"""
User Browser Pool Manager
管理基于用户的浏览器实例，实现同一用户多个任务在不同标签页中执行
"""

import asyncio
import logging
import time
import weakref
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass, field
import hashlib
import threading

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from src.browser.custom_browser import CustomBrowser
from src.browser.custom_context import CustomBrowserContext

logger = logging.getLogger(__name__)

@dataclass
class UserBrowserInfo:
    """用户浏览器信息"""
    user_id: str
    browser: CustomBrowser
    context: CustomBrowserContext
    agent: Optional[Any] = None  # BrowserUseAgent实例
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    active_tasks: int = 0
    total_tasks: int = 0
    
    def update_last_used(self):
        """更新最后使用时间"""
        self.last_used = datetime.now()
    
    def add_task(self):
        """添加任务计数"""
        self.active_tasks += 1
        self.total_tasks += 1
        self.update_last_used()
    
    def remove_task(self):
        """移除任务计数"""
        if self.active_tasks > 0:
            self.active_tasks -= 1
        self.update_last_used()
    
    @property
    def is_idle(self) -> bool:
        """检查是否空闲（没有活跃任务）"""
        return self.active_tasks == 0
    
    @property
    def idle_duration(self) -> timedelta:
        """获取空闲时长"""
        return datetime.now() - self.last_used
    
    def set_agent(self, agent: Any):
        """设置agent实例"""
        self.agent = agent
    
    def has_agent(self) -> bool:
        """检查是否有有效的agent实例"""
        return self.agent is not None
    
    def clear_agent(self):
        """清理agent实例"""
        self.agent = None


class UserBrowserPool:
    """用户浏览器池管理器"""
    
    def __init__(self, 
                 browser_settings: Dict[str, Any],
                 max_idle_time: int = 1800,  # 30分钟空闲时间
                 cleanup_interval: int = 300,  # 5分钟清理间隔
                 max_browsers: int = 10):  # 最大浏览器数量
        
        self.browser_settings = browser_settings
        self.max_idle_time = max_idle_time
        self.cleanup_interval = cleanup_interval
        self.max_browsers = max_browsers
        
        # 用户浏览器池
        self.user_browsers: Dict[str, UserBrowserInfo] = {}
        
        # 线程锁，确保线程安全
        self._lock = asyncio.Lock()
        
        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        logger.info(f"UserBrowserPool initialized with max_idle_time={max_idle_time}s, "
                   f"cleanup_interval={cleanup_interval}s, max_browsers={max_browsers}")
    
    def _generate_user_id(self, request_headers: Dict[str, str], 
                         client_ip: str = None) -> str:
        """
        生成用户ID，支持多种识别方式
        优先级：Authorization > User-Agent + IP > IP > 默认
        """
        # 方法1: Authorization header (最高优先级)
        auth_header = request_headers.get('Authorization') or request_headers.get('authorization')
        if auth_header:
            # 使用Authorization header生成用户ID
            user_id = hashlib.md5(auth_header.encode()).hexdigest()[:12]
            logger.debug(f"Generated user_id from Authorization: {user_id}")
            return f"auth_{user_id}"
        
        # 方法2: User-Agent + IP (中等优先级)
        user_agent = request_headers.get('User-Agent') or request_headers.get('user-agent', '')
        if user_agent and client_ip:
            combined = f"{user_agent}_{client_ip}"
            user_id = hashlib.md5(combined.encode()).hexdigest()[:12]
            logger.debug(f"Generated user_id from User-Agent + IP: {user_id}")
            return f"ua_ip_{user_id}"
        
        # 方法3: 仅IP地址
        if client_ip:
            user_id = hashlib.md5(client_ip.encode()).hexdigest()[:12]
            logger.debug(f"Generated user_id from IP: {user_id}")
            return f"ip_{user_id}"
        
        # 方法4: 默认用户ID
        logger.warning("No user identification available, using default user_id")
        return "default_user"
    
    async def get_browser_for_user(self, request_headers: Dict[str, str], 
                                  client_ip: str = None) -> Tuple[CustomBrowser, CustomBrowserContext, str]:
        """
        获取或创建用户专属的浏览器实例
        返回: (browser, context, user_id)
        """
        async with self._lock:
            user_id = self._generate_user_id(request_headers, client_ip)
            
            # 检查是否已存在该用户的浏览器
            if user_id in self.user_browsers:
                browser_info = self.user_browsers[user_id]
                
                # 如果用户已有活跃的agent，需要检查浏览器进程是否仍然健康
                # 即使有agent，浏览器进程也可能已经死亡
                if browser_info.has_agent():
                    try:
                        # 先进行快速进程健康检查
                        browser_alive = await self._is_browser_process_alive(browser_info.browser)
                        context_alive = await self._is_context_alive(browser_info.context)
                        logger.debug(f"Health check for user {user_id}: browser_alive={browser_alive}, context_alive={context_alive}")
                        
                        if browser_alive and context_alive:
                            browser_info.add_task()
                            logger.info(f"Reusing browser for user {user_id} (has active agent), active_tasks: {browser_info.active_tasks}")
                            return browser_info.browser, browser_info.context, user_id
                        else:
                            # 浏览器或context不可用，需要清理并重建
                            logger.warning(f"🚨 Browser/context dead for user {user_id} (browser:{browser_alive}, context:{context_alive}) - rebuilding...")
                            await self._cleanup_user_browser(user_id)
                    except Exception as e:
                        # 进程检查失败，说明浏览器不可用
                        logger.warning(f"🚨 Browser process check failed for user {user_id}: {e} - rebuilding...")
                        await self._cleanup_user_browser(user_id)
                
                # 没有agent时进行完整的健康检查
                try:
                    # 先检查进程和context是否存活
                    browser_alive = await self._is_browser_process_alive(browser_info.browser)
                    context_alive = await self._is_context_alive(browser_info.context)
                    logger.debug(f"Health check for user {user_id} (no agent): browser_alive={browser_alive}, context_alive={context_alive}")
                    
                    if not browser_alive or not context_alive:
                        logger.warning(f"🚨 Browser/context dead for user {user_id} (browser:{browser_alive}, context:{context_alive}) - rebuilding...")
                        await self._cleanup_user_browser(user_id)
                    else:
                        # 如果进程和context都存活，就直接复用，不再做额外的健康检查
                        # 避免因为空闲连接等原因误判健康浏览器为不健康
                        browser_info.add_task()
                        logger.info(f"Reusing healthy browser for user {user_id}, active_tasks: {browser_info.active_tasks}")
                        return browser_info.browser, browser_info.context, user_id
                except Exception as e:
                    # 健康检查失败，检查是否是进程死亡导致的
                    error_msg = str(e)
                    if "NoneType" in error_msg and "send" in error_msg:
                        logger.warning(f"🚨 Browser process died during health check for user {user_id}: {e} - rebuilding...")
                        await self._cleanup_user_browser(user_id)
                    else:
                        # 其他错误，尝试重用但记录警告
                        logger.debug(f"Health check error for user {user_id}, but trying to reuse: {e}")
                        browser_info.add_task()
                        logger.info(f"Reusing browser for user {user_id} despite health check error, active_tasks: {browser_info.active_tasks}")
                        return browser_info.browser, browser_info.context, user_id
            
            # 检查是否达到最大浏览器数量限制
            if len(self.user_browsers) >= self.max_browsers:
                await self._cleanup_oldest_idle_browser()
            
            # 创建新的浏览器实例
            browser_info = await self._create_user_browser(user_id)
            self.user_browsers[user_id] = browser_info
            
            browser_info.add_task()
            logger.info(f"Created new browser for user {user_id}")
            return browser_info.browser, browser_info.context, user_id
    
    async def get_or_create_agent_for_user(self, user_id: str, task: str, 
                                           agent_factory_func) -> Tuple[Any, bool]:
        """
        获取或创建用户的agent实例
        返回: (agent, is_new_agent)
        
        修复策略说明:
        由于BrowserUseAgent不支持add_new_task方法，我们采用"浏览器复用 + Agent重建"的策略：
        1. 浏览器实例复用: 避免重新创建浏览器的开销，保持会话状态
        2. Agent实例重建: 为每个新任务创建新的Agent，确保任务独立性
        3. 任务正确执行: 新任务能正确执行，而不是继续旧任务
        """
        async with self._lock:
            if user_id not in self.user_browsers:
                logger.warning(f"No browser found for user {user_id}")
                return None, False
            
            browser_info = self.user_browsers[user_id]
            
            # 为每个新任务创建新的agent实例，但复用浏览器
            # 注意: 由于BrowserUseAgent不支持add_new_task方法，我们为每个新任务创建新的agent实例，
            # 但复用同一个浏览器实例，这样既保证了任务的独立性，又避免了浏览器重新创建的开销。
            
            # 清理旧的agent实例（如果存在）
            if browser_info.has_agent():
                logger.debug(f"Clearing previous agent for user {user_id} to create new one for new task")
                browser_info.clear_agent()
            
            # 在创建Agent前确保浏览器连接状态正常
            # 对于新创建的浏览器，跳过严格的连接验证，避免过早的验证失败
            try:
                # 简单检查：确保browser和context对象存在
                if not browser_info.browser or not browser_info.context:
                    raise Exception("Browser or context is None")
                logger.debug(f"Basic browser validation passed for user {user_id}")
                
                # 对于复用浏览器，跳过深度连接验证，避免干扰正常运行的浏览器
                # 基本的存在性检查已经足够，避免深度检查造成连接断开
                logger.debug(f"Skipping deep connection verification for browser reuse - user {user_id}")
                    
            except Exception as conn_e:
                logger.warning(f"Failed to ensure browser connection for user {user_id}: {conn_e}")
                # 连接修复失败，清理并重新创建浏览器
                await self._cleanup_user_browser(user_id)
                raise Exception(f"Browser connection failed and needs recreation: {conn_e}")
            
            # 创建新的agent实例
            try:
                # 关键修复：确保context的session状态在Agent创建前被正确初始化
                # 这防止Agent在get_state()时重新创建session，避免破坏浏览器连接
                if browser_info.context and hasattr(browser_info.context, 'session'):
                    if browser_info.context.session is None:
                        logger.debug(f"Context session is None for user {user_id}, pre-initializing session...")
                        try:
                            # 强制初始化session，确保它与现有浏览器状态兼容
                            session = await browser_info.context.get_session()
                            logger.info(f"✅ Pre-initialized context session for user {user_id}")
                            
                            # 验证session的有效性
                            if session and hasattr(session, 'context') and session.context:
                                pages = session.context.pages
                                logger.debug(f"Session has {len(pages)} pages for user {user_id}")
                            else:
                                logger.warning(f"Session initialization incomplete for user {user_id}")
                                
                        except Exception as session_init_e:
                            logger.error(f"Failed to pre-initialize context session for user {user_id}: {session_init_e}")
                            # 如果session初始化失败，这表明浏览器连接有问题，应该重新创建
                            error_msg = str(session_init_e)
                            if ("Target page, context or browser has been closed" in error_msg or 
                                "Browser process" in error_msg or "connection was lost" in error_msg):
                                logger.warning(f"Browser connection lost during session init for user {user_id}, cleaning up...")
                                await self._cleanup_user_browser(user_id)
                                raise Exception(f"Browser connection lost during session initialization: {session_init_e}")
                            else:
                                # 其他错误，记录但继续，让Agent自己处理
                                logger.warning(f"Non-fatal session init error for user {user_id}: {session_init_e}")
                    else:
                        logger.debug(f"Context session already exists for user {user_id}")
                
                agent = await agent_factory_func(browser_info.browser, browser_info.context)
                
                # 验证Agent的browser_context连接状态
                try:
                    # 确保Agent能正常获取当前页面，这是基本的连接验证
                    current_page = await agent.browser_context.get_agent_current_page()
                    logger.debug(f"Agent browser connection verified for user {user_id}, current page: {current_page.url}")
                except Exception as verify_e:
                    logger.warning(f"Agent browser connection verification failed for user {user_id}: {verify_e}")
                    # 连接验证失败，但不阻止Agent创建，让Agent自己处理连接问题
                
                browser_info.set_agent(agent)
                logger.info(f"Created new agent for user {user_id} for task: {task[:50]}...")
                return agent, True
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to create agent for user {user_id}: {e}")
                
                # 检查是否是进程死亡导致的Agent创建失败
                if "NoneType" in error_msg and "send" in error_msg:
                    logger.warning(f"🚨 Agent creation failed due to browser process death for user {user_id}")
                elif "Target page, context or browser has been closed" in error_msg:
                    logger.warning(f"🚨 Agent creation failed due to browser/context closed for user {user_id}")
                elif "Browser process quit" in error_msg or "did the browser process quit" in error_msg:
                    logger.warning(f"🚨 Agent creation failed due to browser process quit for user {user_id}")
                
                # 如果Agent创建失败，可能是浏览器连接问题，清理浏览器
                await self._cleanup_user_browser(user_id)
                raise

    async def release_browser_for_user(self, user_id: str):
        """释放用户浏览器任务计数"""
        async with self._lock:
            if user_id in self.user_browsers:
                browser_info = self.user_browsers[user_id]
                browser_info.remove_task()
                logger.debug(f"Released task for user {user_id}, active_tasks: {browser_info.active_tasks}")
    
    async def clear_agent_for_user(self, user_id: str):
        """清理用户的agent，保留浏览器实例以便重用"""
        async with self._lock:
            if user_id in self.user_browsers:
                browser_info = self.user_browsers[user_id]
                if browser_info.has_agent():
                    browser_info.clear_agent()
                    logger.debug(f"Cleared agent for user {user_id} to allow browser reuse")
    
    async def _create_user_browser(self, user_id: str) -> UserBrowserInfo:
        """创建新的用户浏览器实例"""
        try:
            # 创建浏览器配置
            browser_config = BrowserConfig(
                headless=self.browser_settings.get('headless', False),
                disable_security=self.browser_settings.get('disable_security', True),
                browser_binary_path=self.browser_settings.get('chrome_instance_path'),
                extra_browser_args=self._get_extra_browser_args(),
                new_context_config=BrowserContextConfig(
                    window_width=self.browser_settings.get('window_width', 1280),
                    window_height=self.browser_settings.get('window_height', 720),
                )
            )
            
            # 创建浏览器实例
            browser = CustomBrowser(config=browser_config)
            
            # 创建浏览器上下文
            context_config = BrowserContextConfig(
                downloads_path="./tmp/downloads",
                save_recording_path=self.browser_settings.get('save_recording_path'),
                window_width=self.browser_settings.get('window_width', 1280),
                window_height=self.browser_settings.get('window_height', 720),
            )
            
            context = await browser.new_context(context_config)
            
            # 验证浏览器初始化完成
            try:
                # 简单验证浏览器状态，确保正确初始化
                if hasattr(browser, '_browser') and browser._browser is None:
                    logger.warning(f"Browser _browser attribute not initialized for user {user_id}")
                
                # 验证context可用性
                if context and hasattr(context, 'session') and context.session:
                    logger.debug(f"Browser initialization verified for user {user_id}")
                else:
                    logger.warning(f"Context initialization issue for user {user_id}")
                    
            except Exception as init_e:
                logger.debug(f"Browser initialization check failed (non-fatal): {init_e}")
            
            browser_info = UserBrowserInfo(
                user_id=user_id,
                browser=browser,
                context=context
            )
            
            logger.info(f"Successfully created browser for user {user_id}")
            return browser_info
            
        except Exception as e:
            logger.error(f"Failed to create browser for user {user_id}: {e}")
            raise
    
    def _get_extra_browser_args(self) -> List[str]:
        """获取额外的浏览器启动参数"""
        extra_args = []
        
        user_agent = self.browser_settings.get('user_agent')
        if user_agent:
            extra_args.append(f'--user-agent={user_agent}')
        
        return extra_args
    
    async def _is_browser_healthy(self, browser: CustomBrowser) -> bool:
        """检查浏览器是否健康"""
        try:
            # 更宽松的健康检查：只要浏览器对象存在就认为是健康的
            # 避免因为连接空闲而误判浏览器不健康
            if hasattr(browser, '_browser') and browser._browser:
                try:
                    # 尝试检查连接状态，但不作为唯一依据
                    if hasattr(browser._browser, 'is_connected'):
                        is_connected = browser._browser.is_connected()
                        logger.debug(f"Browser connection status: {is_connected}")
                        # 即使连接断开，也给浏览器一个重新连接的机会
                        return True
                    return True
                except Exception as conn_e:
                    logger.debug(f"Browser connection check failed, but treating as healthy: {conn_e}")
                    # 连接检查失败也不一定意味着浏览器不可用，可能只是空闲
                    return True
            return False
        except Exception as e:
            logger.debug(f"Browser health check failed: {e}")
            return False
    
    async def _is_browser_process_alive(self, browser) -> bool:
        """快速检测浏览器进程是否存活（只检测进程，不检测连接状态）"""
        try:
            if not browser:
                return False
            
            # 获取底层的playwright浏览器实例
            playwright_browser = await browser.get_playwright_browser()
            if not playwright_browser:
                return False
            
            # 使用 playwright_browser.version 作为进程存活的快速检测
            # 访问这个属性如果进程死亡会立即失败
            _ = playwright_browser.version
            return True
        except Exception as e:
            error_msg = str(e)
            # 检测进程死亡的特征错误
            if "NoneType" in error_msg and "send" in error_msg:
                logger.debug(f"Browser process dead (NoneType send): {error_msg}")
                return False
            elif "did the browser process quit" in error_msg:
                logger.debug(f"Browser process quit: {error_msg}")
                return False
            elif "Target page, context or browser has been closed" in error_msg:
                logger.debug(f"Browser closed: {error_msg}")
                return False
            elif "Connection closed" in error_msg or "connection was lost" in error_msg:
                logger.debug(f"Browser connection lost: {error_msg}")
                return False
            elif "ERR_CONNECTION_REFUSED" in error_msg or "Connection refused" in error_msg:
                logger.debug(f"Browser connection refused: {error_msg}")
                return False
            elif "timeout" in error_msg.lower():
                logger.debug(f"Browser connection timeout: {error_msg}")
                return False
            else:
                # 对于未知错误，保守地认为浏览器已死亡，避免使用坏连接
                logger.warning(f"Browser process check failed with unknown error (treating as dead): {error_msg}")
                return False
    
    async def _is_context_alive(self, context) -> bool:
        """检查浏览器context是否可用"""
        try:
            if not context:
                return False
            
            # 尝试获取context中的页面列表
            if hasattr(context, 'session') and context.session:
                pages = context.session.context.pages
            else:
                # 如果没有session，context可能未初始化
                return False
            if pages is None:
                return False
            
            # 如果有页面，尝试检查第一个页面的状态
            if len(pages) > 0:
                page = pages[0]
                try:
                    # 尝试获取页面URL，这是一个轻量级的检查
                    _ = page.url
                    return True
                except Exception as page_e:
                    logger.debug(f"Context page check failed: {page_e}")
                    return False
            else:
                # 没有页面可能表示context失效，尝试创建一个新页面来测试
                try:
                    test_page = await context.session.context.new_page()
                    await test_page.close()
                    return True
                except Exception as new_page_e:
                    logger.debug(f"Context test page creation failed: {new_page_e}")
                    return False
        except Exception as e:
            error_msg = str(e)
            # 检测context死亡的特征错误
            if "Target page, context or browser has been closed" in error_msg:
                logger.debug(f"Context has been closed: {error_msg}")
                return False
            elif "NoneType" in error_msg:
                logger.debug(f"Context object is None: {error_msg}")
                return False
            elif "Connection closed" in error_msg or "connection was lost" in error_msg:
                logger.debug(f"Context connection lost: {error_msg}")
                return False
            elif "context was closed" in error_msg or "context is closed" in error_msg:
                logger.debug(f"Context explicitly closed: {error_msg}")
                return False
            else:
                logger.debug(f"Context health check failed: {error_msg}")
                return False
    
    async def _ensure_browser_connection(self, browser_info: UserBrowserInfo):
        """确保浏览器连接可用，尝试修复断开的连接"""
        try:
            # 尝试访问浏览器对象来验证连接
            browser = browser_info.browser
            context = browser_info.context
            
            # 检查浏览器对象是否存在
            if not browser:
                raise Exception("Browser object is None")
            
            # 深度进程健康检查：检测底层浏览器进程是否存活
            try:
                # 通过访问 playwright_browser.version 属性来检测进程状态
                playwright_browser = await browser.get_playwright_browser()
                version_info = playwright_browser.version
                logger.debug(f"Browser process is alive for user {browser_info.user_id}: {version_info}")
            except Exception as process_e:
                # 检测进程死亡的特征错误
                error_msg = str(process_e)
                if "NoneType" in error_msg and "send" in error_msg:
                    logger.error(f"🚨 Browser process has died for user {browser_info.user_id}: {error_msg}")
                    raise Exception(f"Browser process died - needs complete recreation: {error_msg}")
                elif "did the browser process quit" in error_msg:
                    logger.error(f"🚨 Browser process quit detected for user {browser_info.user_id}: {error_msg}")
                    raise Exception(f"Browser process quit - needs complete recreation: {error_msg}")
                elif "Target page, context or browser has been closed" in error_msg:
                    logger.error(f"🚨 Browser has been closed for user {browser_info.user_id}: {error_msg}")
                    raise Exception(f"Browser closed - needs complete recreation: {error_msg}")
                else:
                    logger.warning(f"⚠️ Browser process check warning for user {browser_info.user_id}: {error_msg}")
                    # 非致命错误，继续检查context
            
            # 检查context是否可用
            if not context or not hasattr(context, 'session') or not context.session:
                logger.info(f"Browser context invalid for user {browser_info.user_id}, recreating context...")
                
                try:
                    # 重新创建context
                    context_config = BrowserContextConfig(
                        downloads_path="./tmp/downloads",
                        save_recording_path=self.browser_settings.get('save_recording_path'),
                        window_width=self.browser_settings.get('window_width', 1280),
                        window_height=self.browser_settings.get('window_height', 720),
                    )
                    
                    browser_info.context = await browser.new_context(context_config)
                    logger.info(f"✅ Successfully recreated context for user {browser_info.user_id}")
                except Exception as context_error:
                    # 如果context创建失败，检查是否是进程死亡导致的
                    error_msg = str(context_error)
                    if "NoneType" in error_msg and "send" in error_msg:
                        logger.error(f"🚨 Cannot create context - browser process dead for user {browser_info.user_id}")
                        raise Exception(f"Browser process died during context creation: {context_error}")
                    else:
                        logger.error(f"❌ Context creation failed for user {browser_info.user_id}: {context_error}")
                        raise context_error
            
            # 尝试获取页面列表来验证连接
            try:
                if browser_info.context and hasattr(browser_info.context, 'session') and browser_info.context.session:
                    pages = browser_info.context.session.context.pages
                    logger.debug(f"Browser has {len(pages)} active pages for user {browser_info.user_id}")
                else:
                    logger.debug(f"Context validation skipped for user {browser_info.user_id}")
            except Exception as page_e:
                error_msg = str(page_e)
                if "NoneType" in error_msg and "send" in error_msg:
                    logger.error(f"🚨 Page access failed - browser process dead for user {browser_info.user_id}")
                    raise Exception(f"Browser process died during page access: {page_e}")
                else:
                    logger.debug(f"Cannot access pages, but browser seems intact: {page_e}")
                
            logger.debug(f"✅ Browser connection verified for user {browser_info.user_id}")
            
        except Exception as e:
            logger.warning(f"❌ Browser connection verification failed for user {browser_info.user_id}: {e}")
            raise
    
    async def _cleanup_user_browser(self, user_id: str):
        """清理指定用户的浏览器，即使进程已死亡也能正确清理"""
        if user_id not in self.user_browsers:
            return
        
        browser_info = self.user_browsers[user_id]
        cleanup_errors = []
        
        try:
            # 清理agent
            if browser_info.has_agent():
                try:
                    browser_info.clear_agent()
                    logger.debug(f"✅ Cleared agent for user {user_id}")
                except Exception as agent_e:
                    cleanup_errors.append(f"Agent cleanup failed: {agent_e}")
                    logger.warning(f"⚠️ Agent cleanup failed for user {user_id}: {agent_e}")
            
            # 关闭浏览器上下文 - 即使进程死亡也尝试清理
            if browser_info.context:
                try:
                    await browser_info.context.close()
                    logger.debug(f"✅ Closed context for user {user_id}")
                except Exception as context_e:
                    error_msg = str(context_e)
                    if "NoneType" in error_msg and "send" in error_msg:
                        logger.debug(f"🔄 Context already closed (process dead) for user {user_id}")
                    else:
                        cleanup_errors.append(f"Context cleanup failed: {context_e}")
                        logger.warning(f"⚠️ Context cleanup failed for user {user_id}: {context_e}")
            
            # 关闭浏览器 - 即使进程死亡也尝试清理
            if browser_info.browser:
                try:
                    await browser_info.browser.close()
                    logger.debug(f"✅ Closed browser for user {user_id}")
                except Exception as browser_e:
                    error_msg = str(browser_e)
                    if "NoneType" in error_msg and "send" in error_msg:
                        logger.debug(f"🔄 Browser already closed (process dead) for user {user_id}")
                    elif "did the browser process quit" in error_msg:
                        logger.debug(f"🔄 Browser process already quit for user {user_id}")
                    else:
                        cleanup_errors.append(f"Browser cleanup failed: {browser_e}")
                        logger.warning(f"⚠️ Browser cleanup failed for user {user_id}: {browser_e}")
            
            # 等待一小段时间让所有清理任务完成
            await asyncio.sleep(0.1)
            
            if cleanup_errors:
                logger.warning(f"⚠️ Cleanup completed with warnings for user {user_id}: {', '.join(cleanup_errors)}")
            else:
                logger.info(f"✅ Successfully cleaned up browser for user {user_id}")
            
        except Exception as e:
            error_msg = str(e)
            # 忽略常见的事件循环关闭相关错误
            if "Event loop is closed" in error_msg or "RuntimeError" in error_msg:
                logger.debug(f"🔄 Event loop cleanup warning for user {user_id}: {e}")
            else:
                logger.error(f"❌ Unexpected error during cleanup for user {user_id}: {e}")
        finally:
            # 无论如何都要从池中移除，防止资源泄露
            del self.user_browsers[user_id]
            logger.debug(f"🗑️ Removed user {user_id} from browser pool")
    
    async def _cleanup_oldest_idle_browser(self):
        """清理最旧的空闲浏览器"""
        idle_browsers = [
            (user_id, info) for user_id, info in self.user_browsers.items()
            if info.is_idle
        ]
        
        if not idle_browsers:
            logger.warning("No idle browsers to cleanup, but max limit reached")
            return
        
        # 按最后使用时间排序，清理最旧的
        idle_browsers.sort(key=lambda x: x[1].last_used)
        oldest_user_id, _ = idle_browsers[0]
        
        logger.info(f"Cleaning up oldest idle browser for user {oldest_user_id}")
        await self._cleanup_user_browser(oldest_user_id)
    
    async def start_cleanup_task(self):
        """启动定期清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Started browser pool cleanup task")
    
    async def _periodic_cleanup(self):
        """定期清理空闲浏览器"""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_idle_browsers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
    
    async def _cleanup_idle_browsers(self):
        """清理超时的空闲浏览器"""
        async with self._lock:
            current_time = datetime.now()
            users_to_cleanup = []
            
            for user_id, browser_info in self.user_browsers.items():
                if (browser_info.is_idle and 
                    browser_info.idle_duration.total_seconds() > self.max_idle_time):
                    users_to_cleanup.append(user_id)
            
            for user_id in users_to_cleanup:
                logger.info(f"Cleaning up idle browser for user {user_id} "
                           f"(idle for {self.user_browsers[user_id].idle_duration})")
                await self._cleanup_user_browser(user_id)
    
    async def shutdown(self):
        """关闭浏览器池"""
        logger.info("Shutting down UserBrowserPool...")
        
        try:
            # 停止清理任务
            self._shutdown_event.set()
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"🔄 Cleanup task cancellation warning: {e}")
            
            # 清理所有浏览器
            async with self._lock:
                user_ids = list(self.user_browsers.keys())
                for user_id in user_ids:
                    try:
                        await self._cleanup_user_browser(user_id)
                    except Exception as e:
                        error_msg = str(e)
                        if "Event loop is closed" in error_msg:
                            logger.debug(f"🔄 Event loop already closed during shutdown for user {user_id}")
                        else:
                            logger.warning(f"⚠️ Error during shutdown cleanup for user {user_id}: {e}")
            
            logger.info("UserBrowserPool shutdown completed")
            
        except Exception as e:
            error_msg = str(e)
            if "Event loop is closed" in error_msg:
                logger.debug("🔄 Event loop already closed during UserBrowserPool shutdown")
            else:
                logger.error(f"❌ Error during UserBrowserPool shutdown: {e}")
    
    def get_pool_status(self) -> Dict[str, Any]:
        """获取浏览器池状态"""
        status = {
            'total_browsers': len(self.user_browsers),
            'max_browsers': self.max_browsers,
            'browsers': {}
        }
        
        for user_id, browser_info in self.user_browsers.items():
            status['browsers'][user_id] = {
                'created_at': browser_info.created_at.isoformat(),
                'last_used': browser_info.last_used.isoformat(),
                'active_tasks': browser_info.active_tasks,
                'total_tasks': browser_info.total_tasks,
                'is_idle': browser_info.is_idle,
                'idle_duration_seconds': browser_info.idle_duration.total_seconds(),
                'has_agent': browser_info.has_agent()
            }
        
        return status
