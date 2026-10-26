"""Run the benchmark.

    python -m benchmark.runner                       # deterministic baseline only
    python -m benchmark.runner --baseline all --model self-test
    python -m benchmark.runner --baseline all --model real    # needs LLM_*
    python -m benchmark.runner --probe               # check the endpoint first

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

BASELINE_CAVEATS = {
    "deterministic": (
        "risk_level is copied from the alert's configured severity, which is an "
        "input to this baseline. Agreement with min_risk/max_risk is therefore "
        "tautological and must not be read as judgement quality."
    ),
    "single_shot": None,
    "agent": None,
}
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
    skipped: list[dict[str, str]] = []

    try:
        for case in cases:
            for name in baselines:
                if name not in case.applicable_to:
                    continue
                if case.requires_fault_injection and model_mode != "none":
                    # A real model cannot be forced to time out or to fabricate
                    # a citation. Running the case anyway would score the model
                    # on a failure it has no way to produce.
                    skipped.append({"case": case.id, "baseline": name})
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
        "skipped": skipped,
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
            "caveat": BASELINE_CAVEATS.get(name),
            "metrics": [asdict(metric) for metric in metrics],
            "cases": [
                {
                    "id": case.id,
                    "scenario": case.scenario,
                    "produced_answer": result.produced_answer,
                    "risk_level": result.risk_level,
                    # Kept so a verdict can be audited later; the text is the
                    # model's own, and is what the refusal check reads.
                    "summary": result.summary,
                    "reasoning": result.reasoning,
                    "limitations": result.limitations,
                    "refused": result.refused,
                    "citations": len(result.cited_ids),
                    "citations_valid": result.citations_valid,
                    "tool_calls": result.tool_calls,
                    "meets_expectation": meets_expectation(case, result),
                    "error": result.error,
                    "latency_ms": result.latency_ms,
                    "model_calls": result.model_calls,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
                for case, result in pairs
            ],
        }
    return payload


def _print(payload: dict) -> None:
    print(f"mode: {payload['mode']}  cases: {payload['cases']}")
    print(f"note: {payload['disclaimer']}")
    if payload["skipped"]:
        ids = sorted({item["case"] for item in payload["skipped"]})
        print(
            f"skipped {len(ids)} fault-injection case(s) for model baselines: "
            + ", ".join(ids)
        )
        print("  (a real model cannot be forced to fail; covered by tests/)")
    for name, block in payload["baselines"].items():
        print()
        print(f"== {name} ({block['applicable_cases']} applicable cases)")
        if block.get("caveat"):
            print(f"   caveat: {block['caveat']}")
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


def _verdicts(payload: dict) -> dict[tuple[str, str], tuple]:
    return {
        (name, row["id"]): (row["meets_expectation"], row["risk_level"])
        for name, block in payload["baselines"].items()
        for row in block["cases"]
    }


def _stability(runs: list[dict]) -> dict:
    """Which verdicts changed between runs, and how far each rate moved."""
    first = _verdicts(runs[0])
    flips = []
    for key, expected in first.items():
        for index, other in enumerate(runs[1:], start=2):
            actual = _verdicts(other)[key]
            if actual != expected:
                flips.append(
                    {
                        "baseline": key[0],
                        "case": key[1],
                        "run": index,
                        "first": expected,
                        "then": actual,
                    }
                )

    rates: dict[str, dict[str, list[float]]] = {}
    for name in runs[0]["baselines"]:
        rates[name] = {}
        for metric in runs[0]["baselines"][name]["metrics"]:
            if not metric["measured"] or metric["value"] is None:
                continue
            values = [
                next(
                    item["value"]
                    for item in doc["baselines"][name]["metrics"]
                    if item["key"] == metric["key"]
                )
                for doc in runs
            ]
            rates[name][metric["key"]] = values
    return {"flips": flips, "rates": rates}


def _print_stability(stability: dict, runs: int) -> None:
    print()
    print(f"== stability over {runs} runs")
    flips = stability["flips"]
    if flips:
        print(f"  {len(flips)} verdict flip(s) between runs:")
        for item in flips:
            print(
                f"    {item['baseline']}/{item['case']}: run1={item['first']} "
                f"run{item['run']}={item['then']}"
            )
    else:
        print("  every verdict was identical across runs")

    for name, metrics in stability["rates"].items():
        spread = [
            (key, values)
            for key, values in metrics.items()
            if len(set(values)) > 1
        ]
        if not spread:
            continue
        for key, values in spread:
            shown = ", ".join(f"{value:.0%}" if value <= 1 else f"{value:.0f}" for value in values)
            print(f"  {name}/{key}: {shown}")


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
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=(
            "run the suite N times and report verdict stability. A hosted model "
            "is not bit-reproducible even at temperature 0, so one run is a "
            "sample, not a constant."
        ),
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="check the configured endpoint with one tiny call, then exit",
    )
    args = parser.parse_args(argv)

    if args.probe:
        from benchmark.preflight import probe

        return probe()

    baselines = list(ALL_BASELINES) if args.baseline == "all" else [args.baseline]
    if any(name != "deterministic" for name in baselines) and args.model == "none":
        print("model baselines need --model self-test or --model real", file=sys.stderr)
        return 2

    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    try:
        runs = [run(baselines, args.model) for _ in range(args.repeat)]
    except ModelNotConfiguredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = runs[0]
    _print(payload)
    if len(runs) > 1:
        stability = _stability(runs)
        payload["repeat"] = {"runs": len(runs), **stability}
        _print_stability(stability, len(runs))
    Path(args.json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"report written to {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
