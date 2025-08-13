import json
from collections.abc import Generator
from typing import TYPE_CHECKING
import os
import gradio as gr
from datetime import datetime
from typing import Optional, Dict, List
import uuid
import asyncio
import time

from gradio.components import Component
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.agent.service import Agent
from src.browser.custom_browser import CustomBrowser
from src.browser.custom_context import CustomBrowserContext
from src.controller.custom_controller import CustomController
from src.agent.deep_research.deep_research_agent import DeepResearchAgent


class WebuiManager:
    def __init__(self, settings_save_dir: str = "./tmp/webui_settings"):
        self.id_to_component: dict[str, Component] = {}
        self.component_to_id: dict[Component, str] = {}

        self.settings_save_dir = settings_save_dir
        os.makedirs(self.settings_save_dir, exist_ok=True)

    def init_browser_use_agent(self) -> None:
        """
        init browser use agent
        """
        self.bu_agent: Optional[Agent] = None
        self.bu_browser: Optional[CustomBrowser] = None
        self.bu_browser_context: Optional[CustomBrowserContext] = None
        self.bu_controller: Optional[CustomController] = None
        self.bu_chat_history: List[Dict[str, Optional[str]]] = []
        self.bu_response_event: Optional[asyncio.Event] = None
        self.bu_user_help_response: Optional[str] = None
        self.bu_current_task: Optional[asyncio.Task] = None
        self.bu_agent_task_id: Optional[str] = None

    def init_deep_research_agent(self) -> None:
        """
        init deep research agent
        """
        self.dr_agent: Optional[DeepResearchAgent] = None
        self.dr_current_task = None
        self.dr_agent_task_id: Optional[str] = None
        self.dr_save_dir: Optional[str] = None

    async def initialize_browser(self, browser_settings: Dict[str, any]) -> None:
        """
        Initialize browser instance with given settings
        """
        try:
            # Close existing browser if it exists
            # Clean up existing browser resources
            await self._cleanup_browser_resources()
            
            # Extract browser settings
            headless = browser_settings.get('headless', False)
            disable_security = browser_settings.get('disable_security', True)
            browser_binary_path = browser_settings.get('chrome_instance_path')
            user_agent = browser_settings.get('user_agent')
            window_width = browser_settings.get('window_width', 1280)
            window_height = browser_settings.get('window_height', 720)
            save_recording_path = browser_settings.get('save_recording_path')
            
            # Prepare extra browser args
            extra_args = []
            if user_agent:
                extra_args.append(f'--user-agent={user_agent}')
            
            # Create browser configuration
            browser_config = BrowserConfig(
                headless=headless,
                disable_security=disable_security,
                browser_binary_path=browser_binary_path,
                extra_browser_args=extra_args,
                new_context_config=BrowserContextConfig(
                    window_width=window_width,
                    window_height=window_height,
                )
            )
            
            # Initialize browser
            self.bu_browser = CustomBrowser(config=browser_config)
            
            # Create tmp directories if they don't exist
            downloads_path = "./tmp/downloads"
            os.makedirs(downloads_path, exist_ok=True)
            
            # Create browser context
            context_config = BrowserContextConfig(
                save_downloads_path=downloads_path,
                window_height=window_height,
                window_width=window_width,
                force_new_context=True,
                save_recording_path=save_recording_path,
            )
            
            # Create browser context (browser will auto-start when needed)
            self.bu_browser_context = await self.bu_browser.new_context(config=context_config)
            
        except Exception as e:
            # Clean up on error
            if hasattr(self, 'bu_browser') and self.bu_browser:
                try:
                    await self.bu_browser.close()
                except:
                    pass
                self.bu_browser = None
            
            if hasattr(self, 'bu_browser_context') and self.bu_browser_context:
                try:
                    await self.bu_browser_context.close()
                except:
                    pass
                self.bu_browser_context = None
            
            raise Exception(f"Failed to initialize browser: {str(e)}")

    async def _cleanup_browser_resources(self):
        """Clean up existing browser resources gracefully"""
        try:
            # Close browser context first
            if hasattr(self, 'bu_browser_context') and self.bu_browser_context:
                try:
                    logger.debug("Closing existing browser context...")
                    await self.bu_browser_context.close()
                except Exception as e:
                    logger.warning(f"Error closing browser context: {e}")
                finally:
                    self.bu_browser_context = None
            
            # Then close browser
            if hasattr(self, 'bu_browser') and self.bu_browser:
                try:
                    logger.debug("Closing existing browser...")
                    await self.bu_browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")
                finally:
                    self.bu_browser = None
                    
            # Small delay to ensure cleanup is complete
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Error during browser cleanup: {e}")

    def add_components(self, tab_name: str, components_dict: dict[str, "Component"]) -> None:
        """
        Add tab components
        """
        for comp_name, component in components_dict.items():
            comp_id = f"{tab_name}.{comp_name}"
            self.id_to_component[comp_id] = component
            self.component_to_id[component] = comp_id

    def get_components(self) -> list["Component"]:
        """
        Get all components
        """
        return list(self.id_to_component.values())

    def get_component_by_id(self, comp_id: str) -> "Component":
        """
        Get component by id
        """
        return self.id_to_component[comp_id]

    def get_id_by_component(self, comp: "Component") -> str:
        """
        Get id by component
        """
        return self.component_to_id[comp]

    def save_config(self, components: Dict["Component", str]) -> None:
        """
        Save config
        """
        cur_settings = {}
        for comp in components:
            if not isinstance(comp, gr.Button) and not isinstance(comp, gr.File) and str(
                    getattr(comp, "interactive", True)).lower() != "false":
                comp_id = self.get_id_by_component(comp)
                cur_settings[comp_id] = components[comp]

        config_name = datetime.now().strftime("%Y%m%d-%H%M%S")
        with open(os.path.join(self.settings_save_dir, f"{config_name}.json"), "w") as fw:
            json.dump(cur_settings, fw, indent=4)

        return os.path.join(self.settings_save_dir, f"{config_name}.json")

    def load_config(self, config_path: str):
        """
        Load config
        """
        with open(config_path, "r") as fr:
            ui_settings = json.load(fr)

        update_components = {}
        for comp_id, comp_val in ui_settings.items():
            if comp_id in self.id_to_component:
                comp = self.id_to_component[comp_id]
                if comp.__class__.__name__ == "Chatbot":
                    update_components[comp] = comp.__class__(value=comp_val, type="messages")
                else:
                    update_components[comp] = comp.__class__(value=comp_val)
                    if comp_id == "agent_settings.planner_llm_provider":
                        yield update_components  # yield provider, let callback run
                        time.sleep(0.1)  # wait for Gradio UI callback

        config_status = self.id_to_component["load_save_config.config_status"]
        update_components.update(
            {
                config_status: config_status.__class__(value=f"Successfully loaded config: {config_path}")
            }
        )
        yield update_components
