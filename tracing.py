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

_TRACING_CONFIGURED = False


def _has_otel_exporter_config() -> bool:
    """Return True if OTEL exporter-related env vars are set."""
    keys = (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
        "ENABLE_CONSOLE_EXPORTERS",
        "VS_CODE_EXTENSION_PORT",
    )
    return any(os.getenv(k) for k in keys)


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
    global _TRACING_CONFIGURED

    if _TRACING_CONFIGURED:
        return True

    enable_sensitive_data = True

    try:
        from agent_framework.observability import (
            configure_otel_providers,
            create_resource,
            enable_instrumentation,
        )
    except ImportError as e:
        logger.warning(
            f"Agent Framework observability not available: {e}. "
            f"Falling back to manual Azure Monitor configuration."
        )
        return _configure_manual_tracing(service_name)

    # Set service name via environment variable (Agent Framework reads this)
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    # Pattern #3 (recommended for App Insights): configure Azure Monitor exporter,
    # then explicitly enable Agent Framework instrumentation.
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=connection_string,
                resource=create_resource(),
                enable_live_metrics=True,
            )
            enable_instrumentation(enable_sensitive_data=enable_sensitive_data)

            _TRACING_CONFIGURED = True
            logger.info(
                "Azure Monitor (Application Insights) tracing configured. "
                "Agent Framework spans will be exported to App Insights."
            )
            return True
        except Exception as e:
            logger.warning(
                f"Failed to configure Azure Monitor exporter: {e}. "
                "Falling back to OTEL environment-based configuration."
            )

    # Pattern #1: use standard OTEL env vars to configure an OTLP backend (Aspire,
    # Jaeger, etc). NOTE: this does NOT export to Application Insights unless you
    # also have an OTLP collector/bridge.
    try:
        configure_otel_providers(enable_sensitive_data=enable_sensitive_data)
        enable_instrumentation(enable_sensitive_data=enable_sensitive_data)

        _TRACING_CONFIGURED = True
        if not _has_otel_exporter_config() and not connection_string:
            logger.warning(
                "Tracing instrumentation enabled, but no exporter is configured. "
                "To see traces in Application Insights, set APPLICATIONINSIGHTS_CONNECTION_STRING. "
                "To see traces in another backend, set OTEL_EXPORTER_OTLP_ENDPOINT or ENABLE_CONSOLE_EXPORTERS=true."
            )
        else:
            logger.info(
                "Tracing configured via OpenTelemetry environment variables. "
                "Ensure an OTEL backend is configured to receive the data."
            )
        return True
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

        # If Agent Framework is installed, make sure its spans are actually emitted.
        # (Azure Monitor exporter only sets up the backend.)
        try:
            from agent_framework.observability import create_resource, enable_instrumentation
        except Exception:
            create_resource = None
            enable_instrumentation = None
        
        if create_resource:
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

        if enable_instrumentation:
            enable_instrumentation(enable_sensitive_data=True)
        
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
