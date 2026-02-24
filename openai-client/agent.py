"""
Todo Agent using Microsoft Agent Framework with OpenAI Client.
This agent fetches todo data directly from JSONPlaceholder API and provides it as context.

Note: Install with `pip install agent-framework-azure-ai --pre`
The --pre flag is required while Agent Framework is in preview.

This version uses OpenAIChatClient to connect directly to a Foundry-hosted model
using managed identity authentication (no Foundry project SDK needed).
Tracing requires APPLICATIONINSIGHTS_CONNECTION_STRING to be set.
"""
import os
import json
import logging
import httpx
from typing import Annotated, Optional, AsyncGenerator
from dotenv import load_dotenv

from agent_framework import Agent, tool
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, AsyncOpenAI
from pydantic import Field

# Load environment variables first
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
# For Foundry-hosted model with managed identity:
#   AZURE_OPENAI_ENDPOINT - The Foundry model endpoint
#   AZURE_CLIENT_ID - Optional: User-assigned managed identity client ID
# For Azure OpenAI with API key (fallback if identity fails):
#   AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY
# For direct OpenAI API:
#   OPENAI_API_KEY - OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
MANAGED_IDENTITY_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
APIM_SUBSCRIPTION_KEY = os.getenv("APIM_SUBSCRIPTION_KEY", "")
MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.1")
TODO_API_URL = os.getenv("TODO_API_URL", "https://jsonplaceholder.typicode.com/todos")

# Singleton for OpenAI client reuse
_client: Optional[OpenAIChatClient] = None
_credential: Optional[DefaultAzureCredential] = None
_client_initialized = False
_tracing_configured = False

# Cache for todos data
_todos_cache: Optional[list] = None


async def fetch_todos() -> list:
    """
    Fetch all todos from JSONPlaceholder API.
    Results are cached for reuse.
    """
    global _todos_cache
    
    if _todos_cache is not None:
        return _todos_cache
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(TODO_API_URL)
            if response.status_code == 200:
                _todos_cache = response.json()
                logger.info(f"Fetched {len(_todos_cache)} todos from API")
                return _todos_cache
            logger.error(f"API returned status {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error fetching todos: {e}")
        return []


def format_todos_for_context(todos: list, limit: int = 50) -> str:
    """Format todos as a readable context string for the agent."""
    if not todos:
        return "No todos available."
    
    # Limit the number of todos to include in context
    todos_subset = todos[:limit]
    
    lines = [f"Available Todos ({len(todos_subset)} of {len(todos)} shown):"]
    lines.append("-" * 50)
    
    for todo in todos_subset:
        status = "✓" if todo["completed"] else "○"
        lines.append(f"{status} [ID:{todo['id']}] (User {todo['userId']}) {todo['title']}")
    
    return "\n".join(lines)


@tool(approval_mode="never_require")
async def get_todo_by_id_tool(
    todo_id: Annotated[int, Field(description="The ID of the todo item to fetch (1-200)")]
) -> str:
    """
    Fetch a specific todo item by its ID from the JSONPlaceholder API.
    Use this when a user asks for details about a specific todo by ID.
    Valid IDs are 1-200.
    """
    try:
        # Remove /todos suffix if present to build correct URL
        base_url = TODO_API_URL.rstrip('/todos').rstrip('/')
        url = f"{base_url}/todos/{todo_id}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                todo = response.json()
                status = "Completed ✓" if todo["completed"] else "Not completed ○"
                return (
                    f"Todo Details:\n"
                    f"  ID: {todo['id']}\n"
                    f"  User ID: {todo['userId']}\n"
                    f"  Title: {todo['title']}\n"
                    f"  Status: {status}"
                )
            elif response.status_code == 404:
                return f"Todo with ID {todo_id} not found. Valid IDs are 1-200."
            return f"Error: API returned status {response.status_code}"
    except Exception as e:
        logger.error(f"Error fetching todo {todo_id}: {e}")
        return f"Error fetching todo {todo_id}: {str(e)}"


