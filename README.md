
# Todo Agent (Microsoft Agent Framework + Microsoft Foundry)

This repo is a minimal example of using **Microsoft Agent Framework** with a **Microsoft Foundry** project.

The agent:

- Fetches todo items from `https://jsonplaceholder.typicode.com/todos`.
- Creates/runs an agent in your Foundry project via the project endpoint.
- Emits OpenTelemetry traces through Agent Framework’s observability (export requires configuring an exporter/backend).

What you’ll learn:

- How Agent Framework uses a Foundry project endpoint + model deployment to run an agent (even when you execute code locally).
- How to structure a tiny agent with a single tool and streamed responses.
- How to run the agent locally with `DefaultAzureCredential`.
- How to enable OTEL-based tracing with Agent Framework and export it to Application Insights (Azure Monitor exporter) or any OTLP backend.
- How to connect Application Insights after the first run and then provide the connection string so traces show up.
- How to deploy the agent as an app in Azure Container Apps with system-assigned identity and the required RBAC.

## What is Agent Framework?

Microsoft Agent Framework is an SDK that helps you build agents that run against a model deployment in Microsoft Foundry. In this repo, the agent is created using `AzureAIClient` and `Agent`, which connect to your Foundry **project endpoint** and use your chosen **model deployment**.

Even if you run this code locally on your laptop, the agent is still created and executed in the context of your Foundry project (because the SDK is calling the Foundry project endpoint). That’s why you can see agent activity and traces in Foundry while developing locally.

## Prerequisites

- Python 3.12+
- A Microsoft Foundry **resource + project**
- A **deployed model** in that Foundry resource (you reference its *deployment name*)

Authentication:

- Local: `DefaultAzureCredential` (typically `az login`, VS Code sign-in, or other supported credentials)
- Azure Container Apps: system-assigned managed identity

## Code overview

This repo is intentionally small. The fastest way to understand it is to skim these files:

- `agent.py`: Core agent logic.
	- Creates a singleton `AzureAIClient` with `DefaultAzureCredential` for connection reuse.
	- Configures Azure Monitor tracing via `AzureAIClient.configure_azure_monitor()` (auto-fetches App Insights connection string from your Foundry project).
	- Fetches todos from `TODO_API_URL` and formats a subset into prompt context.
	- Defines one tool (`get_todo_by_id_tool`) the model can call to fetch a specific todo by ID.
	- Creates an `Agent` with tools and streams responses back to the caller.

- `main.py`: HTTP API wrapper for the agent.
	- Exposes `/health` and `/chat` endpoints using FastAPI so the agent can be run as a simple web service.
	- Supports streaming responses via `/chat/stream` (Server-Sent Events).
	- Loads env vars (so the same `.env` works locally and in a container).

- `tracing.py`: Fallback tracing configuration.
	- Only used if `AzureAIClient.configure_azure_monitor()` fails.
	- Falls back to manual `APPLICATIONINSIGHTS_CONNECTION_STRING` env var.
	- Provides `get_tracer()` helper for custom span creation.

- `chainlit_app.py`: Optional chat UI.
	- Starts a Chainlit chat session, keeps a simple in-memory `chat_history`, and streams agent output tokens to the UI.

## Configuration (env vars)

Copy `.env.example` to `.env` and set:

- `AZURE_AI_PROJECT_ENDPOINT`: Foundry project endpoint URL (looks like `https://<resource>.services.ai.azure.com/api/projects/<project>`)
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`: the model *deployment name* you created (example: `gpt-5.2-chat`)

Optional:

- `TODO_API_URL` (defaults to JSONPlaceholder)
- `PORT` (defaults to `8080`)
- `OTEL_SERVICE_NAME` (defaults to `todo-agent`)
- `APPLICATIONINSIGHTS_CONNECTION_STRING` (optional fallback - tracing is auto-configured from your Foundry project's connected App Insights)

## One-time Azure setup (required before local run)

Before running locally, you need an Azure resource group, a Foundry resource + project, and a deployed model.

You can create and connect Application Insights later (after your first run) so the flow stays “run it once, then turn on observability”.

### 0) Set variables

```bash
LOCATION=eastus
RG=rg-todo-agent

# Foundry
FOUNDRY_RESOURCE=foundrytodo$RANDOM
FOUNDRY_PROJECT=todo-agent

# Model deployment name (this must match AZURE_AI_MODEL_DEPLOYMENT_NAME)
MODEL_DEPLOYMENT_NAME=gpt-5.2-chat
```

### 1) Create the resource group

```bash
az group create --name $RG --location $LOCATION
```

### 2) Create the Foundry resource + project

```bash
az cognitiveservices account create \
	--name $FOUNDRY_RESOURCE \
	--resource-group $RG \
	--kind AIServices \
	--sku s0 \
	--location $LOCATION \
	--allow-project-management
