"""
Daily Ops Generator — multi-agent pipeline entry point.
Python port of 4th-devs/02_04_ops.
"""
from __future__ import annotations

import asyncio
from datetime import date

from agent import run_agent

DEMO_FILE = "demo/example.md"


def confirm_run() -> None:
    print()
    print("⚠️  UWAGA: Uruchomienie tego agenta może zużyć zauważalną liczbę tokenów.")
    print("   Jeśli nie chcesz uruchamiać go teraz, najpierw sprawdź plik demo:")
    print(f"   Demo: {DEMO_FILE}")
    print()
    answer = input("Czy chcesz kontynuować? (yes/y): ").strip().lower()
    if answer not in ("yes", "y"):
        print("Przerwano.")
        raise SystemExit(0)


async def main() -> None:
    today = date.today().isoformat()

    print()
    print("=" * 40)
    print(f"  Daily Ops Generator — {today}")
    print("=" * 40)
    print()

    confirm_run()

    task = (
        f"Prepare the Daily Ops note for {today}. "
        "Start by reading the workflow instructions from workflows/daily-ops.md using the read_file tool. "
        "Then follow the steps described in the workflow precisely. "
        f"Make sure to write the final output to output/{today}.md"
    )

    result = await run_agent("orchestrator", task)

    print()
    print("=" * 40)
    print("  Result")
    print("=" * 40)
    print()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
