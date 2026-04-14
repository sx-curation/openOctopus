#!/usr/bin/env bash
# Create Azure AI Hub and Project for OpenOctopus Foundry Agent
# Prerequisites: az login, az ml extension (az extension add -n ml)
set -euo pipefail

RG="rg-openoctopus-prod"
LOCATION="eastus"
HUB_NAME="openoctopus-ai-hub"
PROJECT_NAME="openoctopus-project"
AOAI_RESOURCE="aoai-openoctopus"

echo "==> Creating AI Hub"
az ml workspace create \
  --resource-group "${RG}" \
  --name "${HUB_NAME}" \
  --kind hub \
  --location "${LOCATION}"

HUB_ID=$(az ml workspace show \
  --resource-group "${RG}" \
  --name "${HUB_NAME}" \
  --query id -o tsv)

echo "==> Creating AI Project (linked to Hub)"
az ml workspace create \
  --resource-group "${RG}" \
  --name "${PROJECT_NAME}" \
  --kind project \
  --hub-id "${HUB_ID}" \
  --location "${LOCATION}"

echo "==> Retrieving project connection string"
CONN_STR=$(az ml workspace show \
  --resource-group "${RG}" \
  --name "${PROJECT_NAME}" \
  --query "discovery_url" -o tsv | \
  sed "s|https://||;s|/discovery||")

echo ""
echo "Setup complete!"
echo ""
echo "Set this env var before running foundry/agent_definition.py:"
echo "  export AZURE_AI_PROJECT_CONNECTION_STRING=\"${CONN_STR}\""
echo ""
echo "Next: python foundry/agent_definition.py"
