"""
Azure AI Foundry Tracing Configuration.

This module configures OpenTelemetry to export traces to Azure Application Insights,
which enables trace visibility in the Azure AI Foundry Assets page.

When using AzureAIProjectAgentProvider, the SDK can automatically configure tracing
using the project's connected Application Insights resource - no manual connection
string required.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def configure_foundry_tracing(service_name: str = "todo-agent") -> bool:
    """
    Configure OpenTelemetry tracing for Azure AI Foundry.
    
    Uses the Agent Framework's built-in observability configuration which
    automatically connects to your Foundry project's Application Insights.
    
    Args:
        service_name: Name to identify this service in traces
        
    Returns:
        True if tracing was configured successfully, False otherwise
    """
    try:
        from agent_framework.observability import configure_otel_providers
        
        # Set service name via environment variable (Agent Framework reads this)
        os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
        
        # The Agent Framework SDK automatically configures tracing to use
        # the Application Insights connected to your Azure AI Project.
        # It reads the project endpoint from AZURE_AI_PROJECT_ENDPOINT env var.
        configure_otel_providers(
            enable_sensitive_data=True,  # Capture prompts/completions in traces
        )
        
        logger.info(
            f"Foundry tracing configured via Agent Framework. "
            f"Traces will appear in your AI Project's Assets page."
        )
        return True
        
    except ImportError as e:
        logger.warning(
            f"Agent Framework observability not available: {e}. "
            f"Falling back to manual Azure Monitor configuration."
        )
        return _configure_manual_tracing(service_name)
    except Exception as e:
        logger.error(f"Failed to configure Foundry tracing: {e}")
        return False


def _configure_manual_tracing(service_name: str) -> bool:
    """
    Fallback: Configure tracing manually using APPLICATIONINSIGHTS_CONNECTION_STRING.
    """
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    
    if not connection_string:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set and auto-config failed. "
            "Traces will NOT appear in Foundry Assets page."
        )
        return False
    
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        
        configure_azure_monitor(
            connection_string=connection_string,
            enable_live_metrics=True,
        )
        
        logger.info("Foundry tracing configured via manual Application Insights connection.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to configure manual tracing: {e}")
        return False


def get_tracer(name: str = __name__):
    """
    Get an OpenTelemetry tracer for manual span creation.
    
    Use this to add custom spans for operations you want to track:
    
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("my-operation") as span:
            span.set_attribute("custom.key", "value")
            # ... your code ...
    """
    from opentelemetry import trace
    return trace.get_tracer(name)
