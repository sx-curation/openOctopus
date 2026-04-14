// Azure Container Apps deployment for OpenOctopus
// Resources: ACR, Key Vault, Log Analytics, ACA Environment, Container App
//
// Usage:
//   az deployment group create \
//     --resource-group rg-openoctopus-prod \
//     --template-file infra/azure/main.bicep \
//     --parameters imageTag=<tag>

@description('Container image tag (e.g. git short SHA)')
param imageTag string

@description('Azure region')
param location string = resourceGroup().location

@description('Azure OpenAI endpoint (e.g. https://aoai-openoctopus.openai.azure.com/)')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment name')
param azureOpenAiDeployment string = 'gpt-4o'

@description('Azure OpenAI API version')
param azureOpenAiApiVersion string = '2024-02-01'

// ── Container Registry ─────────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {
  name: 'acrOpenOctopus'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// ── Key Vault ──────────────────────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: 'kv-openoctopus'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
  }
}

// ── Log Analytics ──────────────────────────────────────────────────────────
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'law-openoctopus'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Container Apps Environment ─────────────────────────────────────────────
resource acaEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'acae-openoctopus'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// ── Container App — REST API ───────────────────────────────────────────────
resource caApi 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'ca-openoctopus-api'
  location: location
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.name
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'openoctopus-api'
          image: '${acr.properties.loginServer}/openoctopus:${imageTag}'
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'PROVIDER', value: 'azure_openai' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: azureOpenAiDeployment }
            { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
            // Secrets below are referenced from Key Vault via secretRef.
            // After deployment, add KV role assignment so the ACA managed
            // identity can read secrets, then add secretRef entries.
            // For now, set these via: az containerapp secret set
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'azure-openai-key' }
            { name: 'FMP_API_KEY', secretRef: 'fmp-api-key' }
            { name: 'EDGAR_IDENTITY', secretRef: 'edgar-identity' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1  // single replica: avoids in-memory cache invalidation
      }
    }
  }
}

output apiUrl string = 'https://${caApi.properties.configuration.ingress.fqdn}'
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
