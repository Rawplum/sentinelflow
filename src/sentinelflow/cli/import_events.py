"""Import synthetic JSONL events into the configured database.

Usage:
    sentinelflow-import data/sample_events.jsonl
    python -m sentinelflow.cli.import_events data/sample_events.jsonl

Invalid lines are reported and skipped. Duplicate event IDs are skipped by the
import service, making repeated imports safe.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from sentinelflow.db.session import get_session_factory
from sentinelflow.schemas.events import SecurityEventCreate
from sentinelflow.services.events import import_events

DEFAULT_BATCH_SIZE = 500


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import validated security events from a JSONL file."
    )
    parser.add_argument("path", help="Path to a UTF-8 JSONL file")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Events per database transaction (1-{DEFAULT_BATCH_SIZE}, default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Exit with status 1 if any line fails validation",
    )
    return parser


def _parse_line(line: str) -> SecurityEventCreate:
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("each JSONL line must be a JSON object")
    return SecurityEventCreate.model_validate(payload)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= DEFAULT_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {DEFAULT_BATCH_SIZE}")

    path = Path(args.path)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    valid_events: list[SecurityEventCreate] = []
    errors: list[dict[str, Any]] = []
    records_seen = 0

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                records_seen += 1
                try:
                    valid_events.append(_parse_line(stripped))
                except json.JSONDecodeError as exc:
                    errors.append(
                        {
                            "line": line_number,
                            "error": f"invalid JSON: {exc.msg}",
                        }
                    )
                except (ValidationError, ValueError) as exc:
                    errors.append({"line": line_number, "error": str(exc)})
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    received = 0
    imported = 0
    skipped_ids: list[str] = []

    try:
        session_factory = get_session_factory()
        with session_factory() as session:
            for start in range(0, len(valid_events), args.batch_size):
                batch = valid_events[start : start + args.batch_size]
                result = import_events(session, batch)
                received += result.received
                imported += result.imported
                skipped_ids.extend(str(event_id) for event_id in result.skipped_event_ids)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("error: database operation failed", file=sys.stderr)
        return 2

    summary = {
        "file": str(path),
        "records_seen": records_seen,
        "valid_records": len(valid_events),
        "invalid_records": len(errors),
        "received": received,
        "imported": imported,
        "skipped": len(skipped_ids),
        "skipped_event_ids": skipped_ids,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.fail_on_invalid and errors:
        return 1
    if not valid_events:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
