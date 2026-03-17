"""
Standalone database seed script.
Usage:
    python -m infra.seed                      # seed default dev user
    python -m infra.seed --email user@x.com   # seed custom user
    python -m infra.seed --list               # list seeded users

Equivalent of `npm run db:seed` in the TypeScript version.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from infra.auth import DEFAULT_DEV_API_KEY, hash_api_key, seed_default_user
from infra.config import DATABASE_URL
from infra.logger import logger


def _get_repos():
    if DATABASE_URL:
        from infra.db import create_sqlite_repositories
        return create_sqlite_repositories(DATABASE_URL)
    from infra.repositories import create_memory_repositories
    return create_memory_repositories()


def _seed_user(repos, email: str, api_key: str | None = None) -> str:
    key = api_key or f"key-{uuid.uuid4().hex[:16]}"
    key_hash = hash_api_key(key)
    existing = repos.users.get_by_api_key_hash(key_hash)
    if existing:
        logger.info(f"User already exists: {existing.email} (id={existing.id})")
        return key
    repos.users.create({"email": email, "api_key_hash": key_hash})
    logger.info(f"Created user: {email}")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed agent database")
    parser.add_argument("--email", default="dev@agent.local")
    parser.add_argument("--api-key", default=None, help="API key (auto-generated if omitted)")
    parser.add_argument("--list", action="store_true", help="List all users")
    parser.add_argument("--default", action="store_true", help="Seed default dev user only")
    args = parser.parse_args()

    repos = _get_repos()
    storage = f"SQLite ({DATABASE_URL})" if DATABASE_URL else "in-memory (will not persist)"
    logger.info(f"Storage: {storage}")

    if args.list:
        if not hasattr(repos.users, "_store") and not DATABASE_URL:
            logger.warning("In-memory storage — no persisted users to list")
            return
        if DATABASE_URL:
            from infra.db import SqliteUserRepo
            if isinstance(repos.users, SqliteUserRepo):
                cur = repos.users._db.execute("SELECT id, email, created_at FROM users ORDER BY created_at")
                rows = cur.fetchall()
                if not rows:
                    print("No users found.")
                for row in rows:
                    print(f"  {row['id']}  {row['email']}  {row['created_at']}")
        return

    if args.default:
        seed_default_user(repos)
        print(f"Default user seeded (key: {DEFAULT_DEV_API_KEY})")
        return

    key = _seed_user(repos, args.email, args.api_key)
    print(f"User seeded: {args.email}")
    print(f"API key: {key}")


if __name__ == "__main__":
    main()
