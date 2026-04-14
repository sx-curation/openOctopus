"""
Register the OpenOctopus agent with Azure AI Foundry.

Run once (or whenever the system prompt or tool schemas change):
  pip install -r foundry/requirements-foundry.txt
  export AZURE_AI_PROJECT_CONNECTION_STRING="<from infra/foundry/setup.sh output>"
  export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
  python foundry/agent_definition.py

The script prints the agent ID — save it for use in run_foundry.py.
"""
import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

# Ensure project root is on path when run from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.definitions import TOOL_DEFINITIONS
from agent.system_prompt import SYSTEM_PROMPT


def register_agent() -> str:
    conn_str = os.environ.get("AZURE_AI_PROJECT_CONNECTION_STRING", "")
    if not conn_str:
        raise EnvironmentError(
            "AZURE_AI_PROJECT_CONNECTION_STRING is not set. "
            "Run infra/foundry/setup.sh first."
        )

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(),
        conn_str=conn_str,
    )

    # Build ToolSet from existing OpenAI JSON Schema definitions (no schema changes needed)
    tool_set = ToolSet()
    for td in TOOL_DEFINITIONS:
        tool_set.add(FunctionTool(definitions=[td["function"]]))

    agent = client.agents.create_agent(
        model=deployment,
        name="openoctopus-equity-analyst",
        instructions=SYSTEM_PROMPT,
        tools=tool_set.definitions,
    )

    print(f"Agent registered successfully.")
    print(f"Agent ID: {agent.id}")
    print(f"\nSave this ID and set it as OPENOCTOPUS_AGENT_ID when running run_foundry.py")
    return agent.id


if __name__ == "__main__":
    register_agent()
