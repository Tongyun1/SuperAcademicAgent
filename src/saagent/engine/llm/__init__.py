from .base import LLMClient
from .null import NullLLM


def build_llm(settings) -> LLMClient:
    """Factory: pick the configured backend, falling back to NullLLM (pure graph)."""
    if settings.llm_provider == "null" or not settings.llm_available:
        return NullLLM()
    try:
        if settings.llm_provider == "local":
            from .local import LocalLLM

            return LocalLLM(settings)
        if settings.llm_provider == "bailian":
            from .bailian import BailianLLM

            return BailianLLM(settings)
        from .claude import ClaudeLLM

        return ClaudeLLM(settings)
    except Exception:
        return NullLLM()


__all__ = ["LLMClient", "NullLLM", "build_llm"]
