"""
Interactive REPL with confirmation for send_email (Y / T=trust / N).
Commands: exit, clear, untrust.
"""

from __future__ import annotations

from typing import Any

from agent import run
from logger import log

# ANSI
R = "\033[0m"
B = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"
BG_BLUE = "\033[44m"


def _format_email_confirmation(args: dict[str, Any]) -> str:
    to = args.get("to") or []
    recipients = ", ".join(to) if isinstance(to, list) else str(to)
    subject = (args.get("subject") or "(no subject)")[:52]
    fmt = (args.get("format") or "text")[:52]
    body_lines = (args.get("body") or "(empty)").split("\n")
    body_block = "\n".join(f"│  {line}" for line in body_lines)
    reply_line = ""
    if args.get("reply_to"):
        reply_line = f"│  Reply-To: {(args.get('reply_to') or '')[:51]}\n"
    return f"""
{CYAN}┌──────────────────────────────────────────────────────────────────┐{R}
{CYAN}│{R}  {B}📧 EMAIL CONFIRMATION REQUIRED{R}                                 {CYAN}│{R}
{CYAN}├──────────────────────────────────────────────────────────────────┤{R}
{CYAN}│{R}                                                                  {CYAN}│{R}
{CYAN}│{R}  {B}To:{R}      {recipients[:52].ljust(52)}{CYAN}│{R}
{CYAN}│{R}  {B}Subject:{R} {subject.ljust(52)}{CYAN}│{R}
{CYAN}│{R}  {B}Format:{R}  {fmt.ljust(52)}{CYAN}│{R}
{reply_line}{CYAN}│{R}                                                                  {CYAN}│{R}
{CYAN}├──────────────────────────────────────────────────────────────────┤{R}
{CYAN}│{R}  {B}Body:{R}                                                         {CYAN}│{R}
{CYAN}│{R}                                                                  {CYAN}│{R}
{body_block}
{CYAN}│{R}                                                                  {CYAN}│{R}
{CYAN}└──────────────────────────────────────────────────────────────────┘{R}

  {BG_GREEN}{WHITE} [Y] Send {R}    {BG_BLUE}{WHITE} [T] Trust & Send {R}    {BG_RED}{WHITE} [N] Cancel {R}
"""


def create_confirmation_handler(trusted_tools: set[str]):
    """Returns confirm_tool(tool_name, args) -> bool."""

    def confirm_tool(tool_name: str, args: dict[str, Any]) -> bool:
        if tool_name in trusted_tools:
            print(f"\n  {BLUE}⚡ Auto-approved (trusted):{R} {tool_name}\n")
            return True

        if tool_name == "send_email":
            print(_format_email_confirmation(args))
            choice = input(f"  {B}Your choice:{R} ").strip().lower()
            print()
            if choice in ("t", "trust"):
                trusted_tools.add(tool_name)
                print(f'  {BLUE}✓ Trusted "{tool_name}" for this session{R}')
                print(f"  {GREEN}✓ Sending email...{R}\n")
                return True
            if choice in ("y", "yes"):
                print(f"  {GREEN}✓ Sending email...{R}\n")
                return True
            print(f"  {RED}✗ Email cancelled{R}\n")
            return False

        # Generic confirmation for other tools
        print(f"\n{YELLOW}⚠  Action requires confirmation{R}")
        print(f"   Tool: {tool_name}")
        print(f"   Args: {args}")
        print(
            f"\n  {BG_GREEN}{WHITE} [Y] Proceed {R}    {BG_BLUE}{WHITE} [T] Trust & Proceed {R}    {BG_RED}{WHITE} [N] Cancel {R}\n"
        )
        choice = input(f"  {B}Your choice:{R} ").strip().lower()
        if choice in ("t", "trust"):
            trusted_tools.add(tool_name)
            print(f'\n  {BLUE}✓ Trusted "{tool_name}" for this session{R}\n')
            return True
        return choice in ("y", "yes")

    return confirm_tool


def run_repl() -> None:
    conversation_history: list[dict[str, Any]] = []
    trusted_tools: set[str] = set()
    confirm_tool = create_confirmation_handler(trusted_tools)

    while True:
        try:
            user_input = input(f"{B}You:{R} ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.lower() == "exit":
            break
        if user_input.lower() == "clear":
            conversation_history = []
            trusted_tools.clear()
            log.success("Conversation and trust cleared\n")
            continue
        if user_input.lower() == "untrust":
            trusted_tools.clear()
            log.success("All tools untrusted\n")
            continue
        if not user_input:
            continue

        try:
            response, _, new_history = run(
                user_input,
                conversation_history=conversation_history,
                confirm_tool=confirm_tool,
            )
            conversation_history = new_history
            print(f"\n{GREEN}Assistant:{R} {response}\n")
        except Exception as e:
            log.error("Error", str(e))
            print()
