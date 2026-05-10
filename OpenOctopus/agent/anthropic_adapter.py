"""
AnthropicAdapter — wraps the Anthropic SDK to expose the same
OpenAI-style .chat.completions.create() interface.

This adapter is only needed when LLM_PROVIDER=free-claude.
It translates requests to the Anthropic Messages API format and wraps
responses back into OpenAI-compatible duck-typed objects.

Requires: anthropic>=0.26.0  (install with: pip install anthropic)

Tool calling (function calling) support:
- Converts OpenAI tools[] format → Anthropic tools[] format
- Converts Anthropic tool_use response → OpenAI tool_calls format
- arguments field is JSON-encoded string (OpenAI) vs dict (Anthropic)
- finish_reason "tool_calls" (OpenAI) vs stop_reason "tool_use" (Anthropic)
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Duck-typed response wrappers (OpenAI-compatible shape)
# ---------------------------------------------------------------------------

class _ToolFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments  # JSON string, not dict


class _ToolCall:
    def __init__(self, id: str, name: str, arguments: dict[str, Any]):
        self.id = id
        self.type = "function"
        self.function = _ToolFunction(name=name, arguments=json.dumps(arguments))


class _Message:
    def __init__(self, content: str | None, tool_calls: list[_ToolCall] | None = None):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(self, message: _Message, finish_reason: str, index: int = 0):
        self.message = message
        self.finish_reason = finish_reason
        self.index = index


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class _ChatCompletionResponse:
    def __init__(self, choices: list[_Choice], model: str, usage: _Usage):
        self.choices = choices
        self.model = model
        self.usage = usage
        self.object = "chat.completion"


# ---------------------------------------------------------------------------
# Message format converters
# ---------------------------------------------------------------------------

def _openai_messages_to_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert OpenAI messages to Anthropic format.

    Returns:
        (system_prompt, anthropic_messages)

    OpenAI uses {"role": "system", "content": "..."} in the messages list.
    Anthropic takes system as a top-level parameter, not in messages.
    """
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            continue

        if role == "tool":
            # OpenAI tool result: {"role": "tool", "content": "...", "tool_call_id": "..."}
            anthropic_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }],
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            # Assistant message with tool calls
            anthropic_content: list[dict[str, Any]] = []
            if content:
                anthropic_content.append({"type": "text", "text": content})
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                anthropic_content.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args,
                })
            anthropic_messages.append({"role": "assistant", "content": anthropic_content})
            continue

        # Standard user/assistant message
        text = content if isinstance(content, str) else json.dumps(content)
        anthropic_messages.append({
            "role": role,
            "content": [{"type": "text", "text": text}],
        })

    return "\n".join(system_parts), anthropic_messages


def _openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI tools[] to Anthropic tools[] format.

    OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic: {"name": ..., "description": ..., "input_schema": ...}
    """
    result = []
    for tool in tools:
        fn = tool.get("function", {})
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _anthropic_response_to_openai(response: Any, model: str) -> _ChatCompletionResponse:
    """Convert an Anthropic Messages response to OpenAI-compatible object.

    Key differences:
    - Anthropic stop_reason "tool_use" → OpenAI finish_reason "tool_calls"
    - Anthropic content blocks (list) vs OpenAI content (str)
    - Anthropic tool input (dict) vs OpenAI arguments (JSON str)
    """
    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []

    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            tool_calls.append(_ToolCall(
                id=getattr(block, "id", ""),
                name=getattr(block, "name", ""),
                arguments=getattr(block, "input", {}),  # dict → JSON str in _ToolFunction
            ))

    finish_reason = "stop"
    stop_reason = getattr(response, "stop_reason", "end_turn")
    if stop_reason == "tool_use":
        finish_reason = "tool_calls"
    elif stop_reason == "max_tokens":
        finish_reason = "length"

    content = "\n".join(text_parts) if text_parts else None
    message = _Message(content=content, tool_calls=tool_calls if tool_calls else None)
    choice = _Choice(message=message, finish_reason=finish_reason)

    usage_obj = getattr(response, "usage", None)
    usage = _Usage(
        prompt_tokens=getattr(usage_obj, "input_tokens", 0) if usage_obj else 0,
        completion_tokens=getattr(usage_obj, "output_tokens", 0) if usage_obj else 0,
    )

    return _ChatCompletionResponse(
        choices=[choice],
        model=model or getattr(response, "model", "unknown"),
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Adapter classes (OpenAI interface)
# ---------------------------------------------------------------------------

class _ChatCompletions:
    def __init__(self, adapter: "AnthropicAdapter"):
        self._adapter = adapter

    def create(self, **kwargs: Any) -> _ChatCompletionResponse:
        return self._adapter._create(**kwargs)


class _Chat:
    def __init__(self, adapter: "AnthropicAdapter"):
        self.completions = _ChatCompletions(adapter)


class AnthropicAdapter:
    """OpenAI-compatible adapter routing through the free-claude-code proxy.

    Usage:
        adapter = AnthropicAdapter(proxy_url="http://localhost:8082")
        response = adapter.chat.completions.create(
            model="ollama/llama3.2:latest",
            messages=[{"role": "user", "content": "Hello"}],
        )
        print(response.choices[0].message.content)
    """

    def __init__(self, proxy_url: str):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for LLM_PROVIDER=free-claude. "
                "Install it with: pip install anthropic"
            ) from exc
        self._client = anthropic.Anthropic(
            api_key="free-claude",  # free-claude-code ignores the key value
            base_url=proxy_url,
        )
        self.chat = _Chat(self)

    def _create(self, **kwargs: Any) -> _ChatCompletionResponse:
        """Translate and forward an OpenAI-style completion request."""
        messages: list[dict[str, Any]] = kwargs.get("messages", [])
        openai_tools: list[dict[str, Any]] = kwargs.get("tools", [])
        model: str = kwargs.get("model", "ollama/llama3.2:latest")
        max_tokens: int = kwargs.get("max_tokens", 4096)
        temperature: float | None = kwargs.get("temperature", None)

        system_prompt, anthropic_messages = _openai_messages_to_anthropic(messages)

        anthropic_kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            anthropic_kwargs["system"] = system_prompt
        if temperature is not None:
            anthropic_kwargs["temperature"] = temperature
        if openai_tools:
            anthropic_kwargs["tools"] = _openai_tools_to_anthropic(openai_tools)

        logger.debug("AnthropicAdapter: forwarding to %s via free-claude-code", model)
        response = self._client.messages.create(**anthropic_kwargs)
        return _anthropic_response_to_openai(response, model)
