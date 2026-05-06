"""
Investment Analysis agentic loop.

支援三種後端（由 .env 控制，程式碼不需修改）：
  1. Azure OpenAI   — 設定 AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY
  2. OpenAI         — 設定 OPENAI_API_KEY
  3. 開源模型/本地   — 設定 OPENAI_API_KEY + BASE_URL（Ollama / vLLM / LM Studio）
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import APITimeoutError

from config import settings
from agent.llm_client import get_llm_client
from agent.investment.system_prompt import SYSTEM_PROMPT
from tools.definitions import TOOL_DEFINITIONS
from tools.dispatcher import dispatch


def run_analysis(user_query: str) -> str:
    """Run a full investment analysis for the given user query."""
    client = get_llm_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]
    iterations = 0

    while iterations < settings.MAX_AGENT_ITERATIONS:
        try:
            response = client.chat.completions.create(
                model=settings.MODEL,
                tools=TOOL_DEFINITIONS,
                messages=messages,
                max_tokens=8096,
                timeout=settings.API_TIMEOUT,
            )
        except APITimeoutError:
            raise TimeoutError(
                f"模型 '{settings.MODEL}' 沒有回應（已等待 {settings.API_TIMEOUT} 秒）。\n"
                f"請確認服務是否正在執行。\n"
                f"如需延長等待時間，請在 .env 加入：API_TIMEOUT=300"
            )
        iterations += 1

        choice = response.choices[0]
        finish_reason = choice.finish_reason

        if finish_reason == "stop":
            return choice.message.content or ""

        if finish_reason == "tool_calls":
            messages.append(choice.message)
            tool_calls = choice.message.tool_calls
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                futures = {
                    executor.submit(dispatch, tc.function.name, json.loads(tc.function.arguments)): tc
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

        break

    return "Analysis incomplete: maximum iterations reached or unexpected stop."
