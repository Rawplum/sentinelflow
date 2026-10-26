"""Create a local SentinelFlow user with an interactive password prompt.

Usage:
    sentinelflow-create-user --username admin --role admin
    sentinelflow-create-user --username analyst1 --role analyst

Passwords are never accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy.exc import SQLAlchemyError

from sentinelflow.core.permissions import UserRole
from sentinelflow.db.session import get_session_factory
from sentinelflow.services.auth import create_user


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local SentinelFlow user with an interactive password prompt."
    )
    parser.add_argument("--username", required=True, help="Local username")
    parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in UserRole],
        help="Role assigned to the user",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("error: passwords do not match", file=sys.stderr)
        return 1

    try:
        session_factory = get_session_factory()
        with session_factory() as session:
            user = create_user(
                session,
                username=args.username,
                password=password,
                role=UserRole(args.role),
                actor_username="local-cli",
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("error: database operation failed", file=sys.stderr)
        return 2

    print(f"created user '{user.username}' with role '{user.role}' (id={user.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
