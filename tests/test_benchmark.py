"""Benchmark harness tests.

These assert that the harness works and that the numbers it prints are honest.
They do **not** measure model quality: the model baselines run against a canned
double, which is why the reports label them as self-test.
"""

from __future__ import annotations

import json

from sentinelflow.ai.model_client import ModelTurn
from sentinelflow.core.config import get_settings

from benchmark.baselines import EchoToolClient
from benchmark.dataset import load_cases
from benchmark.metrics import meets_expectation
from benchmark.runner import run

from support import ScriptedClient, evidence_ids, findings
from support.stub_provider import completion


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
    # The denominator must equal the number of cases that ask for a refusal, so
    # adding a case cannot silently dilute the metric.
    refusing = [
        case
        for case in load_cases()
        if case.expect.get("should_refuse") and "deterministic" in case.applicable_to
    ]
    assert refusal["denominator"] == len(refusing)
    # A template can only ever state the rule's own conclusion.
    assert refusal["numerator"] == 0

    misses = {
        row["id"]
        for row in payload["baselines"]["deterministic"]["cases"]
        if not row["meets_expectation"]
    }
    # The template fails exactly where uncertainty or an anomaly has to be
    # expressed. Anywhere else it passes, because the risk level it prints is
    # the severity it was handed.
    structural = {
        case.id
        for case in load_cases()
        if "deterministic" in case.applicable_to
        and (case.expect.get("should_refuse") or case.expect.get("must_mention_any"))
    }
    assert misses == structural


def test_agent_baseline_answers_with_valid_citations() -> None:
    payload = run(["agent"], "self-test")

    block = payload["baselines"]["agent"]
    # Three cases need an injected fault (timeout, bad citation, tool error).
    # A model baseline cannot reproduce those, so they are skipped and reported
    # rather than scored against a failure the model has no way to produce.
    expected = sum(
        1
        for case in load_cases()
        if "agent" in case.applicable_to and not case.requires_fault_injection
    )
    assert block["applicable_cases"] == expected
    assert {item["case"] for item in payload["skipped"]} == {
        "invalid_citation",
        "model_timeout",
        "tool_failure_recovery",
    }
    answered = [row for row in block["cases"] if row["produced_answer"]]
    assert len(answered) == expected
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


# --- preflight --------------------------------------------------------------


def test_fault_injection_cases_are_never_silently_dropped() -> None:
    """Skipping is allowed; hiding it is not."""
    payload = run(["agent"], "self-test")

    flagged = {
        case.id for case in load_cases() if case.requires_fault_injection
    }
    reported = {item["case"] for item in payload["skipped"]}

    assert flagged == reported
    assert flagged, "the dataset should still declare which cases need injection"


def test_deterministic_baseline_is_not_scored_on_its_own_input() -> None:
    """The rule engine copies risk from alert severity, so the caveat must show."""
    payload = run(["deterministic"], "none")

    assert payload["baselines"]["deterministic"]["caveat"]
    assert "tautological" in payload["baselines"]["deterministic"]["caveat"]


def test_preflight_fails_closed_without_configuration(monkeypatch) -> None:
    from benchmark.preflight import probe

    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_BASE", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    assert probe() == 2


def test_preflight_passes_against_a_working_endpoint(
    stub_provider, monkeypatch
) -> None:
    """A reachable endpoint that returns a valid findings object must pass."""
    from benchmark.preflight import probe

    stub_provider.responses.append(
        (
            200,
            completion(
                {
                    "content": json.dumps(
                        {
                            "summary": "connectivity check",
                            "risk_level": "low",
                            "reasoning": "probe",
                            "recommended_actions": ["none"],
                            "limitations": ["probe only"],
                            "cited_event_ids": [
                                "00000000-0000-4000-8000-000000000000"
                            ],
                        }
                    )
                }
            ),
        )
    )
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("LLM_API_BASE", stub_provider.base_url)
    monkeypatch.setenv("LLM_API_KEY", "sk-stub-not-a-real-key")
    get_settings.cache_clear()

    assert probe() == 0


def test_preflight_reports_a_rejected_key(stub_provider, monkeypatch) -> None:
    """A 401 must fail the probe instead of letting nine cases fail one by one."""
    from benchmark.preflight import probe

    stub_provider.responses.append((401, {"error": {"message": "bad key"}}))
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("LLM_API_BASE", stub_provider.base_url)
    monkeypatch.setenv("LLM_API_KEY", "sk-wrong")
    get_settings.cache_clear()

    assert probe() == 2


# --- scoring rules ----------------------------------------------------------


def test_anomaly_cases_ignore_the_limitations_boilerplate() -> None:
    """The rule report always says timestamps 'may be skewed'.

    If that counted as noticing the anomaly, the case would pass by boilerplate
    instead of by reading the data.
    """
    from benchmark.baselines import BaselineResult
    from benchmark.metrics import meets_expectation

    case = next(c for c in load_cases() if c.id == "contradictory_timestamps")
    boilerplate = BaselineResult(
        baseline="deterministic",
        case_id=case.id,
        scenario=case.scenario,
        produced_answer=True,
        risk_level="medium",
        summary="Rule AUTH-001 fired on 5 failed attempts.",
        reasoning="The rule counts failures in a window.",
        limitations=["Event timestamps may be inaccurate or skewed."],
        cited_ids=["a"],
    )
    assert meets_expectation(case, boilerplate) is False

    noticing = BaselineResult(
        baseline="agent",
        case_id=case.id,
        scenario=case.scenario,
        produced_answer=True,
        risk_level="high",
        summary="The success is sandwiched between failures.",
        reasoning="The evidence is internally contradictory: one event carries a "
        "clock skew marker.",
        limitations=["Ordering cannot be trusted."],
        cited_ids=["a"],
    )
    assert meets_expectation(case, noticing) is True


def test_repeat_reports_whether_verdicts_moved() -> None:
    from benchmark.runner import _stability

    first = run(["deterministic"], "none")
    second = run(["deterministic"], "none")

    stability = _stability([first, second])

    # The rule engine is deterministic, so nothing may move between runs.
    assert stability["flips"] == []
    assert stability["rates"]["deterministic"]["expectation_match_rate"]
