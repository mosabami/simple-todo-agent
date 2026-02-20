"""
Azure AI Foundry Tracing Configuration.

This module provides fallback tracing configuration using APPLICATIONINSIGHTS_CONNECTION_STRING.
Primary tracing is configured via AzureAIClient.configure_azure_monitor() in agent.py,
which automatically fetches the App Insights connection string from your Foundry project.
"""
import os
import logging
from dotenv import load_dotenv

# OpenTelemetry
from opentelemetry import trace

# Agent Framework observability (optional - graceful fallback if not installed)
try:
    from agent_framework.observability import (
        create_resource,
        enable_instrumentation,
    )
    AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    AGENT_FRAMEWORK_AVAILABLE = False
    create_resource = None
    enable_instrumentation = None

# Azure Monitor exporter (optional - graceful fallback if not installed)
try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    AZURE_MONITOR_AVAILABLE = True
except ImportError:
    AZURE_MONITOR_AVAILABLE = False
    configure_azure_monitor = None

load_dotenv()

logger = logging.getLogger(__name__)

_TRACING_CONFIGURED = False


def configure_foundry_tracing(service_name: str = "todo-agent") -> bool:
    """
    Fallback: Configure tracing using APPLICATIONINSIGHTS_CONNECTION_STRING env var.
    
    This is called when AzureAIClient.configure_azure_monitor() fails.
    
    Args:
        service_name: Name to identify this service in traces
        
    Returns:
        True if tracing was configured successfully, False otherwise
    """
    global _TRACING_CONFIGURED

    if _TRACING_CONFIGURED:
        return True

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    
    if not connection_string:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set. "
            "Traces will NOT be exported to Application Insights."
        )
        return False
    
    if not AZURE_MONITOR_AVAILABLE:
        logger.warning(
            "azure-monitor-opentelemetry not installed. "
            "Cannot configure Application Insights tracing."
        )
        return False

    # Set service name via environment variable
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    try:
        if AGENT_FRAMEWORK_AVAILABLE and create_resource:
            configure_azure_monitor(
                connection_string=connection_string,
                resource=create_resource(),
                enable_live_metrics=True,
            )
        else:
            configure_azure_monitor(
                connection_string=connection_string,
                enable_live_metrics=True,
            )

        if AGENT_FRAMEWORK_AVAILABLE and enable_instrumentation:
            enable_instrumentation(enable_sensitive_data=True)

        _TRACING_CONFIGURED = True
        logger.info(
            "Azure Monitor (Application Insights) tracing configured via connection string. "
            "Agent Framework spans will be exported to App Insights."
        )
        return True

    except Exception as e:
        logger.error(f"Failed to configure tracing: {e}")
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
    return trace.get_tracer(name)
