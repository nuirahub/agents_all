"""Simple colored logger for terminal output."""
from __future__ import annotations

from datetime import datetime

# ANSI
R = "\033[0m"
B = "\033[1m"
D = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_BLUE = "\033[44m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class _Log:
    def info(self, msg: str) -> None:
        print(f"{D}[{_ts()}]{R} {msg}")

    def success(self, msg: str) -> None:
        print(f"{D}[{_ts()}]{R} {GREEN}✓{R} {msg}")

    def error(self, title: str, msg: str = "") -> None:
        print(f"{D}[{_ts()}]{R} {RED}✗ {title}{R} {msg or ''}")

    def warn(self, msg: str) -> None:
        print(f"{D}[{_ts()}]{R} {YELLOW}⚠{R} {msg}")

    def start(self, msg: str) -> None:
        print(f"{D}[{_ts()}]{R} {CYAN}→{R} {msg}")

    def box(self, text: str) -> None:
        lines = text.split("\n")
        width = max(len(l) for l in lines) + 4
        print(f"\n{CYAN}{'─' * width}{R}")
        for line in lines:
            print(f"{CYAN}│{R} {B}{line.ljust(width - 3)}{R}{CYAN}│{R}")
        print(f"{CYAN}{'─' * width}{R}\n")

    def query(self, q: str) -> None:
        print(f"\n{BG_BLUE}{WHITE} QUERY {R} {q}\n")

    def response(self, r: str) -> None:
        snippet = r[:500] + "..." if len(r) > 500 else r
        print(f"\n{GREEN}Response:{R} {snippet}\n")

    def api(self, step: str, msg_count: int) -> None:
        print(f"{D}[{_ts()}]{R} {MAGENTA}◆{R} {step} ({msg_count} messages)")

    def api_done(self, usage: dict) -> None:
        if usage:
            i = usage.get("input_tokens", 0)
            o = usage.get("output_tokens", 0)
            print(f"{D}         tokens: {i} in / {o} out{R}")

    def tool(self, name: str, args: dict) -> None:
        import json
        s = json.dumps(args)
        if len(s) > 100:
            s = s[:100] + "..."
        print(f"{D}[{_ts()}]{R} {YELLOW}⚡{R} {name} {D}{s}{R}")

    def tool_result(self, name: str, success: bool, output: str) -> None:
        icon = f"{GREEN}✓{R}" if success else f"{RED}✗{R}"
        out = output[:150] + "..." if len(output) > 150 else output
        print(f"{D}         {icon} {out}{R}")


log = _Log()
