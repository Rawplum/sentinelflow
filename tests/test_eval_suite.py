"""Run the agent evaluation cases inside pytest.

The same cases can be run standalone with ``python -m evaluation.run``. Here
they are parametrized so a failure names the exact case.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.harness import Harness, load_cases  # noqa: E402
from evaluation.metrics import compute  # noqa: E402

CASES = load_cases()


@pytest.fixture(scope="module")
def harness():
    instance = Harness()
    try:
        yield instance
    finally:
        instance.close()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_evaluation_case(harness: Harness, case: dict) -> None:
    result = harness.run_case(case)
    assert result.passed, result.failures


def test_all_cases_are_covered(harness: Harness) -> None:
    """The suite must cover every scenario the day-5 scope promises."""
    covered = {case["category"] for case in CASES}

    assert {
        "happy_path",
        "insufficient_evidence",
        "multi_step",
        "empty_result",
        "model_failure",
        "tool_failure",
        "tool_timeout",
        "unauthorized_tool",
        "invalid_arguments",
        "invalid_citation",
        "budget",
        "prompt_injection",
        "authorization",
    } <= covered


def test_metrics_are_measured_not_assumed() -> None:
    """Metrics without data must report 'not measured', never a fake score."""
    results = [harness_result() for _ in range(1)]
    report = compute(results)

    cost = report.by_key("model_cost")
    assert cost.measured is False
    assert cost.value is None
    assert "not measured" in cost.display


def harness_result():
    from evaluation.harness import CaseResult

    return CaseResult(
        case_id="synthetic",
        name="synthetic",
        category="synthetic",
        status="succeeded",
        expected_status="succeeded",
        http_status=202,
        duration_ms=10,
    )