```

If the resource doesn’t already have a custom subdomain, set one (required for Entra/RBAC auth in many setups):

```bash
az cognitiveservices account update \
	--name $FOUNDRY_RESOURCE \
	--resource-group $RG \
	--custom-domain $FOUNDRY_RESOURCE
```

```bash
az cognitiveservices account project create \
	--name $FOUNDRY_RESOURCE \
	--resource-group $RG \
	--project-name $FOUNDRY_PROJECT \
	--location $LOCATION
```

Get the project details and locate the project endpoint in the output (look under `.properties.endpoints`). Set it as `AZURE_AI_PROJECT_ENDPOINT`.

```bash
az cognitiveservices account project show \
	--name $FOUNDRY_RESOURCE \
	--resource-group $RG \
	--project-name $FOUNDRY_PROJECT \
	-o jsonc
```

### 3) Deploy a model (creates the deployment name you reference)

Example for an Azure OpenAI model deployment. Adjust `--model-name` and `--model-version` to a model/version available in your region/subscription.

```bash
az cognitiveservices account deployment create \
	--name $FOUNDRY_RESOURCE \
	--resource-group $RG \
	--deployment-name $MODEL_DEPLOYMENT_NAME \
	--model-name gpt-5.2 \
	--model-version "2024-07-18" \
	--model-format OpenAI \
	--sku-capacity "1" \
	--sku-name "Standard"
```

## Run locally

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Note: `requirements.txt` installs a preview package (`agent-framework-azure-ai`) using `--pre`.

### 2) Create your .env

Copy `.env.example` to `.env` and set:

- `AZURE_AI_PROJECT_ENDPOINT` (from step 3 above)
- `AZURE_AI_MODEL_DEPLOYMENT_NAME` (your deployment name)

### 3) Sign in to Azure (for local auth)

```bash
az login
```

### 4) Start the API

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

Try it:

```bash
curl -s http://localhost:8080/health

curl -s http://localhost:8080/chat \
	-H "content-type: application/json" \
	-d '{"message":"Show me 3 incomplete todos"}'
```

### Optional: run the Chainlit UI and have a conversation

```bash
python -m chainlit run chainlit_app.py
```

## After your first local run: connect Application Insights (New Foundry UI)

Once you’ve run the agent at least once, it should show up in your Foundry project. At that point, you can create Application Insights (if you don’t already have one) and then connect it from the agent’s monitoring view.

### 1) Create Application Insights (optional, if you don’t already have one)

```bash
APPINSIGHTS=appi-todo-agent

az monitor app-insights component create \
	--app $APPINSIGHTS \
	--location $LOCATION \
	--resource-group $RG \
	--application-type web
```

### 2) Connect it in the Foundry portal

In the Foundry portal:

1. Make sure the **New Foundry** toggle is ON.
2. Open your Foundry project.
3. Navigate to your agent in the project (the agent is created with the name `TodoAgent`).
4. Open the agent and go to its **Monitoring** tab.
5. Use the action bar prompt to **connect Application Insights**, then select the Application Insights resource.

After the connection is set, traces from subsequent runs will appear in the agent’s traces/monitoring views.

Important: connecting Application Insights in Foundry does not automatically configure this app to export telemetry. For traces to show up, you must also set `APPLICATIONINSIGHTS_CONNECTION_STRING` in the environment where this code runs (local `.env`, Container Apps app settings, etc.).



## Deploy to Azure Container Apps (Azure CLI)

This section assumes you already created:

- A resource group
- A Foundry resource + project
- A model deployment

You’ll deploy this repo as a container by creating an ACR image, a Container Apps environment, and a Container App with system-assigned identity + RBAC.

### 0) Set variables

```bash
LOCATION=eastus
RG=rg-todo-agent

# Foundry project endpoint + deployment name
AZURE_AI_PROJECT_ENDPOINT="<paste-your-foundry-project-endpoint-here>"
MODEL_DEPLOYMENT_NAME=gpt-5.2-chat

# Containers
ACR_NAME=acrtodo$RANDOM
IMAGE_NAME=todo-agent
ACA_ENV=env-todo-agent
ACA_APP=todo-agent

# Observability resources
LOG_ANALYTICS=law-todo-agent
APPINSIGHTS=appi-todo-agent

