#!/usr/bin/env bash
# Deploy OpenOctopus to Azure Container Apps
# Prerequisites: az login, Docker, jq
set -euo pipefail

RG="rg-openoctopus-prod"
LOCATION="eastus"
ACR="acrOpenOctopus"
IMAGE_TAG="openoctopus:$(git rev-parse --short HEAD)"

echo "==> Building and pushing image: ${IMAGE_TAG}"
az acr build \
  --registry "${ACR}" \
  --image "${IMAGE_TAG}" \
  --file Dockerfile \
  .

echo "==> Deploying Bicep template"
az deployment group create \
  --resource-group "${RG}" \
  --template-file infra/azure/main.bicep \
  --parameters \
    imageTag="$(git rev-parse --short HEAD)" \
    azureOpenAiEndpoint="${AZURE_OPENAI_ENDPOINT}" \
  --output table

echo "==> Setting container app secrets (from Key Vault)"
az containerapp secret set \
  --name ca-openoctopus-api \
  --resource-group "${RG}" \
  --secrets \
    "azure-openai-key=${AZURE_OPENAI_API_KEY}" \
    "fmp-api-key=${FMP_API_KEY}" \
    "edgar-identity=${EDGAR_IDENTITY}"

API_URL=$(az containerapp show \
  --name ca-openoctopus-api \
  --resource-group "${RG}" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "Deployment complete!"
echo "API URL: https://${API_URL}"
echo ""
echo "Test:"
echo "  curl -X POST https://${API_URL}/analyze -H 'Content-Type: application/json' -d '{\"query\":\"AAPL\"}'"
