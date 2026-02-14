"""
FastAPI application exposing the Todo Agent as REST endpoints.
This enables the agent to be deployed as a Container App.
"""
import os
import json
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from agent import run_todo_agent, run_todo_agent_sync

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    logger.info("Todo Agent API starting up...")
    yield
    logger.info("Todo Agent API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Todo Agent API",
    description="AI Agent for managing todo items using Microsoft Agent Framework",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatMessage(BaseModel):
    """A single chat message."""
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str = Field(..., description="User's message to the agent")
    chat_history: list[ChatMessage] = Field(
        default=[],
        description="Previous conversation history"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="User identifier for tracking"
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response"
    )


class ChatResponse(BaseModel):
    """Response body for non-streaming chat."""
    response: str = Field(..., description="Agent's response")
    model: str = Field(..., description="Model used")
    framework: str = Field(default="agent-framework", description="Framework used")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str


@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint with service info."""
    return HealthResponse(
        status="healthy",
        service="Todo Agent API",
        version="1.0.0"
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for container orchestration."""
    return HealthResponse(
        status="healthy",
        service="Todo Agent API",
        version="1.0.0"
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the Todo Agent (non-streaming).
    
    Send a message and receive the complete response.
    """
    try:
        # Convert chat history to expected format
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.chat_history
        ]
        
        if request.stream:
            # Return streaming response
            async def generate():
                async for chunk in run_todo_agent(
                    request.message,
                    history,
                    request.user_id
                ):
                    if not chunk.startswith("__METADATA__:"):
                        yield chunk
            
            return StreamingResponse(
                generate(),
                media_type="text/plain"
            )
        
        # Non-streaming response
        response = await run_todo_agent_sync(
            request.message,
            history,
            request.user_id
        )
        
        return ChatResponse(
            response=response,
            model=os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o-mini"),
            framework="agent-framework"
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Chat with the Todo Agent (streaming).
    
    Send a message and receive the response as a stream of chunks.
    """
    try:
        # Convert chat history to expected format
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.chat_history
        ]
        
        async def generate():
            async for chunk in run_todo_agent(
                request.message,
                history,
                request.user_id
            ):
                if not chunk.startswith("__METADATA__:"):
                    # Send as server-sent event format
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"Error in streaming chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
