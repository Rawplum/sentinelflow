"""Run the benchmark.

    python -m benchmark.runner                       # deterministic baseline only
    python -m benchmark.runner --baseline all --model self-test
    python -m benchmark.runner --baseline all --model real    # needs LLM_*

``--model real`` is the only mode whose model numbers are measurements.
``self-test`` runs a canned double to prove the harness works; its output is
explicitly labelled and must not be quoted as model performance.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sentinelflow.ai.model_client import ModelNotConfiguredError, build_model_client
from sentinelflow.core.permissions import UserRole
from sentinelflow.db.session import Base
from sentinelflow.services.auth import create_user

from benchmark.baselines import (
    BaselineResult,
    EchoToolClient,
    run_agent,
    run_deterministic,
    run_single_shot,
)
from benchmark.dataset import load_cases, seed
from benchmark.metrics import compute, meets_expectation

DEFAULT_REPORT = Path(__file__).resolve().parent / "last_report.json"
ALL_BASELINES = ("deterministic", "single_shot", "agent")


def _make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        create_user(
            session,
            username="bench.admin",
            password="bench-password-123",
            role=UserRole.ADMIN,
        )
    return engine, factory


def _client_for(mode: str):
    if mode == "real":
        return build_model_client()
    if mode == "self-test":
        return EchoToolClient()
    return None


def run(baselines: list[str], model_mode: str) -> dict:
    cases = load_cases()
    engine, factory = _make_db()
    results: dict[str, list[tuple]] = {name: [] for name in baselines}

    try:
        for case in cases:
            for name in baselines:
                if name not in case.applicable_to:
                    continue
                with factory() as session:
                    alert = seed(session, case)
                    session.commit()
                    user = session.scalar(
                        __import__("sqlalchemy").select(
                            __import__(
                                "sentinelflow.models.user", fromlist=["User"]
                            ).User
                        )
                    )
                    if name == "deterministic":
                        result = run_deterministic(session, alert)
                    elif name == "single_shot":
                        result = run_single_shot(_client_for(model_mode), session, alert)
                    else:
                        result = run_agent(_client_for(model_mode), session, alert, user)
                    result.case_id = case.id
                    result.scenario = case.scenario
                    results[name].append((case, result))
    finally:
        engine.dispose()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (
            "real"
            if model_mode == "real"
            else ("self_test" if model_mode == "self-test" else "no_model")
        ),
        "disclaimer": (
            "Deterministic numbers are real measurements of the rule engine. "
            "Model numbers are measurements only in --model real mode."
            if model_mode != "real"
            else "All numbers are real measurements."
        ),
        "cases": len(cases),
        "baselines": {},
    }

    for name in baselines:
        pairs = results[name]
        metrics = compute(
            name,
            pairs,
            mode="real" if model_mode == "real" else "self_test",
            has_tools=(name == "agent"),
        )
        payload["baselines"][name] = {
            "applicable_cases": len(pairs),
            "metrics": [asdict(metric) for metric in metrics],
            "cases": [
                {
                    "id": case.id,
                    "scenario": case.scenario,
                    "produced_answer": result.produced_answer,
                    "risk_level": result.risk_level,
                    "refused": result.refused,
                    "citations": len(result.cited_ids),
                    "citations_valid": result.citations_valid,
                    "tool_calls": result.tool_calls,
                    "meets_expectation": meets_expectation(case, result),
                    "error": result.error,
                    "latency_ms": result.latency_ms,
                }
                for case, result in pairs
            ],
        }
    return payload


def _print(payload: dict) -> None:
    print(f"mode: {payload['mode']}  cases: {payload['cases']}")
    print(f"note: {payload['disclaimer']}")
    for name, block in payload["baselines"].items():
        print()
        print(f"== {name} ({block['applicable_cases']} applicable cases)")
        print(f"  {'case':32} {'scenario':14} {'answer':6} {'risk':9} {'cite':6} {'expect':6}")
        for row in block["cases"]:
            print(
                f"  {row['id']:32} {row['scenario']:14} "
                f"{'yes' if row['produced_answer'] else 'no':6} "
                f"{row['risk_level'] or '-':9} "
                f"{row['citations']:<6} "
                f"{'ok' if row['meets_expectation'] else 'MISS':6}"
                + (f"  {row['error'][:40]}" if row["error"] else "")
            )
        print()
        for metric in block["metrics"]:
            value = metric["value"]
            if not metric["measured"] or value is None:
                shown = "not measured"
            elif metric["denominator"]:
                shown = f"{metric['numerator']}/{metric['denominator']} = {value:.0%}"
            else:
                shown = f"{value:.1f}"
            print(f"  {metric['key']:28} {shown}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SentinelFlow agent benchmark")
    parser.add_argument(
        "--baseline",
        choices=[*ALL_BASELINES, "all"],
        default="deterministic",
    )
    parser.add_argument(
        "--model",
        choices=["none", "self-test", "real"],
        default="none",
        help="'real' needs LLM_* configured; 'self-test' only validates the harness",
    )
    parser.add_argument("--json", dest="json_path", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    baselines = list(ALL_BASELINES) if args.baseline == "all" else [args.baseline]
    if any(name != "deterministic" for name in baselines) and args.model == "none":
        print("model baselines need --model self-test or --model real", file=sys.stderr)
        return 2

    try:
        payload = run(baselines, args.model)
    except ModelNotConfiguredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _print(payload)
    Path(args.json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"report written to {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
