"""
Configuration for the agent API (01_05_agent port).
Loads .env from parent my_python directory.
"""
from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of infra/ (i.e. 01_05_02_ agents)
ROOT_DIR = Path(__file__).resolve().parent.parent
_env_path = ROOT_DIR.parent / ".env"
load_dotenv(_env_path)

# Load shared AI config from parent my_python
_parent_config_path = str(ROOT_DIR.parent / "config.py")
_spec = importlib.util.spec_from_file_location("_my_python_config", _parent_config_path)
_parent_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _parent_mod
_spec.loader.exec_module(_parent_mod)

AI_CONFIG = _parent_mod.load_config()
DEFAULT_MODEL = AI_CONFIG.resolve_model_for_provider("gpt-4.1")
MAX_OUTPUT_TOKENS = 8192
MAX_AGENT_DEPTH = 5
MAX_TURNS = 10

DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
"""SQLite file path (e.g. '.data/agent.db'). Empty → in-memory repositories."""


def _register_providers() -> None:
    """Register all available providers based on environment config."""
    from infra.provider_registry import register_provider, set_default_provider
    from infra.provider_openai import OpenAIProvider

    openai_provider = OpenAIProvider(
        provider_name=AI_CONFIG.provider,
        api_key=AI_CONFIG.api_key,
        base_url=AI_CONFIG.responses_api_endpoint,
        extra_headers=AI_CONFIG.extra_api_headers,
        default_max_tokens=MAX_OUTPUT_TOKENS,
    )
    register_provider(openai_provider)

    if AI_CONFIG.provider != "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key:
            openai_direct = OpenAIProvider(
                provider_name="openai",
                api_key=openai_key,
                base_url="https://api.openai.com/v1/responses",
                default_max_tokens=MAX_OUTPUT_TOKENS,
            )
            register_provider(openai_direct)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        from infra.provider_gemini import GeminiProvider
        gemini_model = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash").strip()
        gemini_provider = GeminiProvider(
            api_key=gemini_key,
            default_model=gemini_model,
            default_max_tokens=MAX_OUTPUT_TOKENS,
        )
        register_provider(gemini_provider)

    set_default_provider(AI_CONFIG.provider)


_register_providers()
