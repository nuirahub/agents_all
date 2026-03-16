from __future__ import annotations

import os
from dataclasses import dataclass

import dotenv

dotenv.load_dotenv()

RESPONSES_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/responses",
    "openrouter": "https://openrouter.ai/api/v1/responses",
}
VALID_PROVIDERS = {"openai", "openrouter"}


def _resolve_provider(
    requested_provider: str, has_openai_key: bool, has_openrouter_key: bool
) -> str:
    if requested_provider:
        if requested_provider == "openai" and not has_openai_key:
            raise SystemExit("AI_PROVIDER=openai requires OPENAI_API_KEY")
        if requested_provider == "openrouter" and not has_openrouter_key:
            raise SystemExit("AI_PROVIDER=openrouter requires OPENROUTER_API_KEY")
        if requested_provider not in VALID_PROVIDERS:
            raise SystemExit("AI_PROVIDER must be one of: openai, openrouter")
        return requested_provider

    if has_openai_key:
        return "openai"
    if has_openrouter_key:
        return "openrouter"

    raise SystemExit(
        "API key is not set. Please provide OPENAI_API_KEY or OPENROUTER_API_KEY "
        "in environment variables or in a .env file in the `my_python` directory."
    )


@dataclass(frozen=True)
class AIConfig:
    provider: str
    api_key: str
    responses_api_endpoint: str
    extra_api_headers: dict[str, str]

    def resolve_model_for_provider(self, model: str) -> str:
        """
        Python equivalent of `resolveModelForProvider` from the JS config.
        """
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Model must be a non-empty string")

        if self.provider != "openrouter" or "/" in model:
            return model

        if model.startswith("gpt-"):
            return f"openai/{model}"
        return model


def load_config() -> AIConfig:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    requested_provider = os.getenv("AI_PROVIDER", "").strip().lower()

    has_openai_key = bool(openai_api_key)
    has_openrouter_key = bool(openrouter_api_key)

    provider = _resolve_provider(requested_provider, has_openai_key, has_openrouter_key)
    api_key = openai_api_key if provider == "openai" else openrouter_api_key

    responses_api_endpoint = RESPONSES_ENDPOINTS[provider]

    extra_headers: dict[str, str] = {}
    if provider == "openrouter":
        referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
        app_name = os.getenv("OPENROUTER_APP_NAME", "").strip()
        if referer:
            extra_headers["HTTP-Referer"] = referer
        if app_name:
            extra_headers["X-Title"] = app_name

    return AIConfig(
        provider=provider,
        api_key=api_key,
        responses_api_endpoint=responses_api_endpoint,
        extra_api_headers=extra_headers,
    )


CONFIG = load_config()
