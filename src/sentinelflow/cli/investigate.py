"""Local CLI: run one investigation and print its trace.

This is the debugging entry point for a single alert. It runs the agent
synchronously and prints the round-by-round trace so a developer can see where
an investigation stalled, without opening the database or the web UI.

Example:
    sentinelflow-investigate --alert-id <uuid>
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from sentinelflow.ai.model_client import ModelNotConfiguredError, build_model_client
from sentinelflow.core.config import get_settings
from sentinelflow.core.permissions import UserRole
from sentinelflow.db.session import get_session_factory
from sentinelflow.models.alert import Alert
from sentinelflow.models.user import User
from sentinelflow.services.investigations import (
    InvestigationConflictError,
    list_rounds,
    list_tool_calls,
    run_investigation,
)


def _pick_actor(session, username: str | None) -> User | None:
    if username:
        return session.scalar(select(User).where(User.username == username.lower()))
    return session.scalar(
        select(User).where(User.role == UserRole.ADMIN.value).order_by(User.username)
    )


def _print_trace(session, investigation) -> None:
    rounds = list_rounds(session, investigation.id)
    calls = list_tool_calls(session, investigation.id)

    print()
    print(f"investigation : {investigation.id}")
    print(f"alert         : {investigation.alert_id}")
    print(f"status        : {investigation.status}")
    print(f"model         : {investigation.model_provider}/{investigation.model_name}")
    print(
        f"budget used   : {investigation.rounds_used} rounds, "
        f"{investigation.tool_calls_used} tool calls"
    )
    print(f"duration      : {investigation.duration_ms} ms")
    if investigation.error:
        print(f"error         : {investigation.error}")
    if investigation.report_id:
        print(f"draft report  : {investigation.report_id}")

    print()
    print("rounds")
    print(f"  {'#':>3}  {'outcome':16} {'latency':>9}  {'tools':>5}  error")
    for item in rounds:
        print(
            f"  {item.round_index:>3}  {item.outcome:16} "
            f"{item.latency_ms:>7} ms  {item.tool_call_count:>5}  "
            f"{item.error or ''}"
        )

    print()
    print("tool calls")
    if not calls:
        print("  (none)")
    else:
        print(f"  {'#':>3}  {'tool':22} {'status':9} {'ms':>6}  summary")
        for call in calls:
            print(
                f"  {call.sequence:>3}  {call.tool_name:22} {call.status:9} "
                f"{call.duration_ms:>4} ms  {call.result_summary or ''}"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one SentinelFlow investigation and print its trace."
    )
    parser.add_argument("--alert-id", required=True, help="alert UUID")
    parser.add_argument(
        "--username",
        default=None,
        help="admin username used as the investigation actor (default: first admin)",
    )
    args = parser.parse_args(argv)

    try:
        alert_id = uuid.UUID(args.alert_id)
    except ValueError:
        print("error: --alert-id must be a UUID", file=sys.stderr)
        return 2

    try:
        client = build_model_client()
    except ModelNotConfiguredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = get_settings()

    with get_session_factory()() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            print(f"error: alert {alert_id} not found", file=sys.stderr)
            return 2

        actor = _pick_actor(session, args.username)
        if actor is None:
            print(
                "error: no admin user found; create one with sentinelflow-create-user",
                file=sys.stderr,
            )
            return 2

        try:
            investigation = run_investigation(
                session,
                alert_id,
                user=actor,
                client=client,
                max_rounds=settings.agent_max_rounds,
                max_tool_calls=settings.agent_max_tool_calls,
                tool_timeout_seconds=settings.agent_tool_timeout_seconds,
                commit=True,
            )
        except InvestigationConflictError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        if investigation is None:
            print("error: investigation could not be created", file=sys.stderr)
            return 2

        _print_trace(session, investigation)
        return 0 if investigation.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
