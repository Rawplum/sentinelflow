"""Benchmark harness tests.

These assert that the harness works and that the numbers it prints are honest.
They do **not** measure model quality: the model baselines run against a canned
double, which is why the reports label them as self-test.
"""

from __future__ import annotations

from sentinelflow.ai.model_client import ModelTurn

from benchmark.baselines import EchoToolClient
from benchmark.dataset import load_cases
from benchmark.metrics import meets_expectation
from benchmark.runner import run

from support import ScriptedClient, evidence_ids, findings


def _metric(payload, baseline, key):
    block = payload["baselines"][baseline]
    return next(item for item in block["metrics"] if item["key"] == key)


def test_dataset_covers_every_required_scenario() -> None:
    scenarios = {case.scenario for case in load_cases()}

    assert {
        "suspicious",
        "benign",
        "insufficient",
        "multi_step",
        "contradictory",
        "tool_failure",
        "malicious",
        "invalid_citation",
        "model_failure",
    } <= scenarios


def test_dataset_is_synthetic_and_deterministic() -> None:
    first = load_cases()
    second = load_cases()

    assert [case.id for case in first] == [case.id for case in second]
    for case in first:
        assert case.spec["alert"]["username"].endswith(".demo")
        assert "production" not in case.description.lower()


def test_deterministic_baseline_completes_every_applicable_case() -> None:
    payload = run(["deterministic"], "none")

    assert payload["mode"] == "no_model"
    metric = _metric(payload, "deterministic", "task_completion_rate")
    assert metric["measured"] is True
    assert metric["numerator"] == metric["denominator"] > 0


def test_deterministic_baseline_cannot_refuse_insufficient_evidence() -> None:
    """A real, documented limitation of the rule engine - not a harness bug.

    The rule always emits a conclusion with a risk level, so it scores 0 on
    "says it cannot conclude". Recording this is the point of the baseline.
    """
    payload = run(["deterministic"], "none")

    refusal = _metric(payload, "deterministic", "refusal_appropriateness")
    assert refusal["denominator"] == 2
    assert refusal["numerator"] == 0

    misses = [
        row["id"]
        for row in payload["baselines"]["deterministic"]["cases"]
        if not row["meets_expectation"]
    ]
    assert set(misses) == {"insufficient_single_event", "contradictory_timestamps"}


def test_agent_baseline_answers_with_valid_citations() -> None:
    payload = run(["agent"], "self-test")

    block = payload["baselines"]["agent"]
    assert block["applicable_cases"] == 9
    answered = [row for row in block["cases"] if row["produced_answer"]]
    assert len(answered) == 9
    assert all(row["citations_valid"] for row in answered)

    tool_metric = _metric(payload, "agent", "tool_call_success_rate")
    assert tool_metric["measured"] is True
    assert tool_metric["numerator"] == tool_metric["denominator"] > 0


def test_self_test_mode_is_labelled_and_costs_are_not_claimed() -> None:
    payload = run(["agent"], "self-test")

    assert payload["mode"] == "self_test"
    assert "only in --model real mode" in payload["disclaimer"]
    assert _metric(payload, "agent", "model_cost")["measured"] is False
    assert _metric(payload, "agent", "avg_latency_ms")["measured"] is False


def test_benchmark_verdicts_are_repeatable() -> None:
    first = run(["deterministic", "agent"], "self-test")
    second = run(["deterministic", "agent"], "self-test")

    def signature(payload):
        return {
            name: [
                (row["id"], row["produced_answer"], row["risk_level"], row["citations"])
                for row in block["cases"]
            ]
            for name, block in payload["baselines"].items()
        }

    assert signature(first) == signature(second)


def test_expectation_matcher_handles_risk_bounds() -> None:
    from benchmark.baselines import BaselineResult

    case = next(item for item in load_cases() if item.id == "suspicious_bruteforce")
    high = BaselineResult(
        baseline="x",
        case_id=case.id,
        scenario=case.scenario,
        produced_answer=True,
        risk_level="high",
        cited_ids=["a"],
    )
    low = BaselineResult(
        baseline="x",
        case_id=case.id,
        scenario=case.scenario,
        produced_answer=True,
        risk_level="low",
        cited_ids=["a"],
    )

    assert meets_expectation(case, high) is True
    assert meets_expectation(case, low) is False


def test_synchronous_investigation_actually_runs(
    app, alert_factory, admin_user, session_factory
) -> None:
    """Regression guard: the sync helper must claim and execute, not just queue.

    Before this was fixed it created a `pending` row and returned immediately,
    which also silently broke `sentinelflow-investigate`.
    """
    from sentinelflow.services.investigations import run_investigation

    alert_id = alert_factory(evidence_count=4)
    cited = evidence_ids(session_factory, alert_id)[:1]

    with session_factory() as session:
        user = session.get(type(admin_user), admin_user.id)
        investigation = run_investigation(
            session,
            alert_id,
            user=user,
            client=ScriptedClient([ModelTurn(findings=findings([cited[0]]))]),
            max_rounds=5,
            max_tool_calls=8,
            tool_timeout_seconds=5,
            commit=True,
        )

    assert investigation is not None
    assert investigation.status == "succeeded"
    assert investigation.attempt_count == 1
    assert investigation.rounds_used >= 1
    assert investigation.report_id is not None
