"""
Configuration for the file & email agent (01_05_confirmation port).
Loads .env from parent my_python directory.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Load from parent my_python directory
ROOT_DIR = Path(__file__).resolve().parent
_env_path = ROOT_DIR.parent / ".env"
load_dotenv(_env_path)

# Resend (optional -- only needed when send_email is used)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "").strip()

if not RESEND_API_KEY or not RESEND_FROM:
    warnings.warn(
        "RESEND_API_KEY / RESEND_FROM not set -- send_email will fail. "
        "Add them to git/my_python/.env if you need email sending.",
        stacklevel=1,
    )

# Workspace and whitelist
WORKSPACE_DIR = ROOT_DIR / "workspace"
WHITELIST_PATH = WORKSPACE_DIR / "whitelist.json"

# AI: use shared config from parent my_python
import sys
import importlib.util

_parent_config_path = str(ROOT_DIR.parent / "config.py")
_spec = importlib.util.spec_from_file_location("_my_python_config", _parent_config_path)
_parent_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _parent_mod
_spec.loader.exec_module(_parent_mod)

AI_CONFIG = _parent_mod.load_config()
MODEL = AI_CONFIG.resolve_model_for_provider("gpt-4.1")
MAX_OUTPUT_TOKENS = 16384

INSTRUCTIONS = """You are an assistant with access to file system tools and email sending.

## AVAILABLE TOOLS

### File Operations
- fs_read: Read file contents
- fs_write: Write/create files
- fs_list: List directory contents
- fs_search: Search for files

### Email (Native)
- send_email: Send email to whitelisted recipients

## CRITICAL: EMAIL WORKFLOW

When the user asks to send an email:
1. Call send_email tool IMMEDIATELY with the email details
2. DO NOT ask for confirmation - the system handles that automatically
3. DO NOT preview the email in your response - the system shows a UI
4. Just call the tool and report the result

The system will intercept the tool call and show a confirmation UI to the user.
Your job is to call the tool, not to confirm.

## RULES

- Use tools to help the user with file-related tasks
- Always confirm before overwriting existing files
- Report results clearly after operations complete"""
