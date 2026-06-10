from functools import lru_cache
from .config import settings
from .providers.base import VisionProvider


@lru_cache(maxsize=1)
def get_vision_provider() -> VisionProvider:
    return _build_provider(settings.vision_provider)


@lru_cache(maxsize=1)
def get_enrich_provider() -> VisionProvider:
    """Provider for text-only barcode enrichment; follows vision_provider unless overridden."""
    name = settings.enrich_provider or settings.vision_provider
    if name == settings.vision_provider:
        return get_vision_provider()
    return _build_provider(name)


def _build_provider(name: str) -> VisionProvider:
    if name == "ollama":
        from .providers.ollama import OllamaProvider
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)

    from .providers.gemini import GeminiProvider
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
