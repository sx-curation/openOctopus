"""
Azure AI Foundry execution loop for OpenOctopus.

Replaces agent/loop.py for the Foundry deployment path.
Uses the Azure AI Projects SDK polling model (required_action pattern),
while reusing tools/dispatcher.py for all tool execution — no tool rewrites needed.

Usage:
  export AZURE_AI_PROJECT_CONNECTION_STRING="..."
  export OPENOCTOPUS_AGENT_ID="asst_..."     # from agent_definition.py output
  python foundry/run_foundry.py
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ThreadMessageRole, RunStatus, ToolOutput
from azure.identity import DefaultAzureCredential

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.dispatcher import dispatch  # direct reuse, zero changes


def run_foundry_analysis(user_query: str, agent_id: str) -> str:
    """
    Run a full equity analysis via Azure AI Foundry.
    Creates a new thread per call to avoid context contamination across queries.
    """
    conn_str = os.environ.get("AZURE_AI_PROJECT_CONNECTION_STRING", "")
    if not conn_str:
        raise EnvironmentError("AZURE_AI_PROJECT_CONNECTION_STRING is not set.")

    client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(),
        conn_str=conn_str,
    )

    # New thread per query — Foundry threads persist in storage
    thread = client.agents.create_thread()
    client.agents.create_message(
        thread_id=thread.id,
        role=ThreadMessageRole.USER,
        content=user_query,
    )

    run = client.agents.create_run(thread_id=thread.id, agent_id=agent_id)

    while run.status in (RunStatus.QUEUED, RunStatus.IN_PROGRESS, RunStatus.REQUIRES_ACTION):
        time.sleep(1)
        run = client.agents.get_run(thread_id=thread.id, run_id=run.id)

        if run.status == RunStatus.REQUIRES_ACTION:
            tool_calls = run.required_action.submit_tool_outputs.tool_calls

            # Parallel dispatch — mirrors the ThreadPoolExecutor pattern in agent/loop.py
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                futures = {
                    executor.submit(
                        dispatch,
                        tc.function.name,
                        json.loads(tc.function.arguments),
                    ): tc
                    for tc in tool_calls
                }
                outputs = [
                    ToolOutput(
                        tool_call_id=futures[f].id,
                        output=json.dumps(f.result(), default=str),
                    )
                    for f in as_completed(futures)
                ]

            client.agents.submit_tool_outputs_to_run(
                thread_id=thread.id,
                run_id=run.id,
                tool_outputs=outputs,
            )

    if run.status != RunStatus.COMPLETED:
        return f"Run ended with status: {run.status}"

    messages = client.agents.list_messages(thread_id=thread.id)
    for msg in reversed(messages.data):
        if msg.role == ThreadMessageRole.ASSISTANT:
            return msg.content[0].text.value

    return "No response generated."


def main():
    """Simple CLI REPL for Foundry mode."""
    from rich.console import Console
    from rich.markdown import Markdown

    agent_id = os.environ.get("OPENOCTOPUS_AGENT_ID", "")
    if not agent_id:
        print("Error: OPENOCTOPUS_AGENT_ID is not set.")
        print("Run foundry/agent_definition.py first to get an agent ID.")
        sys.exit(1)

    console = Console()
    console.print("[bold green]OpenOctopus Foundry Mode[/bold green]")
    console.print(f"Agent: {agent_id}")
    console.print("Enter a ticker or question (quit to exit)\n")

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query.lower() in ("quit", "exit", "q"):
            break
        if not query:
            continue

        console.print("\n[dim]Analyzing...[/dim]")
        report = run_foundry_analysis(query, agent_id)
        console.print(Markdown(report))
        console.print()


if __name__ == "__main__":
    main()
