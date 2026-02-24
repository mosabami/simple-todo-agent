"""
OpenTelemetry Tracing Configuration for OpenAI Client mode.

This module configures OpenTelemetry tracing using Azure Monitor exporters.
Since we're using OpenAIClient (no Foundry project), APPLICATIONINSIGHTS_CONNECTION_STRING
is REQUIRED for tracing to work.

Uses Agent Framework's configure_otel_providers() with Azure Monitor exporters
for rich agent telemetry in Application Insights.
"""
import os
import logging
from typing import Optional
from dotenv import load_dotenv

# OpenTelemetry
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan, Span

load_dotenv()

logger = logging.getLogger(__name__)

_TRACING_CONFIGURED = False
_AGENT_ID: Optional[str] = None
_AGENT_NAME: Optional[str] = None


class AgentIdSpanProcessor(SpanProcessor):
    """
    SpanProcessor that adds gen_ai.agent.id and gen_ai.agent.name to every span.
    This ensures the agent ID appears in Application Insights customDimensions.
    """
    
    def __init__(self, agent_id: str, agent_name: str):
        self.agent_id = agent_id
        self.agent_name = agent_name
    
    def on_start(self, span: Span, parent_context=None) -> None:
        """Add agent attributes when span starts."""
        if span.is_recording():
            span.set_attribute("gen_ai.agent.id", self.agent_id)
            span.set_attribute("gen_ai.agent.name", self.agent_name)
    
    def on_end(self, span: ReadableSpan) -> None:
        """Called when span ends - no action needed."""
        pass
    
    def shutdown(self) -> None:
        """Shutdown the processor."""
        pass
    
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush - nothing to flush."""
        return True


# Agent Framework observability
try:
    from agent_framework.observability import (
        configure_otel_providers,
        create_resource,
        enable_instrumentation,
    )
    AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    AGENT_FRAMEWORK_AVAILABLE = False
    configure_otel_providers = None
    create_resource = None
    enable_instrumentation = None

# Azure Monitor exporters (preferred - gives us control over what to export)
try:
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorTraceExporter,
        AzureMonitorMetricExporter,
        AzureMonitorLogExporter,
    )
    AZURE_MONITOR_EXPORTERS_AVAILABLE = True
except ImportError:
    AZURE_MONITOR_EXPORTERS_AVAILABLE = False
    AzureMonitorTraceExporter = None
    AzureMonitorMetricExporter = None
    AzureMonitorLogExporter = None

# Fallback to configure_azure_monitor if exporters not available
try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    AZURE_MONITOR_AVAILABLE = True
except ImportError:
    AZURE_MONITOR_AVAILABLE = False
    configure_azure_monitor = None


def _str_to_bool(value: Optional[str], default: bool = False) -> bool:
    """Convert string environment variable to boolean."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def configure_tracer(
    service_name: str = "todo-agent",
    agent_id: Optional[str] = None,
    enable_content_recording: Optional[bool] = None,
) -> bool:
    """
    Configure Agent Framework tracing with Azure Monitor exporters.
    
    APPLICATIONINSIGHTS_CONNECTION_STRING is REQUIRED since there's no Foundry project
    to auto-fetch the connection string from.
    
    Args:
        service_name: Name to identify this service in traces
        agent_id: Unique identifier for the agent (defaults to AGENT_ID env var or service_name)
        enable_content_recording: Whether to record sensitive content in traces
        
    Returns:
        True if tracing was configured successfully, False otherwise
    """
    global _TRACING_CONFIGURED, _AGENT_ID, _AGENT_NAME

    if _TRACING_CONFIGURED:
        return True

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    
    if not connection_string:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set. "
            "Traces will NOT be exported to Application Insights. "
            "This is REQUIRED when using OpenAIClient (no Foundry project)."
        )
        return False
    
    # Set service name
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    
    # Resolve agent ID (from param, env var, or service name)
    resolved_agent_id = agent_id or os.getenv("AGENT_ID", service_name)
    
    # Resolve content recording setting
    resolved_enable_content = (
        enable_content_recording 
        if enable_content_recording is not None 
        else _str_to_bool(os.getenv("ENABLE_SENSITIVE_DATA", "true"), default=True)
    )
    
    # Option 1 (Preferred): Use Agent Framework's configure_otel_providers with Azure Monitor exporters
    if AGENT_FRAMEWORK_AVAILABLE and configure_otel_providers and AZURE_MONITOR_EXPORTERS_AVAILABLE:
        try:
            # Create Azure Monitor exporters (traces + metrics + logs)
            exporters = [
                AzureMonitorTraceExporter(connection_string=connection_string),
                AzureMonitorMetricExporter(connection_string=connection_string),
                AzureMonitorLogExporter(connection_string=connection_string),
            ]
            
            # Configure Agent Framework with Azure Monitor exporters
            configure_otel_providers(
                enable_sensitive_data=resolved_enable_content,
                exporters=exporters,
            )
            
            # Explicitly enable instrumentation (may already be done by configure_otel_providers)
            if enable_instrumentation:
                enable_instrumentation(enable_sensitive_data=resolved_enable_content)
            
            # Add AgentIdSpanProcessor to inject gen_ai.agent.id into every span
            tracer_provider = trace.get_tracer_provider()
            if hasattr(tracer_provider, 'add_span_processor'):
                tracer_provider.add_span_processor(
                    AgentIdSpanProcessor(agent_id=resolved_agent_id, agent_name=service_name)
                )
            
            # Store agent info globally
            _AGENT_ID = resolved_agent_id
            _AGENT_NAME = service_name
            
            _TRACING_CONFIGURED = True
            logger.info(
                f"Agent Framework tracing configured with Azure Monitor exporters "
                f"(service={service_name}, agent_id={resolved_agent_id}, content_recording={resolved_enable_content})"
            )
            return True
            
        except Exception as e:
            logger.warning(f"Failed to configure Agent Framework with Azure Monitor exporters: {e}")
    
    # Option 2 (Fallback): Use configure_azure_monitor directly
    if AZURE_MONITOR_AVAILABLE and configure_azure_monitor:
        try:
            kwargs = {
                "connection_string": connection_string,
                "enable_live_metrics": True,
            }
            
            if AGENT_FRAMEWORK_AVAILABLE and create_resource:
                kwargs["resource"] = create_resource()
            
            configure_azure_monitor(**kwargs)
            
            _TRACING_CONFIGURED = True
            logger.info(
                f"Azure Monitor tracing configured via configure_azure_monitor "
                f"(service={service_name})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to configure tracing: {e}")
            return False
    
    logger.warning(
        "Tracing not configured. Install azure-monitor-opentelemetry-exporter "
        "or azure-monitor-opentelemetry for Application Insights telemetry."
    )
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
