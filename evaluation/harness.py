"""Evaluation harness.

Runs the JSON case set through the real HTTP API with a scripted model client.
No real model provider is contacted: these cases measure *orchestration*
correctness (does the pipeline enforce limits, validate citations, block
forbidden tools), not the analytical quality of a language model.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).resolve().parent / "cases.json"

# The scripted client and helpers live in tests/support so that the pytest
# suite and this harness exercise exactly the same doubles.
_TESTS_DIR = str(PROJECT_ROOT / "tests")
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinelflow.ai.model_client import (  # noqa: E402
    AgentFindings,
    ModelClientError,
    ModelTurn,
    ToolCallRequest,
)
from sentinelflow.ai.tools import TOOL_SPECS, ToolSpec  # noqa: E402
from sentinelflow.api.routes.investigations import provide_model_client  # noqa: E402
from sentinelflow.core.config import get_settings  # noqa: E402
from sentinelflow.core.permissions import UserRole  # noqa: E402
from sentinelflow.db.session import Base, get_db  # noqa: E402
from sentinelflow.main import create_app  # noqa: E402
from sentinelflow.models.alert import Alert  # noqa: E402
from sentinelflow.models.security_event import SecurityEvent  # noqa: E402
from sentinelflow.schemas.alerts import InvestigationReportResponse  # noqa: E402
from sentinelflow.services.auth import create_user  # noqa: E402
from sentinelflow.services.investigation_worker import process_one  # noqa: E402
from support import ScriptedClient  # noqa: E402

ADMIN_USER = "eval.admin"
ADMIN_PASSWORD = "eval-admin-password-123"
ANALYST_USER = "eval.analyst"
ANALYST_PASSWORD = "eval-analyst-password-123"


@dataclass
class CaseResult:
    case_id: str
    name: str
    category: str
    status: str | None = None
    http_status: int = 0
    report_created: bool = False
    report: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    duration_ms: int | None = None
    injection_marker_found: bool = False
    expected_status: str | None = None
    citations_valid: bool | None = None
    report_schema_valid: bool | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _utcnow() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _patched_tool(name: str, mode: str) -> Iterator[None]:
    """Temporarily replace a tool handler to simulate failure or slowness."""
    original = TOOL_SPECS[name]

    def handler(_context, _params):
        if mode == "fail":
            raise RuntimeError("simulated tool failure")
        time.sleep(0.4)
        return {"returned": 0, "events": []}

    TOOL_SPECS[name] = ToolSpec(
        name=original.name,
        description=original.description,
        input_model=original.input_model,
        required_permission=original.required_permission,
        handler=handler,
    )
    try:
        yield
    finally:
        TOOL_SPECS[name] = original


class Harness:
    """One isolated database, one app, reused across cases."""

    #: Fixed for the whole run so tokens stay valid if the settings cache is
    #: cleared by another test fixture between cases.
    SECRET = "evaluation-only-secret-" + "x" * 32

    def _ensure_settings(self) -> None:
        os.environ["JWT_SECRET"] = self.SECRET
        os.environ.setdefault("APP_ENV", "evaluation")
        get_settings.cache_clear()

    def __init__(self) -> None:
        self._ensure_settings()

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

        self.app = create_app()
        self.app.dependency_overrides[get_db] = self._get_db

        with self.session_factory() as session:
            create_user(
                session,
                username=ADMIN_USER,
                password=ADMIN_PASSWORD,
                role=UserRole.ADMIN,
            )
            create_user(
                session,
                username=ANALYST_USER,
                password=ANALYST_PASSWORD,
                role=UserRole.ANALYST,
            )

        self.admin = TestClient(self.app)
        self.analyst = TestClient(self.app)
        self.admin.headers.update(
            {"Authorization": f"Bearer {self._login(ADMIN_USER, ADMIN_PASSWORD)}"}
        )
        self.analyst.headers.update(
            {"Authorization": f"Bearer {self._login(ANALYST_USER, ANALYST_PASSWORD)}"}
        )

    def _get_db(self):
        with self.session_factory() as session:
            yield session

    def _login(self, username: str, password: str) -> str:
        response = self.admin.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    # --- seeding -----------------------------------------------------------

    def seed_alert(self, spec: dict[str, Any]) -> tuple[uuid.UUID, list[uuid.UUID]]:
        count = int(spec.get("evidence_count", 5))
        username = spec.get("username", "alice.demo")
        source_ip = spec.get("source_ip", "198.51.100.10")
        injection = spec.get("inject_message")

        base = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
        with self.session_factory() as session:
            events = []
            for index in range(count):
                raw = f"synthetic failure {index}"
                if injection and index == int(injection.get("index", 0)):
                    raw = str(injection.get("text", raw))
                events.append(
                    SecurityEvent(
                        event_id=uuid.uuid4(),
                        timestamp=base + timedelta(minutes=index),
                        event_type="authentication",
                        username=username,
                        source_ip=source_ip,
                        asset_id="asset-01",
                        action="login",
                        outcome="failure",
                        raw_message=raw,
                        source="synthetic-auth",
                    )
                )
            session.add_all(events)

            alert = Alert(
                rule_id="AUTH-001",
                rule_version="1.0.0",
                title="Suspicious login activity",
                description=f"{count} failed authentication attempts for '{username}'.",
                severity=spec.get("severity", "high"),
                status="open",
                first_seen_at=base,
                last_seen_at=base + timedelta(minutes=max(count - 1, 0)),
                event_count=count,
                dedup_key=f"AUTH-001:{uuid.uuid4().hex}",
            )
            alert.evidence_events = events
            session.add(alert)
            session.commit()
            return alert.id, [event.event_id for event in events]

    # --- scripted model ----------------------------------------------------

    def _build_turns(
        self,
        script: list[dict[str, Any]],
        evidence_ids: list[uuid.UUID],
        alert_id: uuid.UUID,
    ) -> list[ModelTurn | BaseException]:
        turns: list[ModelTurn | BaseException] = []
        for index, item in enumerate(script):
            if "error" in item:
                turns.append(ModelClientError(str(item["error"])))
                continue
            if "tool" in item:
                arguments = {
                    key: (str(alert_id) if value == "$alert" else value)
                    for key, value in (item.get("arguments") or {}).items()
                }
                turns.append(
                    ModelTurn(
                        tool_calls=[
                            ToolCallRequest(
                                call_id=f"call-{index}",
                                name=item["tool"],
                                arguments=arguments,
                            )
                        ]
                    )
                )
                continue
            payload = dict(item["findings"])
            payload["cited_event_ids"] = self._resolve_citations(
                item.get("cite", []), evidence_ids
            )
            turns.append(ModelTurn(findings=AgentFindings.model_validate(payload)))
        return turns

    @staticmethod
    def _resolve_citations(spec: list[str], evidence_ids: list[uuid.UUID]) -> list[str]:
        resolved: list[str] = []
        for item in spec:
            if isinstance(item, str) and item.startswith("$"):
                index = int(item[1:])
                resolved.append(str(evidence_ids[index]))
            else:
                resolved.append(str(item))
        return resolved

    # --- execution ---------------------------------------------------------

    def run_case(self, case: dict[str, Any]) -> CaseResult:
        result = CaseResult(
            case_id=case["id"],
            name=case["name"],
            category=case.get("category", "general"),
            expected_status=(case.get("expect") or {}).get("status"),
        )
        self._ensure_settings()
        alert_id, evidence_ids = self.seed_alert(case.get("alert", {}))

        if case.get("kind") == "api":
            return self._run_api_case(case, alert_id, result)

        turns = self._build_turns(case.get("script", []), evidence_ids, alert_id)
        client = ScriptedClient(turns)
        self.app.dependency_overrides[provide_model_client] = lambda: client

        limits = case.get("limits") or {}
        patches = []
        if "inject_tool_failure" in case:
            patches.append((case["inject_tool_failure"], "fail"))
        if "inject_tool_timeout" in case:
            patches.append((case["inject_tool_timeout"], "slow"))

        try:
            with ExitStack() as stack:
                stack.enter_context(self._applied_limits(limits))
                for name, mode in patches:
                    stack.enter_context(_patched_tool(name, mode))

                created = self.admin.post(f"/api/v1/alerts/{alert_id}/investigations")
                result.http_status = created.status_code
                if created.status_code != 202:
                    result.failures.append(
                        f"expected 202 from POST, got {created.status_code}"
                    )
                    return result
                investigation_id = created.json()["id"]
                # The worker thread is disabled in evaluation: drain the durable
                # queue through the same claim/execute path the worker uses.
                self._drain(client)
                final = self.admin.get(f"/api/v1/investigations/{investigation_id}")
        except Exception as exc:
            result.failures.append(f"harness error: {exc.__class__.__name__}: {exc}")
            return result

        if final.status_code != 200:
            result.failures.append(f"GET returned {final.status_code}")
            return result

        body = final.json()
        result.status = body["status"]
        result.error = body.get("error")
        result.tool_calls = body.get("tool_calls") or []
        result.rounds = body.get("rounds") or []
        result.duration_ms = body.get("duration_ms")

        marker = (case.get("expect") or {}).get("injection_marker")
        if marker:
            result.injection_marker_found = any(
                marker in json.dumps(turn, ensure_ascii=False)
                for transcript in client.transcripts
                for turn in transcript
            )

        if body.get("report_id"):
            report_response = self.admin.get(f"/api/v1/reports/{body['report_id']}")
            if report_response.status_code == 200:
                result.report = report_response.json()["content"]
                result.report_created = True

        if result.report is not None:
            known = {str(item) for item in evidence_ids}
            cited = {
                str(item["event_id"]) for item in result.report.get("evidence", [])
            }
            result.citations_valid = bool(cited) and cited <= known
            try:
                InvestigationReportResponse.model_validate(result.report)
                result.report_schema_valid = True
            except Exception:
                result.report_schema_valid = False

        result.failures.extend(
            self._check(case.get("expect") or {}, result, evidence_ids)
        )
        return result

    def _drain(self, client) -> int:
        settings = get_settings()
        processed = 0
        while processed < 10:
            with self.session_factory() as session:
                result = process_one(
                    session,
                    client=client,
                    lease_seconds=settings.agent_lease_seconds,
                    max_rounds=settings.agent_max_rounds,
                    max_tool_calls=settings.agent_max_tool_calls,
                    tool_timeout_seconds=settings.agent_tool_timeout_seconds,
                )
            if result is None:
                break
            processed += 1
        return processed

    def _run_api_case(
        self, case: dict[str, Any], alert_id: uuid.UUID, result: CaseResult
    ) -> CaseResult:
        response = self.analyst.post(f"/api/v1/alerts/{alert_id}/investigations")
        result.http_status = response.status_code
        expected = (case.get("expect") or {}).get("http_status")
        if expected is not None and response.status_code != expected:
            result.failures.append(
                f"expected HTTP {expected}, got {response.status_code}"
            )
        return result

    @contextmanager
    def _applied_limits(self, limits: dict[str, Any]) -> Iterator[None]:
        if not limits:
            yield
            return
        settings = get_settings()
        mapping = {
            key if hasattr(settings, key) else f"agent_{key}": value
            for key, value in limits.items()
        }
        saved = {key: getattr(settings, key) for key in mapping}
        for key, value in mapping.items():
            setattr(settings, key, value)
        try:
            yield
        finally:
            for key, value in saved.items():
                setattr(settings, key, value)

    # --- expectations ------------------------------------------------------

    def _check(
        self,
        expect: dict[str, Any],
        result: CaseResult,
        evidence_ids: list[uuid.UUID],
    ) -> list[str]:
        failures: list[str] = []

        if "status" in expect and result.status != expect["status"]:
            failures.append(f"status: expected {expect['status']}, got {result.status}")

        if "report" in expect and result.report_created != expect["report"]:
            failures.append(
                f"report: expected {expect['report']}, got {result.report_created}"
            )

        if "error_contains" in expect:
            needle = expect["error_contains"]
            if needle not in (result.error or ""):
                failures.append(f"error: expected to contain {needle!r}")

        if "tool_calls" in expect:
            low, high = expect["tool_calls"]
            if not low <= len(result.tool_calls) <= high:
                failures.append(
                    f"tool_calls: expected {low}..{high}, got {len(result.tool_calls)}"
                )

        if "rounds" in expect:
            low, high = expect["rounds"]
            if not low <= len(result.rounds) <= high:
                failures.append(
                    f"rounds: expected {low}..{high}, got {len(result.rounds)}"
                )

        if "tool_statuses" in expect:
            actual = [call["status"] for call in result.tool_calls]
            if actual != expect["tool_statuses"]:
                failures.append(
                    f"tool_statuses: expected {expect['tool_statuses']}, got {actual}"
                )

        if "round_outcomes" in expect:
            actual = [item["outcome"] for item in result.rounds]
            if actual != expect["round_outcomes"]:
                failures.append(
                    f"round_outcomes: expected {expect['round_outcomes']}, got {actual}"
                )

        for tool in expect.get("denied_tools", []):
            denied = [
                call
                for call in result.tool_calls
                if call["tool_name"] == tool and call["status"] == "denied"
            ]
            if not denied:
                failures.append(f"denied: {tool} was not recorded as denied")

        for tool in expect.get("forbidden_never_ok", []):
            executed = [
                call
                for call in result.tool_calls
                if call["tool_name"] == tool and call["status"] == "ok"
            ]
            if executed:
                failures.append(f"safety: forbidden tool {tool} executed successfully")

        if expect.get("all_citations_valid") and result.report:
            known = {str(item) for item in evidence_ids}
            cited = {
                str(item["event_id"]) for item in result.report.get("evidence", [])
            }
            if not cited:
                failures.append("citations: report cites no evidence")
            unknown = cited - known
            if unknown:
                failures.append(f"citations: unknown event ids {sorted(unknown)}")

        for needle in expect.get("report_contains", []):
            haystack = json.dumps(result.report or {}, ensure_ascii=False).lower()
            if needle.lower() not in haystack:
                failures.append(f"report: expected to contain {needle!r}")

        if "empty_result_tool" in expect:
            tool = expect["empty_result_tool"]
            matches = [call for call in result.tool_calls if call["tool_name"] == tool]
            if not matches:
                failures.append(f"empty_result: {tool} was not called")
            elif (matches[0].get("result_summary") or {}).get("returned") != 0:
                failures.append(
                    "empty_result: expected returned=0, got "
                    f"{matches[0].get('result_summary')}"
                )

        marker = expect.get("injection_marker")
        if marker:
            if (
                expect.get("injection_must_reach_tools")
                and not result.injection_marker_found
            ):
                failures.append(
                    "injection: marker never reached the model as tool data"
                )
            # The marker must never appear as an executed tool call.
            executed = [
                call
                for call in result.tool_calls
                if call["status"] == "ok" and "delete" in call["tool_name"]
            ]
            if executed:
                failures.append("injection: a destructive tool executed")

        return failures

    def close(self) -> None:
        self.app.dependency_overrides.clear()
        self.admin.close()
        self.analyst.close()
        self.engine.dispose()
