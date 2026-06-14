"""
Retrieval agent: parallel tool execution for the investment analysis loop.

Decouples the ThreadPoolExecutor logic from loop.py so the orchestration
loop stays focused on LLM interaction only.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.dispatcher import dispatch

logger = logging.getLogger(__name__)


def fetch_parallel(tool_calls: list) -> list[dict]:
    """Execute a batch of LLM tool-calls in parallel and return their results.

    Args:
        tool_calls: List of OpenAI ToolCall objects
                    (response.choices[0].message.tool_calls).

    Returns:
        List of dicts, one per tool call::

            [{"tool_call_id": str, "content": str}, ...]

        ``content`` is always a JSON string so it can be appended directly to
        the messages list as a ``role: "tool"`` turn.
    """
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max(1, len(tool_calls))) as executor:
        futures = {
            executor.submit(
                dispatch,
                tc.function.name,
                json.loads(tc.function.arguments),
            ): tc
            for tc in tool_calls
        }
        for future in as_completed(futures):
            tc = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool %r raised %s: %s", tc.function.name, type(exc).__name__, exc)
                result = {"error": str(exc)}

            results.append({
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return results
