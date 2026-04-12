"""
Core agentic loop: drives the LLM with tool use until finish_reason == 'stop'.
Uses the OpenAI client — works with any OpenAI-compatible model (gpt-4o, etc.).
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from config import settings
from agent.system_prompt import SYSTEM_PROMPT
from tools.definitions import TOOL_DEFINITIONS
from tools.dispatcher import dispatch

if not settings.OPENAI_API_KEY:
    raise EnvironmentError(
        "OPENAI_API_KEY is not set. Add your OpenAI API key to .env."
    )

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.BASE_URL or None,
)


def run_analysis(user_query: str) -> str:
    """
    Run a full investment analysis for the given user query.
    Loops until the model produces a final text response or max_iterations is reached.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]
    iterations = 0

    while iterations < settings.MAX_AGENT_ITERATIONS:
        response = client.chat.completions.create(
            model=settings.MODEL,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            max_tokens=8096,
        )
        iterations += 1

        choice = response.choices[0]
        finish_reason = choice.finish_reason

        if finish_reason == "stop":
            return choice.message.content or ""

        if finish_reason == "tool_calls":
            # Append the assistant message (contains the tool_calls list)
            messages.append(choice.message)

            tool_calls = choice.message.tool_calls
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
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
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(future.result(), default=str),
                    })
            continue

        # Unexpected finish reason (e.g. "length", "content_filter")
        break

    return "Analysis incomplete: maximum iterations reached or unexpected stop."
