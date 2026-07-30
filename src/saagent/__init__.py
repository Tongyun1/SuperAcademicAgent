"""SuperAcademic research agent — Stirrup agent loop over the SuperAcademicAISearch engine."""

from .client_anthropic import AnthropicMessagesClient
from .client_openai import OpenAICompatClient

__all__ = ["AnthropicMessagesClient", "OpenAICompatClient"]