SUB_ID=$(az account show --query id -o tsv)
```

### 1) Create ACR and build the image

```bash
az acr create --name $ACR_NAME --resource-group $RG --sku Basic

az acr build --registry $ACR_NAME --image ${IMAGE_NAME}:latest .
```

### 2) Create Container Apps environment (with Log Analytics)

```bash
az monitor log-analytics workspace create \
	--resource-group $RG \
	--workspace-name $LOG_ANALYTICS \
	--location $LOCATION

WORKSPACE_ID=$(az monitor log-analytics workspace show \
	--resource-group $RG \
	--workspace-name $LOG_ANALYTICS \
	--query customerId -o tsv)

WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
	--resource-group $RG \
	--workspace-name $LOG_ANALYTICS \
	--query primarySharedKey -o tsv)

az containerapp env create \
	--name $ACA_ENV \
	--resource-group $RG \
	--location $LOCATION \
	--logs-workspace-id $WORKSPACE_ID \
	--logs-workspace-key $WORKSPACE_KEY
```

### 3) Create Application Insights (optional)

This resource is created here as a convenient place to look at Container Apps telemetry. To export traces from this app to Application Insights, you must provide `APPLICATIONINSIGHTS_CONNECTION_STRING` (this repo uses the Azure Monitor OpenTelemetry exporter).

```bash
az monitor app-insights component create \
	--app $APPINSIGHTS \
	--location $LOCATION \
	--resource-group $RG \
	--application-type web

# Get the connection string (you'll set it on the Container App)
APPINSIGHTS_CONNECTION_STRING=$(az monitor app-insights component show \
	--app $APPINSIGHTS \
	--resource-group $RG \
	--query connectionString -o tsv)
```

### 4) Create the Container App and configure identity + RBAC

Create the Container App:

```bash
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --resource-group $RG --query loginServer -o tsv)

az containerapp create \
	--name $ACA_APP \
	--resource-group $RG \
	--environment $ACA_ENV \
	--image ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:latest \
	--target-port 8080 \
	--ingress external \
	--env-vars \
		PORT=8080 \
		TODO_API_URL=https://jsonplaceholder.typicode.com/todos \
		OTEL_SERVICE_NAME=todo-agent \
		APPLICATIONINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONNECTION_STRING \
		AZURE_AI_PROJECT_ENDPOINT=$AZURE_AI_PROJECT_ENDPOINT \
		AZURE_AI_MODEL_DEPLOYMENT_NAME=$MODEL_DEPLOYMENT_NAME
```

Enable system-assigned identity and capture its principal ID:

```bash
APP_PRINCIPAL_ID=$(az containerapp identity assign \
	--name $ACA_APP \
	--resource-group $RG \
	--system-assigned \
	--query principalId \
	-o tsv)
```

Grant the identity permission to pull from ACR:

```bash
REGISTRY_ID=$(az acr show --name $ACR_NAME --resource-group $RG --query id -o tsv)

az role assignment create \
	--assignee $APP_PRINCIPAL_ID \
	--scope $REGISTRY_ID \
	--role "AcrPull"

az containerapp registry set \
	--name $ACA_APP \
	--resource-group $RG \
	--server $ACR_LOGIN_SERVER \
	--identity system
```

Grant the identity permission to use Foundry (Azure AI User). The simplest scope is the resource group; you can scope this down to the Foundry resource if you prefer least privilege.

```bash
RG_SCOPE=$(az group show --name $RG --query id -o tsv)

az role assignment create \
	--assignee $APP_PRINCIPAL_ID \
	--scope $RG_SCOPE \
	--role "Azure AI User"
```

Update the Container App env var once you have the project endpoint:

```bash
az containerapp update \
	--name $ACA_APP \
	--resource-group $RG \
	--set-env-vars AZURE_AI_PROJECT_ENDPOINT=$AZURE_AI_PROJECT_ENDPOINT
```

Get the app URL:

```bash
az containerapp show \
	--name $ACA_APP \
	--resource-group $RG \
	--query properties.configuration.ingress.fqdn \
	-o tsv
```

## Rebuild + redeploy after code changes

When you change code, rebuild the container image and update the Container App to point at the new tag (using a unique tag avoids "latest" caching issues).

```bash
# Build a new image tag in ACR
IMAGE_TAG=$(date +%Y%m%d%H%M%S)
az acr build --registry $ACR_NAME --image ${IMAGE_NAME}:${IMAGE_TAG} .

# Update Container App to the new image (creates a new revision)
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --resource-group $RG --query loginServer -o tsv)
az containerapp update \
	--name $ACA_APP \
	--resource-group $RG \
	--image ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}
```

