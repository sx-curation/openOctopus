"""
Core agentic loop: drives Claude with tool use until stop_reason == 'end_turn'.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

from config import settings
from agent.system_prompt import SYSTEM_PROMPT
from tools.definitions import TOOL_DEFINITIONS
from tools.dispatcher import dispatch

if not settings.ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
    )

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def run_analysis(user_query: str) -> str:
    """
    Run a full investment analysis for the given user query.
    Loops until Claude produces a final text response or max_iterations is reached.
    """
    messages = [{"role": "user", "content": user_query}]
    iterations = 0

    while iterations < settings.MAX_AGENT_ITERATIONS:
        response = client.messages.create(
            model=settings.MODEL,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            max_tokens=8096,
        )
        iterations += 1

        # Append the full assistant message (may contain text + tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return _extract_text(response.content)

        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            with ThreadPoolExecutor(max_workers=len(tool_blocks)) as executor:
                futures = {executor.submit(dispatch, b.name, b.input): b for b in tool_blocks}
                tool_results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": futures[f].id,
                        "content": json.dumps(f.result(), default=str),
                    }
                    for f in as_completed(futures)
                ]
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason
        break

    return "Analysis incomplete: maximum iterations reached or unexpected stop."


def _extract_text(content) -> str:
    """Extract the concatenated text from an assistant content block list."""
    return "\n".join(b.text for b in content if b.type == "text").strip()
