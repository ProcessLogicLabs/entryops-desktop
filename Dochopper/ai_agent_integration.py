"""
AI Agent Integration - Bridges the existing DocHopper UI with the new agent system
Provides the AgentManager class that handles the full agentic loop.
"""

import os
import sys
import json
import sqlite3
import threading
from typing import Optional, Dict, Any, Callable
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal, QThread

# Import agent core components
from ai_agent_core import (
    ConversationManager, ToolExecutor, ContextBuilder, AgentLoop,
    ToolCall, ToolResult, DEFAULT_SYSTEM_PROMPT
)
from ai_agent_tools import ToolRegistry, register_all_tools


class AgentWorkerThread(QThread):
    """Worker thread for running the agent loop without blocking UI."""

    # Signals for UI updates
    text_received = pyqtSignal(str)  # Assistant text response
    tool_started = pyqtSignal(str, dict)  # tool_name, tool_input
    tool_completed = pyqtSignal(str, dict, dict)  # tool_name, tool_input, tool_result
    iteration_complete = pyqtSignal(int)  # iteration number
    finished_signal = pyqtSignal(dict)  # final result dict
    error_signal = pyqtSignal(str)  # error message
    code_changed = pyqtSignal(str)  # template code changed by tool

    def __init__(self, agent_loop: AgentLoop, message: str, parent=None):
        super().__init__(parent)
        self.agent_loop = agent_loop
        self.message = message
        self._cancelled = False

    def run(self):
        """Run the agent loop in the background thread."""
        try:
            # Set up callbacks that emit signals
            def on_text(text):
                if not self._cancelled:
                    self.text_received.emit(text)

            def on_tool_start(tc: ToolCall):
                if not self._cancelled:
                    self.tool_started.emit(tc.name, tc.input)

            def on_tool_result(tc: ToolCall, tr: ToolResult):
                if not self._cancelled:
                    result_dict = {
                        "content": tr.content,
                        "is_error": tr.is_error
                    }
                    self.tool_completed.emit(tc.name, tc.input, result_dict)

            def on_iteration(n):
                if not self._cancelled:
                    self.iteration_complete.emit(n)

            def on_error(err):
                if not self._cancelled:
                    self.error_signal.emit(err)

            self.agent_loop.on_assistant_text = on_text
            self.agent_loop.on_tool_start = on_tool_start
            self.agent_loop.on_tool_result = on_tool_result
            self.agent_loop.on_iteration_complete = on_iteration
            self.agent_loop.on_error = on_error

            result = self.agent_loop.run(self.message)
            if not self._cancelled:
                self.finished_signal.emit(result)

        except Exception as e:
            if not self._cancelled:
                self.error_signal.emit(str(e))

    def cancel(self):
        """Cancel the agent loop."""
        self._cancelled = True


