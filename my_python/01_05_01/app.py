"""
File & Email Agent (Interactive) — Python port of 01_05_confirmation.
Uses workspace file tools and send_email with whitelist; requires terminal
confirmation before sending email.
"""
from __future__ import annotations

from config import WORKSPACE_DIR
from logger import log
from repl import run_repl
from tools_file import FILE_TOOLS
from tools_email import SEND_EMAIL_TOOL

EXAMPLES = [
    "List all files in the workspace",
    "Read workspace/whitelist.json and show me its contents",
    'Write "Hello from the agent!" to workspace/output/hello.txt',
    'Send an email to alice@aidevs.pl with subject "Hello" and a short greeting',
    "Search for any markdown files in the workspace",
]


def main() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    log.box("File & Email Agent\nCommands: 'exit' | 'clear' | 'untrust'")

    file_tool_names = [t["name"] for t in FILE_TOOLS]
    log.info(f"File tools: {', '.join(file_tool_names)}")
    log.info(f"Native tools: send_email")
    print()
    log.info("Example queries:")
    for ex in EXAMPLES:
        log.info(f"  • {ex}")
    print()

    run_repl()


if __name__ == "__main__":
    main()