async def get_openai_client() -> OpenAIChatClient:
    """
    Get or create a singleton OpenAIChatClient for connection reuse.
    
    Supports:
    - Foundry-hosted model with managed identity: Set AZURE_OPENAI_ENDPOINT
    - Direct OpenAI API: Set OPENAI_API_KEY
    
    Tracing uses APPLICATIONINSIGHTS_CONNECTION_STRING.
    """
    global _client, _credential, _client_initialized, _tracing_configured
    
    if _client_initialized and _client is not None:
        return _client
    
    # Configure tracing first (requires APPLICATIONINSIGHTS_CONNECTION_STRING)
    if not _tracing_configured:
        _configure_tracing()
    
    # Option 1: Foundry via APIM with API key (simplest)
    if AZURE_OPENAI_ENDPOINT and APIM_SUBSCRIPTION_KEY:
        azure_client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=APIM_SUBSCRIPTION_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        
        _client = OpenAIChatClient(
            async_client=azure_client,
            model_id=MODEL_DEPLOYMENT,
        )
        logger.info(
            f"Created OpenAIChatClient for Foundry via APIM: {AZURE_OPENAI_ENDPOINT} "
            f"(model={MODEL_DEPLOYMENT}, api-version={AZURE_OPENAI_API_VERSION})"
        )
    
    # Option 2: Azure OpenAI with API key (fallback if identity fails)
    elif AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
        azure_client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        
        _client = OpenAIChatClient(
            async_client=azure_client,
            model_id=MODEL_DEPLOYMENT,
        )
        logger.info(
            f"Created OpenAIChatClient for Azure OpenAI with API key: {AZURE_OPENAI_ENDPOINT} "
            f"(model={MODEL_DEPLOYMENT}, api-version={AZURE_OPENAI_API_VERSION})"
        )
    
    # Option 3: Foundry with managed identity (direct endpoint, no APIM)
    elif AZURE_OPENAI_ENDPOINT:
        # Create credential for managed identity
        if MANAGED_IDENTITY_CLIENT_ID:
            _credential = DefaultAzureCredential(
                managed_identity_client_id=MANAGED_IDENTITY_CLIENT_ID
            )
        else:
            _credential = DefaultAzureCredential()
        
        # Create token provider for Azure AD authentication
        token_provider = get_bearer_token_provider(
            _credential,
            "https://cognitiveservices.azure.com/.default"
        )
        
        azure_client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        
        _client = OpenAIChatClient(
            async_client=azure_client,
            model_id=MODEL_DEPLOYMENT,
        )
        logger.info(
            f"Created OpenAIChatClient for Foundry with managed identity: {AZURE_OPENAI_ENDPOINT} "
            f"(model={MODEL_DEPLOYMENT}, api-version={AZURE_OPENAI_API_VERSION})"
        )
    
    # Option 4: Direct OpenAI API
    elif OPENAI_API_KEY:
        _client = OpenAIChatClient(api_key=OPENAI_API_KEY, model_id=MODEL_DEPLOYMENT)
        logger.info("Created OpenAIChatClient for OpenAI API")
    
    else:
        raise ValueError(
            "No credentials configured. Set one of:\n"
            "  - AZURE_OPENAI_ENDPOINT + APIM_SUBSCRIPTION_KEY for Foundry via APIM\n"
            "  - AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY for Azure OpenAI with API key\n"
            "  - AZURE_OPENAI_ENDPOINT alone for Foundry with managed identity\n"
            "  - OPENAI_API_KEY for direct OpenAI API"
        )
    
    _client_initialized = True
    return _client


def _configure_tracing() -> None:
    """
    Configure tracing using APPLICATIONINSIGHTS_CONNECTION_STRING.
    
    Since we're using OpenAIChatClient (no Foundry project), tracing must be
    configured manually via the connection string.
    """
    global _tracing_configured
    
    from tracing import configure_tracer
    service_name = os.getenv("OTEL_SERVICE_NAME", "todo-agent")
    agent_id = os.getenv("AGENT_ID", "TodoAgent")
    
    if configure_tracer(service_name=service_name, agent_id=agent_id):
        _tracing_configured = True
    else:
        logger.warning(
            "Tracing not configured. Set APPLICATIONINSIGHTS_CONNECTION_STRING "
            "to export traces to Application Insights."
        )


