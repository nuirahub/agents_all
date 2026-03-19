"""
OpenAI client setup.
Loads API key from the shared my_python/.env file.
"""
from __future__ import annotations

import os
from pathlib import Path

import dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
dotenv.load_dotenv(_env_path)

from openai import OpenAI  # noqa: E402

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()

if _PROVIDER == "openrouter" or (not _OPENAI_API_KEY and _OPENROUTER_API_KEY):
    AI_PROVIDER = "openrouter"
    _API_KEY = _OPENROUTER_API_KEY
    _BASE_URL = "https://openrouter.ai/api/v1"
elif _OPENAI_API_KEY:
    AI_PROVIDER = "openai"
    _API_KEY = _OPENAI_API_KEY
    _BASE_URL = "https://api.openai.com/v1"
else:
    raise SystemExit("No OPENAI_API_KEY or OPENROUTER_API_KEY found in .env")

client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL)


def resolve_model(model: str) -> str:
    if AI_PROVIDER != "openrouter" or "/" in model:
        return model
    return f"openai/{model}"
