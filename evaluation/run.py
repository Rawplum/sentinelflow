"""Command line entry point for the agent evaluation suite.

Usage:
    python -m evaluation.run                 # run every case
    python -m evaluation.run --case normal_investigation
    python -m evaluation.run --json out.json

Exit code is 0 only when every case passes. The report is always written to
``evaluation/last_report.json`` so a run can be inspected after the fact.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from evaluation.harness import Harness, load_cases
from evaluation.metrics import compute

DEFAULT_REPORT = Path(__file__).resolve().parent / "last_report.json"


def _print_case_table(results) -> None:
    header = f"{'case':32} {'category':20} {'status':14} {'report':7} {'tools':6} {'rounds':7} {'ms':7} result"
    print(header)
    print("-" * len(header))
    for item in results:
        status = item.status or f"HTTP {item.http_status}"
        print(
            f"{item.case_id:32} {item.category:20} {status:14} "
            f"{'yes' if item.report_created else 'no':7} "
            f"{len(item.tool_calls):<6} {len(item.rounds):<7} "
            f"{item.duration_ms if item.duration_ms is not None else '-':<7} "
            f"{'PASS' if item.passed else 'FAIL'}"
        )
        for failure in item.failures:
            print(f"{'':32}   - {failure}")


def _print_metrics(report) -> None:
    print()
    print(f"cases: {report.passed_cases}/{report.total_cases} passed")
    print()
    print(f"{'metric':34} {'value':28} formula")
    print("-" * 110)
    for metric in report.metrics:
        print(f"{metric.key:34} {metric.display:28} {metric.formula}")
        if metric.note:
            print(f"{'':34} note: {metric.note}")


def _verdict_signature(results) -> list[tuple]:
    """Stable per-case verdict used to prove repeatability.

    Wall-clock durations are deliberately excluded: they legitimately vary and
    are not part of a verdict.
    """
    return [
        (
            item.case_id,
            item.passed,
            item.status,
            item.http_status,
            item.report_created,
            len(item.rounds),
            tuple(call["status"] for call in item.tool_calls),
            item.error,
        )
        for item in results
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the SentinelFlow agent evaluation suite."
    )
    parser.add_argument(
        "--case", action="append", dest="cases", help="run only these case ids"
    )
    parser.add_argument("--json", dest="json_path", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run the suite N times and verify every run reaches the same verdicts",
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.cases:
        wanted = set(args.cases)
        cases = [case for case in cases if case["id"] in wanted]
        if not cases:
            print(f"no case matched {sorted(wanted)}", file=sys.stderr)
            return 2

    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    harness = Harness()
    runs = []
    try:
        for run_index in range(1, args.repeat + 1):
            results = [harness.run_case(case) for case in cases]
            runs.append(results)
            if args.repeat > 1:
                passed = sum(1 for item in results if item.passed)
                print(f"run {run_index}/{args.repeat}: {passed}/{len(results)} passed")
    finally:
        harness.close()

    results = runs[0]
    metrics = compute(results)
    _print_case_table(results)
    _print_metrics(metrics)

    signatures = [_verdict_signature(run) for run in runs]
    stable = all(sig == signatures[0] for sig in signatures)
    if args.repeat > 1:
        print()
        print(
            f"repeatability: {args.repeat}/{args.repeat} runs identical verdicts"
            if stable
            else "repeatability: UNSTABLE — runs disagreed"
        )
        if not stable:
            for index, sig in enumerate(signatures[1:], start=2):
                # Lengths can differ when one run errored on a case.
                for expected, actual in zip(signatures[0], sig, strict=False):
                    if expected != actual:
                        print(f"  run {index} differs: {expected} != {actual}")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "scripted-mock",
        "disclaimer": (
            "Runs against a scripted model client. Measures orchestration and "
            "safety behaviour, not the analytical quality of a real model."
        ),
        "summary": {
            "total_cases": metrics.total_cases,
            "passed_cases": metrics.passed_cases,
        },
        "cases": [
            {
                "id": item.case_id,
                "name": item.name,
                "category": item.category,
                "passed": item.passed,
                "status": item.status,
                "http_status": item.http_status,
                "report_created": item.report_created,
                "tool_calls": len(item.tool_calls),
                "rounds": len(item.rounds),
                "duration_ms": item.duration_ms,
                "error": item.error,
                "failures": item.failures,
            }
            for item in results
        ],
        "metrics": [
            {
                "key": metric.key,
                "label": metric.label,
                "formula": metric.formula,
                "scope": metric.scope,
                "numerator": metric.numerator,
                "denominator": metric.denominator,
                "value": metric.value,
                "measured": metric.measured,
                "note": metric.note,
            }
            for metric in metrics.metrics
        ],
    }
    Path(args.json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"report written to {args.json_path}")

    if not stable:
        return 1
    return 0 if metrics.passed_cases == metrics.total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
