from functools import lru_cache

from fastapi import Depends, HTTPException

from app.core.config import Settings, get_settings
from app.services.ai_scoring import AnthropicClient, GeminiClient
from app.services.places import PlacesClient


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def _places(key: str) -> PlacesClient:
    return PlacesClient(key)


@lru_cache
def _llm(key: str, model: str) -> AnthropicClient:
    return AnthropicClient(key, model)


@lru_cache
def _gemini(key: str, model: str) -> GeminiClient:
    return GeminiClient(key, model)


def _configured_llm(settings: Settings, model: str):
    if settings.llm_provider == "gemini":
        return _gemini(settings.gemini_api_key, settings.gemini_model) if settings.gemini_api_key else None
    return _llm(settings.anthropic_api_key, model) if settings.anthropic_api_key else None


def get_optional_places_client(settings: Settings = Depends(get_app_settings)):
    return _places(settings.google_places_api_key) if settings.google_places_api_key else None


def get_places_client(client=Depends(get_optional_places_client)):
    if client is None:
        raise HTTPException(503, "GOOGLE_PLACES_API_KEY nao configurada")
    return client


def get_llm_client(settings: Settings = Depends(get_app_settings)):
    return _configured_llm(settings, settings.llm_model) if settings.llm_enabled else None


def get_agent_llm(settings: Settings = Depends(get_app_settings)):
    return _configured_llm(settings, settings.agent_model) if settings.agent_enabled else None


@lru_cache
def _wa(token: str, phone_id: str, version: str):
    from app.services.whatsapp import WhatsAppClient

    return WhatsAppClient(token, phone_id, version)


def build_whatsapp(settings: Settings):
    if settings.whatsapp_enabled and settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        return _wa(settings.whatsapp_access_token, settings.whatsapp_phone_number_id, settings.whatsapp_api_version)
    return None


def get_whatsapp_client(settings: Settings = Depends(get_app_settings)):
    return build_whatsapp(settings)


def build_agent_llm(settings: Settings):
    return _configured_llm(settings, settings.agent_model) if settings.agent_enabled else None