# System prompt for the agent
SYSTEM_PROMPT = """You are a helpful Todo Assistant agent. You help users query and understand their todo items.

You have been provided with a list of todos from the JSONPlaceholder API. Use this data to answer user questions.

You also have a tool to fetch specific todo details by ID:
- Use the get_todo_by_id tool when a user asks for a specific todo (e.g., "get todo 5", "show me todo #42")

When users ask about todos, tasks, or to-do items:
1. For specific todo requests by ID, use the get_todo_by_id tool
2. For general queries, reference the provided todo data
3. You can filter, search, and summarize the todos
4. Each todo has: id, userId, title, and completed status (✓ = completed, ○ = not completed)

Examples of what you can help with:
- "Get todo 5" → Use the tool to fetch todo with ID 5
- "Show me completed todos" → Filter from provided data
- "What todos does user 1 have?" → Filter by userId
- "How many todos are incomplete?" → Count todos by status

Provide clear, formatted responses. Be helpful, concise, and proactive in suggesting insights about the todos.
"""


async def run_todo_agent(
    user_message: str,
    chat_history: list[dict] = None,
    user_id: str = None
) -> AsyncGenerator[str, None]:
    """
    Run the Todo Agent with a user message.
    
    Args:
        user_message: The user's input message
        chat_history: Previous conversation history
        user_id: User identifier for tracking
        
    Yields:
        Response chunks from the agent
    """
    if chat_history is None:
        chat_history = []
    
    try:
        client = await get_openai_client()
        
        # Fetch todos directly from API
        todos = await fetch_todos()
        todos_context = format_todos_for_context(todos)
        
        # Create agent with get_todo_by_id tool and todos context
        agent = Agent(
            client=client,
            name="TodoAgent",
            instructions=SYSTEM_PROMPT + f"\n\n--- TODO DATA ---\n{todos_context}",
            tools=[get_todo_by_id_tool],
            model=MODEL_DEPLOYMENT,
        )
        
        logger.info(f"Todo Agent created with {len(todos)} todos as context")
        
        # Build conversation context
        conversation_context = ""
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    conversation_context += f"User: {content}\n"
                elif role == "assistant":
                    conversation_context += f"Assistant: {content}\n"
        
        full_prompt = conversation_context + user_message
        
        # Stream the response (new API: run with stream=True)
        async for chunk in agent.run(full_prompt, stream=True):
            if chunk.text:
                yield chunk.text
        
        # Yield metadata
        metadata = {
            "model": MODEL_DEPLOYMENT,
            "framework": "agent-framework",
            "api_url": TODO_API_URL,
            "todos_loaded": len(todos),
            "user_id": user_id or "anonymous"
        }
        yield f"\n__METADATA__:{json.dumps(metadata)}"
            
    except Exception as e:
        logger.error(f"Error running Todo Agent: {e}")
        yield f"Error: {str(e)}"


async def run_todo_agent_sync(
    user_message: str,
    chat_history: list[dict] = None,
    user_id: str = None
) -> str:
    """
    Run the Todo Agent and return the complete response (non-streaming).
    """
    response_parts = []
    async for chunk in run_todo_agent(user_message, chat_history, user_id):
        if not chunk.startswith("__METADATA__:"):
            response_parts.append(chunk)
    return "".join(response_parts)


if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("Todo Agent CLI - Type 'exit' to quit\n")
        chat_history = []
        
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() == "exit":
                break
            
            if not user_input:
                continue
            
            chat_history.append({"role": "user", "content": user_input})
            
            print("Agent: ", end="", flush=True)
            response = ""
            async for chunk in run_todo_agent(user_input, chat_history):
                if not chunk.startswith("__METADATA__:"):
                    print(chunk, end="", flush=True)
                    response += chunk
            print("\n")
            
            chat_history.append({"role": "assistant", "content": response})
    
    asyncio.run(main())
