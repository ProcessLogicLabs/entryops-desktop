"""
AI Agent Core - Claude Code-like agentic experience for EntryOps
Provides conversation management, tool execution, and agent loop.
"""

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import copy


class MessageRole(Enum):
    """Message roles in conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


@dataclass
class ToolCall:
    """Represents a tool invocation request from the AI."""
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class ToolResult:
    """Represents the result of a tool execution."""
    tool_use_id: str
    content: Any
    is_error: bool = False

    def to_api_format(self) -> Dict:
        """Convert to Anthropic API format."""
        result = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
        }
        if self.is_error:
            result["is_error"] = True
            result["content"] = str(self.content)
        else:
            result["content"] = json.dumps(self.content) if not isinstance(self.content, str) else self.content
        return result


@dataclass
class Message:
    """A message in the conversation."""
    role: MessageRole
    content: Any  # str for user/assistant, list for tool results
    tool_calls: List[ToolCall] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_api_format(self) -> Dict:
        """Convert to Anthropic API format."""
        if self.role == MessageRole.TOOL_RESULT:
            return {
                "role": "user",
                "content": self.content  # Already formatted as tool results
            }

        # For assistant messages with tool calls, format content as list with
        # text block(s) and tool_use blocks
        if self.role == MessageRole.ASSISTANT and self.tool_calls:
            content = []
            # Add text block if there's text content
            if self.content:
                content.append({
                    "type": "text",
                    "text": self.content
                })
            # Add tool_use blocks for each tool call
            for tc in self.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input
                })
            return {
                "role": "assistant",
                "content": content
            }

        return {
            "role": self.role.value,
            "content": self.content
        }


@dataclass
class Checkpoint:
    """A conversation checkpoint for rewind functionality."""
    id: str
    messages: List[Message]
    template_code: str
    timestamp: float = field(default_factory=time.time)
    description: str = ""


class ConversationManager:
    """Manages conversation history and checkpoints."""

    def __init__(self, max_history: int = 50):
        self.messages: List[Message] = []
        self.checkpoints: List[Checkpoint] = []
        self.max_history = max_history
        self._checkpoint_counter = 0

    def add_message(self, role: MessageRole, content: Any,
                    tool_calls: List[ToolCall] = None) -> Message:
        """Add a message to the conversation."""
        msg = Message(
            role=role,
            content=content,
            tool_calls=tool_calls or []
        )
        self.messages.append(msg)

        # Trim old messages if needed
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]

        return msg

    def add_user_message(self, content: str) -> Message:
        """Add a user message."""
        return self.add_message(MessageRole.USER, content)

    def add_assistant_message(self, content: str,
                               tool_calls: List[ToolCall] = None) -> Message:
        """Add an assistant message."""
        return self.add_message(MessageRole.ASSISTANT, content, tool_calls)

    def add_tool_results(self, results: List[ToolResult]) -> Message:
        """Add tool results as a message."""
        content = [r.to_api_format() for r in results]
        return self.add_message(MessageRole.TOOL_RESULT, content)

    def get_messages_for_api(self) -> List[Dict]:
        """Get messages formatted for Anthropic API."""
        return [msg.to_api_format() for msg in self.messages]

    def create_checkpoint(self, template_code: str,
                          description: str = "") -> Checkpoint:
        """Create a checkpoint of current conversation state."""
        self._checkpoint_counter += 1
        checkpoint = Checkpoint(
            id=f"cp_{self._checkpoint_counter}",
            messages=copy.deepcopy(self.messages),
            template_code=template_code,
            description=description
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    def restore_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Restore conversation to a checkpoint."""
        for cp in self.checkpoints:
            if cp.id == checkpoint_id:
                self.messages = copy.deepcopy(cp.messages)
                return cp
        return None

    def clear(self):
        """Clear all messages but keep checkpoints."""
        self.messages = []

    def get_last_assistant_message(self) -> Optional[Message]:
        """Get the most recent assistant message."""
        for msg in reversed(self.messages):
            if msg.role == MessageRole.ASSISTANT:
                return msg
        return None


