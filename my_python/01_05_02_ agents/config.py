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

ROOT_DIR = Path(__file__).resolve().parent
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