class AgentManager(QObject):
    """
    Manages the full agent experience for the AI Template Assistant.
    Handles conversation, tool execution, and UI integration.
    """

    # Signals for UI updates
    assistant_text = pyqtSignal(str)
    tool_started = pyqtSignal(str, dict)  # tool_name, tool_input
    tool_completed = pyqtSignal(str, dict, dict)  # tool_name, input, result
    agent_finished = pyqtSignal(dict)
    agent_error = pyqtSignal(str)
    code_changed = pyqtSignal(str)  # emitted when tool changes template code

    def __init__(self, parent=None):
        super().__init__(parent)

        # Core components
        self.conversation = ConversationManager()
        self.tool_executor = ToolExecutor()
        self.context = ContextBuilder()
        self.tool_registry = ToolRegistry()

        # API client (set by set_api_client)
        self.api_client = None
        self.model = "claude-sonnet-4-20250514"

        # Agent loop (created on demand)
        self.agent_loop: Optional[AgentLoop] = None
        self.worker_thread: Optional[AgentWorkerThread] = None

        # State
        self._current_template_code = ""
        self._invoice_text = ""
        self._invoice_path = ""
        self._invoice_tables = []
        self._invoice_page_texts = []
        self._db_connection = None

        # Set up tools
        self._setup_tools()

    def _setup_tools(self):
        """Initialize and register all tools."""
        # Set up context callbacks
        self.tool_registry.set_context("current_template_code", self._current_template_code)
        self.tool_registry.set_context("set_template_code_callback", self._on_tool_code_change)
        self.tool_registry.set_context("invoice_text", self._invoice_text)
        self.tool_registry.set_context("invoice_path", self._invoice_path)
        self.tool_registry.set_context("invoice_tables", self._invoice_tables)
        self.tool_registry.set_context("invoice_page_texts", self._invoice_page_texts)
        self.tool_registry.set_context("db_connection", self._db_connection)

        # Register tools
        register_all_tools(self.tool_executor, self.tool_registry)

        # Set system prompt
        self.context.set_system_prompt(DEFAULT_SYSTEM_PROMPT)

    def _on_tool_code_change(self, new_code: str):
        """Called when a tool changes the template code (legacy, not used in threaded mode)."""
        self._current_template_code = new_code
        self.tool_registry.set_context("current_template_code", new_code)
        self.code_changed.emit(new_code)

    def _on_worker_code_changed(self, new_code: str):
        """Handle code change signal from worker thread - this runs in main thread."""
        self._current_template_code = new_code
        self.tool_registry.set_context("current_template_code", new_code)
        self.code_changed.emit(new_code)

    def set_api_client(self, client, model: str = None):
        """Set the API client to use for requests."""
        self.api_client = client
        if model:
            self.model = model

    def set_model(self, model: str):
        """Set the model to use."""
        self.model = model

    def set_template_code(self, code: str):
        """Set the current template code."""
        self._current_template_code = code
        self.tool_registry.set_context("current_template_code", code)
        self.context.set_template_code(code)

    def set_invoice(self, text: str, path: str = "", tables: list = None, page_texts: list = None):
        """Set the loaded invoice data."""
        self._invoice_text = text
        self._invoice_path = path
        self._invoice_tables = tables or []
        self._invoice_page_texts = page_texts or []

        self.tool_registry.set_context("invoice_text", text)
        self.tool_registry.set_context("invoice_path", path)
        self.tool_registry.set_context("invoice_tables", self._invoice_tables)
        self.tool_registry.set_context("invoice_page_texts", self._invoice_page_texts)

        self.context.set_invoice(text, path)

    def set_database_connection(self, connection):
        """Set the database connection for query tools."""
        self._db_connection = connection
        self.tool_registry.set_context("db_connection", connection)

    def send_message(self, message: str):
        """
        Send a message and run the agent loop.
        Results are emitted via signals.
        """
        if not self.api_client:
            self.agent_error.emit("No API client configured")
            return

        # Check if already running
        if self.is_running():
            self.agent_error.emit("Agent is already processing a request")
            return

        # Clean up previous worker thread if it exists
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None

        # Create agent loop
        self.agent_loop = AgentLoop(
            api_client=self.api_client,
            conversation=self.conversation,
            tool_executor=self.tool_executor,
            context=self.context,
            model=self.model
        )

        # Create and start worker thread
        self.worker_thread = AgentWorkerThread(self.agent_loop, message)
        self.worker_thread.text_received.connect(self.assistant_text.emit)
        self.worker_thread.tool_started.connect(self.tool_started.emit)
        self.worker_thread.tool_completed.connect(self.tool_completed.emit)
        self.worker_thread.finished_signal.connect(self._on_agent_finished)
        self.worker_thread.error_signal.connect(self.agent_error.emit)
        self.worker_thread.code_changed.connect(self._on_worker_code_changed)

        # Update the callback to use the worker thread's signal
        # This ensures thread-safe communication
        self.tool_registry.set_context("set_template_code_callback", self.worker_thread.code_changed.emit)

        self.worker_thread.start()

    def _on_agent_finished(self, result: dict):
        """Handle agent loop completion."""
        # Clean up worker thread reference
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None
        self.agent_finished.emit(result)

    def cancel(self):
        """Cancel the current agent request."""
        if self.worker_thread:
            self.worker_thread.cancel()
            self.worker_thread = None

    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self.worker_thread is not None and self.worker_thread.isRunning()

    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation.clear()

    def get_conversation_history(self) -> list:
        """Get conversation history for saving/loading."""
        return [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp
            }
            for msg in self.conversation.messages
        ]


def create_anthropic_client(api_key: str):
    """Create an Anthropic API client."""
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        raise ImportError("anthropic package not installed")


def create_openai_client(api_key: str):
    """Create an OpenAI API client."""
    try:
        import openai
        return openai.OpenAI(api_key=api_key)
    except ImportError:
        raise ImportError("openai package not installed")


# Model mapping for different providers
ANTHROPIC_MODELS = {
    "Claude 3.5 Sonnet": "claude-sonnet-4-20250514",
    "Claude 3 Opus": "claude-3-opus-20240229",
    "Claude 3 Haiku": "claude-3-haiku-20240307",
    "Claude 3.5 Haiku": "claude-3-5-haiku-20241022",
}

OPENAI_MODELS = {
    "GPT-4o": "gpt-4o",
    "GPT-4o Mini": "gpt-4o-mini",
    "GPT-4 Turbo": "gpt-4-turbo",
}