class ToolExecutor:
    """Executes tools and manages tool registry."""

    def __init__(self):
        self._tools: Dict[str, Dict] = {}
        self._handlers: Dict[str, Callable] = {}

    def register_tool(self, name: str, description: str,
                      input_schema: Dict, handler: Callable):
        """Register a tool with its handler."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema
        }
        self._handlers[name] = handler

    def get_tools_for_api(self) -> List[Dict]:
        """Get tools formatted for Anthropic API."""
        return list(self._tools.values())

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool and return the result."""
        if tool_call.name not in self._handlers:
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Unknown tool: {tool_call.name}",
                is_error=True
            )

        try:
            handler = self._handlers[tool_call.name]
            result = handler(**tool_call.input)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=result
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error executing {tool_call.name}: {str(e)}\n{traceback.format_exc()}",
                is_error=True
            )

    def execute_all(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Execute multiple tools and return results."""
        return [self.execute(tc) for tc in tool_calls]


class ContextBuilder:
    """Builds context for API calls."""

    def __init__(self):
        self.system_prompt = ""
        self.current_template_code = ""
        self.invoice_text = ""
        self.invoice_path = ""

    def set_system_prompt(self, prompt: str):
        """Set the system prompt."""
        self.system_prompt = prompt

    def set_template_code(self, code: str):
        """Set current template code."""
        self.current_template_code = code

    def set_invoice(self, text: str, path: str = ""):
        """Set invoice text and path."""
        self.invoice_text = text
        self.invoice_path = path

    def build_system_prompt(self) -> str:
        """Build the complete system prompt with context."""
        parts = [self.system_prompt]

        if self.current_template_code:
            parts.append(f"\n\n## Current Template Code\n```python\n{self.current_template_code}\n```")

        if self.invoice_path:
            parts.append(f"\n\n## Loaded Invoice\nPath: {self.invoice_path}")

        return "\n".join(parts)


class AgentLoop:
    """Main agent loop that handles request -> tools -> response cycle."""

    def __init__(self, api_client, conversation: ConversationManager,
                 tool_executor: ToolExecutor, context: ContextBuilder,
                 model: str = "claude-sonnet-4-6"):
        self.api_client = api_client
        self.conversation = conversation
        self.tool_executor = tool_executor
        self.context = context
        self.model = model
        self.max_iterations = 10  # Prevent infinite loops

        # Callbacks for UI updates
        self.on_assistant_text: Optional[Callable[[str], None]] = None
        self.on_tool_start: Optional[Callable[[ToolCall], None]] = None
        self.on_tool_result: Optional[Callable[[ToolCall, ToolResult], None]] = None
        self.on_iteration_complete: Optional[Callable[[int], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def set_model(self, model: str):
        """Set the model to use."""
        self.model = model

    def run(self, user_message: str) -> Dict[str, Any]:
        """
        Run the agent loop with a user message.

        Returns a dict with:
        - success: bool
        - final_text: str (accumulated assistant text)
        - tool_calls: List of all tool calls made
        - tool_results: List of all tool results
        - iterations: int (number of API calls made)
        - error: str (if success is False)
        """
        # Add user message to conversation
        self.conversation.add_user_message(user_message)

        result = {
            "success": True,
            "final_text": "",
            "tool_calls": [],
            "tool_results": [],
            "iterations": 0,
            "error": None
        }

        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            result["iterations"] = iteration

            try:
                # Make API call
                response = self._call_api()

                # Extract content from response
                text_parts = []
                tool_calls = []

                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tool_calls.append(ToolCall(
                            id=block.id,
                            name=block.name,
                            input=block.input
                        ))

                # Handle text response - accumulate all text across iterations
                current_text = ""
                if text_parts:
                    current_text = "\n".join(text_parts)
                    result["final_text"] += current_text + "\n"
                    if self.on_assistant_text:
                        self.on_assistant_text(current_text)

                # Check stop reason - if end_turn with no tool calls, we're done
                stop_reason = getattr(response, 'stop_reason', None)

                # If no tool calls, we're done
                if not tool_calls:
                    if current_text:
                        self.conversation.add_assistant_message(current_text)
                    break

                # Add assistant message with tool calls (include current iteration text only)
                self.conversation.add_assistant_message(
                    current_text,
                    tool_calls
                )

                # Execute tools
                tool_results = []
                for tc in tool_calls:
                    result["tool_calls"].append({
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input
                    })

                    if self.on_tool_start:
                        self.on_tool_start(tc)

                    tr = self.tool_executor.execute(tc)
                    tool_results.append(tr)

                    result["tool_results"].append({
                        "tool_use_id": tr.tool_use_id,
                        "content": tr.content,
                        "is_error": tr.is_error
                    })

                    if self.on_tool_result:
                        self.on_tool_result(tc, tr)

                # Add tool results to conversation
                self.conversation.add_tool_results(tool_results)

                if self.on_iteration_complete:
                    self.on_iteration_complete(iteration)

            except Exception as e:
                error_msg = f"Agent loop error: {str(e)}\n{traceback.format_exc()}"
                result["success"] = False
                result["error"] = error_msg
                if self.on_error:
                    self.on_error(error_msg)
                break

        if iteration >= self.max_iterations:
            result["success"] = False
            result["error"] = f"Max iterations ({self.max_iterations}) reached"

        return result

    def _call_api(self):
        """Make an API call to Claude."""
        return self.api_client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.context.build_system_prompt(),
            tools=self.tool_executor.get_tools_for_api(),
            messages=self.conversation.get_messages_for_api()
        )


# Default system prompt for template building.
#
# Speak in plain user-facing language ("update the code", "look up another
# template"), NEVER in implementation terms (`edit_template`,
# `validate_syntax`, etc.) — those internal tool names are confusing for
# non-developer users. The tool schemas are still passed to the model via
# the API; this prompt only governs the natural-language reply that
# appears in the chat panel.
DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant who edits invoice extraction templates for EntryOps, a customs entry processing tool. You communicate with non-developer users (customs entry writers) who need their templates to extract data correctly from their suppliers' invoices.

## How to communicate

Speak in plain English. Do NOT mention internal tool names or implementation details in your replies. Describe what you're doing in user terms:

  YES: "Let me update the line-item regex so it captures the W/LID variant."
  NO:  "I'll use the edit_template tool with edit_type='surgical' and replace_all=true."

  YES: "I checked the template against the sample — it pulls 8 items and reconciles to $16,298.95."
  NO:  "I ran test_template and got 8 items."

  YES: "Looking at how the sigmac_seksaria template handles per-row PO numbers…"
  NO:  "Let me call read_template on sigmac_seksaria.py."

You DO have actions available to read, edit, and test code. Use them freely — but describe them as actions, not as named tools. The user does not need to know the schema.

## What a template needs to do

Templates inherit from `BaseTemplate` and must implement:
  - can_process(text) — return True for this supplier's invoices
  - extract_invoice_number(text)
  - extract_project_number(text) — PO number, or "UNKNOWN"
  - extract_line_items(text) — list of dicts with at minimum part_number, quantity, total_price

Strongly recommend including: unit_price, description, quantity_unit, hts_code, country_origin, po_number per row.

## Workflow

When the user asks you to change something:

1. **Explain what you found and what you're going to do** in plain user terms. One short paragraph is enough.
2. **Make the change** — use surgical edits for small fixes, a full rewrite only for major restructuring. Set `replace_all=true` when the user says "everywhere" or "in all locations".
3. **After the change lands, summarize what you changed** in plain user terms. Quote the new behavior, not the regex.
4. **Verify by testing** when it's reasonable — running the template against a sample is the only way to know it actually extracts. Report the row count, total, and any obviously-wrong items.

When the user asks a question (not a change):
  - Give a thorough plain-English answer grounded in the actual code.
  - Cite line numbers or function names where it helps — that's normal user speak.
  - Don't leak internal action names.

## Response format

The user can't see your internal actions — only your text. EVERY reply must end with a plain-English summary of what you did and what the user should check next. Never end a reply with a bare action call.

When you tested the template, the summary should always include:
  - whether it matched (`can_process` result, in plain words)
  - how many items were extracted
  - the total
  - one or two example items (part number, quantity, total)
"""
