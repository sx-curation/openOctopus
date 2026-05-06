"""
Investment Analysis agentic loop.

支援三種後端（由 .env 控制，程式碼不需修改）：
  1. Azure OpenAI   — 設定 AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY
  2. OpenAI         — 設定 OPENAI_API_KEY
  3. 開源模型/本地   — 設定 OPENAI_API_KEY + BASE_URL（Ollama / vLLM / LM Studio）
"""
from openai import APITimeoutError

from config import settings
from agent.llm_client import get_llm_client
from agent.investment.system_prompt import SYSTEM_PROMPT
from agent.investment.retrieval_agent import fetch_parallel
from tools.definitions import TOOL_DEFINITIONS


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
            for tr in fetch_parallel(choice.message.tool_calls):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["content"],
                })
            continue

        break

    return "Analysis incomplete: maximum iterations reached or unexpected stop."
