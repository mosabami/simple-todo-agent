"""
Chainlit UI for the Todo Agent.
Provides a chat interface for interacting with the AI agent.
"""
import chainlit as cl
from agent import run_todo_agent


@cl.on_chat_start
async def start():
    """Initialize the chat session."""
    cl.user_session.set("chat_history", [])
    
    await cl.Message(
        content="👋 Hello! I'm the **Todo Agent**. I can help you fetch and manage todo items.\n\nTry asking me things like:\n- \"Get todo item 1\"\n- \"What is todo 5 about?\"\n- \"Fetch todos 1, 2, and 3\""
    ).send()


@cl.on_message
async def main(message: cl.Message):
    """Handle incoming user messages."""
    chat_history = cl.user_session.get("chat_history", [])
    
    # Add user message to history
    chat_history.append({"role": "user", "content": message.content})
    
    # Create a message placeholder for streaming
    msg = cl.Message(content="")
    await msg.send()
    
    # Run the agent and collect response
    full_response = ""
    async for chunk in run_todo_agent(
        user_message=message.content,
        chat_history=chat_history[:-1],  # Exclude current message
        user_id=cl.user_session.get("id", "anonymous")
    ):
        # Skip metadata chunks
        if chunk.startswith("\n__METADATA__:"):
            continue
        full_response += chunk
        await msg.stream_token(chunk)
    
    # Finalize the message
    await msg.update()
    
    # Add assistant response to history
    chat_history.append({"role": "assistant", "content": full_response})
    cl.user_session.set("chat_history", chat_history)


@cl.on_chat_end
async def end():
    """Clean up when chat session ends."""
    pass
