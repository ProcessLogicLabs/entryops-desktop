"""
Ollama Integration for AI-Assisted Template Generation
DEPRECATED: This module is maintained for backward compatibility.
Use ai_providers module instead for multi-provider support.
"""

# Re-export from ai_providers for backward compatibility
from ai_providers import (
    OllamaProvider as OllamaHelper,
    TemplateAnalysis,
    ExtractionPattern,
    generate_template_code,
)

# Legacy function for checking Ollama status
def check_ollama_status():
    """
    Check Ollama installation and status.

    Returns:
        Tuple of (is_available, status_message, available_models)
    """
    helper = OllamaHelper()
    available, message = helper.is_available()
    models = helper.get_available_models() if available else []
    return available, message, models
