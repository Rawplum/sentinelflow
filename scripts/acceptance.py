"""End-to-end acceptance run against a real server and a real database.

    python scripts/acceptance.py --database-url postgresql+psycopg://... --seed

Starts its own uvicorn process with a scripted model client (no API key, no
network), then walks the product the way a person would: log in, import logs,
run detection, open an alert, start an investigation, read the report, finalize
it, try the things that should be refused, and check the audit trail.

Every check prints PASS or FAIL with the reason. The exit code is 0 only when
all of them pass. Nothing here mocks the database or the HTTP layer: the only
stand-in is the model, which is a local HTTP server returning fixed turns.

This is the harness behind docs/V1_ACCEPTANCE.md. It is deliberately separate
from the pytest suite: pytest proves units and contracts, this proves the
product works when assembled.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from perf.harness import (
    Client,
    database_url,
    reset_database,
    running_server,
)

ADMIN = ("admin", "v1-admin-password-123")
ANALYST = ("analyst", "v1-analyst-password-123")

EVENT_TEMPLATE = {
    "event_type": "authentication",
    "username": "acceptance.demo",
    "source_ip": "198.51.100.77",
    "asset_id": "asset-v1",
    "action": "login",
    "outcome": "failure",
    "source": "acceptance-synthetic",
}


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def record(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, "PASS" if ok else "FAIL", detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52} {detail}")
        return ok

    def equal(self, name: str, actual, expected, detail: str = "") -> bool:
        ok = actual == expected
        return self.record(name, ok, detail or f"got {actual!r}, expected {expected!r}")

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [row for row in self.rows if row[1] == "FAIL"]


class StubModel:
    """A local OpenAI-compatible endpoint that answers without a network call.

    First turn asks for one tool call; the second reads the tool result and
    cites up to three real event ids from it, which is what the citation
    validator accepts.
    """

    def __init__(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                message = outer._reply(body)
                data = json.dumps(
                    {
                        "choices": [{"message": message}],
                        "usage": {"prompt_tokens": 80, "completion_tokens": 40},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        import threading

        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _reply(self, body: dict) -> dict:
        import re

        messages = body.get("messages", [])
        tool_messages = [item for item in messages if item.get("role") == "tool"]
        if not tool_messages:
            return {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_related_events",
                            "arguments": json.dumps({"limit": 20}),
                        },
                    }
                ]
            }

        found = re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            str(tool_messages[-1].get("content") or ""),
        )
        return {
            "content": json.dumps(
                {
                    "summary": "同一来源在 5 分钟内多次失败登录，随后成功登录。",
                    "risk_level": "high",
                    "reasoning": "失败集中在同一账号与同一来源地址。",
                    "recommended_actions": ["确认是否为账号主人操作", "必要时重置凭据"],
                    "limitations": ["仅基于认证日志", "本报告由验收用桩模型生成"],
                    "cited_event_ids": found[:3],
                }
            )
        }

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _event(index: int, *, outcome: str = "failure", minute: int | None = None) -> dict:
    # Template first: spreading it after "outcome" would silently overwrite the
    # argument with the template's default and turn every success into a failure.
    return {
        **EVENT_TEMPLATE,
        "event_id": str(uuid.uuid4()),
        "timestamp": f"2026-05-0{1 + index // 40}T{index % 24:02d}:{index % 60:02d}:00Z",
        "raw_message": f"acceptance synthetic event {index} outcome={outcome}",
        "outcome": outcome,
    }


def _burst(count: int = 6, start_minute: int = 0) -> list[dict]:
    rows = []
    for index in range(count):
        row = _event(index)
        row["timestamp"] = f"2026-05-01T03:{start_minute + index:02d}:00Z"
        rows.append(row)
    rows.append(
        {
            **_event(99, outcome="success"),
            "timestamp": f"2026-05-01T03:{start_minute + count:02d}:00Z",
            "raw_message": "acceptance synthetic success after the burst",
        }
    )
    return rows


def run(base_url: str, checks: Checks) -> dict:
    facts: dict = {}

    # --- authentication and roles ------------------------------------------
    admin = Client(base_url)
    status, body, _ = admin.request(
        "POST",
        "/api/v1/auth/login",
        {"username": ADMIN[0], "password": ADMIN[1]},
        auth=False,
    )
    checks.equal("login with correct password", status, 200)
    admin.token = json.loads(body)["access_token"]

    status, _, _ = Client(base_url).request(
        "POST",
        "/api/v1/auth/login",
        {"username": ADMIN[0], "password": "definitely-wrong"},
        auth=False,
    )
    checks.equal("login with wrong password is refused", status, 401)

    anonymous = Client(base_url)
    status, _, _ = anonymous.request("GET", "/api/v1/alerts")
    checks.equal("alert list requires a token", status, 401)

    bad_token = Client(base_url)
    bad_token.token = "not-a-jwt"
    status, _, _ = bad_token.request("GET", "/api/v1/alerts")
    checks.equal("malformed token is refused", status, 401)

    analyst = Client(base_url)
    status, body, _ = analyst.request(
        "POST",
        "/api/v1/auth/login",
        {"username": ANALYST[0], "password": ANALYST[1]},
        auth=False,
    )
    checks.equal("analyst can log in", status, 200)
    analyst.token = json.loads(body)["access_token"]

    status, _, _ = analyst.request("POST", "/api/v1/detections/run")
    checks.equal("analyst cannot run detection", status, 403)
    status, _, _ = analyst.request("GET", "/api/v1/alerts")
    checks.equal("analyst can read alerts", status, 200)

    # --- import and detection ----------------------------------------------
    rows = _burst()
    status, body, _ = admin.request("POST", "/api/v1/events/import", {"events": rows})
    imported = json.loads(body)
    checks.equal("import a burst of synthetic events", status, 201)
    facts["imported"] = imported.get("imported")
    checks.equal("every row was accepted", imported.get("imported"), len(rows))

    status, body, _ = admin.request("POST", "/api/v1/events/import", {"events": rows})
    duplicate = json.loads(body)
    checks.equal("re-importing the same batch is a no-op", status, 201)
    checks.equal("no row is created twice", duplicate.get("imported"), 0)
    checks.equal(
        "duplicates are reported, not silently dropped",
        duplicate.get("skipped"),
        len(rows),
    )

    status, _, _ = admin.request(
        "POST",
        "/api/v1/events/import",
        {"events": [{"event_id": "not-a-uuid"}]},
    )
    checks.equal("a malformed batch is rejected whole", status, 422)

    status, body, _ = admin.request("POST", "/api/v1/detections/run")
    detection = json.loads(body)
    checks.equal("detection runs", status, 200)
    checks.equal("one alert per burst", detection.get("alerts_created"), 1)
    alert_id = detection["created_alert_ids"][0]
    facts["alert_id"] = alert_id

    status, body, _ = admin.request("POST", "/api/v1/detections/run")
    repeat = json.loads(body)
    checks.equal(
        "re-running detection creates nothing", repeat.get("alerts_created"), 0
    )
    checks.equal(
        "re-running detection reports the skip",
        repeat.get("alerts_skipped_existing"),
        1,
    )

    status, body, _ = admin.request("GET", f"/api/v1/alerts/{alert_id}")
    alert = json.loads(body)
    checks.equal("alert detail is readable", status, 200)
    checks.equal("alert links the burst as evidence", alert["evidence_count"], 6)

    status, body, _ = admin.request("GET", "/api/v1/alerts?severity=high&limit=10")
    checks.equal("alert list filters by severity", status, 200)
    checks.equal("the filter returns the alert", json.loads(body)["total"], 1)

    status, body, _ = admin.request("GET", "/api/v1/events?limit=5&outcome=failure")
    page = json.loads(body)
    checks.equal("event list paginates", status, 200)
    checks.equal("page size is respected", len(page["items"]), 5)

    # --- status change ------------------------------------------------------
    status, body, _ = admin.request(
        "PATCH", f"/api/v1/alerts/{alert_id}", {"status": "acknowledged"}
    )
    checks.equal("alert can be acknowledged", status, 200)
    checks.equal("status is applied", json.loads(body)["status"], "acknowledged")

    status, _, _ = admin.request(
        "PATCH", f"/api/v1/alerts/{alert_id}", {"status": "open"}
    )
    checks.equal("an illegal transition is refused", status, 409)

    # --- investigation ------------------------------------------------------
    started = time.perf_counter()
    status, body, _ = admin.request("POST", f"/api/v1/alerts/{alert_id}/investigations")
    checks.equal("investigation is accepted", status, 202)
    investigation_id = json.loads(body)["id"]
    facts["investigation_id"] = investigation_id
    checks.record(
        "POST returns immediately",
        time.perf_counter() - started < 2.0,
        f"{(time.perf_counter() - started) * 1000:.0f} ms",
    )

    status, _, _ = admin.request("POST", f"/api/v1/alerts/{alert_id}/investigations")
    checks.equal("a second investigation is refused while one runs", status, 409)

    state = None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status, body, _ = admin.request(
            "GET", f"/api/v1/investigations/{investigation_id}"
        )
        payload = json.loads(body)
        state = payload["status"]
        if state not in ("pending", "running"):
            break
        time.sleep(0.25)

    checks.equal("investigation reaches a terminal state", state, "succeeded")
    checks.record(
        "investigation recorded its rounds",
        payload.get("rounds_used", 0) >= 1,
        f"rounds={payload.get('rounds_used')}",
    )
    checks.record(
        "investigation recorded its tool calls",
        payload.get("tool_calls_used", 0) >= 1,
        f"tool_calls={payload.get('tool_calls_used')}",
    )
    checks.record(
        "investigation recorded its steps",
        len(payload.get("rounds") or []) >= 1,
        f"steps={len(payload.get('rounds') or [])}",
    )
    report_id = payload.get("report_id")
    facts["report_id"] = report_id
    checks.record("investigation produced a report", bool(report_id), str(report_id))

    # --- report integrity ---------------------------------------------------
    status, body, _ = admin.request("GET", f"/api/v1/reports/{report_id}")
    report = json.loads(body)
    checks.equal("report is readable", status, 200)
    checks.equal("report starts as a draft", report["status"], "draft")
    checks.equal("report is version 1", report["version"], 1)

    cited = [item["event_id"] for item in report["content"].get("evidence", [])]
    checks.record("report cites evidence", len(cited) >= 1, f"{len(cited)} citations")

    _, evidence_body, _ = admin.request(
        "GET", f"/api/v1/alerts/{alert_id}/evidence?limit=200"
    )
    known = {item["event_id"] for item in json.loads(evidence_body)["items"]}
    checks.record(
        "every cited id belongs to this alert",
        set(cited) <= known,
        f"{len(set(cited) - known)} unknown",
    )

    _, evidence_body, _ = admin.request(
        "GET", f"/api/v1/alerts/{alert_id}/evidence?limit=2"
    )
    checks.equal(
        "evidence pagination caps the page", len(json.loads(evidence_body)["items"]), 2
    )

    # --- finalize and versioning -------------------------------------------
    status, body, _ = admin.request("POST", f"/api/v1/reports/{report_id}/finalize")
    finalized = json.loads(body)
    checks.equal("report can be finalized", status, 200)
    checks.equal("finalized report says so", finalized["status"], "finalized")
    checks.record(
        "finalized report records when", bool(finalized.get("finalized_at")), ""
    )

    status, _, _ = admin.request("POST", f"/api/v1/reports/{report_id}/finalize")
    checks.equal("finalizing twice is refused", status, 409)

    status, _, _ = analyst.request("POST", f"/api/v1/reports/{report_id}/finalize")
    checks.equal("analyst cannot finalize a report", status, 403)

    # A second investigation on the same alert must create version 2, not edit v1.
    status, body, _ = admin.request("POST", f"/api/v1/alerts/{alert_id}/investigations")
    checks.equal("a new investigation is allowed after the first finished", status, 202)
    second_id = json.loads(body)["id"]
    deadline = time.monotonic() + 90
    second_state = None
    while time.monotonic() < deadline:
        _, body, _ = admin.request("GET", f"/api/v1/investigations/{second_id}")
        second = json.loads(body)
        second_state = second["status"]
        if second_state not in ("pending", "running"):
            break
        time.sleep(0.25)
    checks.equal("second investigation finishes", second_state, "succeeded")

    status, body, _ = admin.request("GET", f"/api/v1/reports/{second['report_id']}")
    second_report = json.loads(body)
    checks.equal("second report is version 2", second_report["version"], 2)
    checks.equal("second report is a draft", second_report["status"], "draft")

    _, body, _ = admin.request("GET", f"/api/v1/reports/{report_id}")
    checks.equal(
        "the finalized version is untouched by the new draft",
        json.loads(body)["status"],
        "finalized",
    )

    # --- audit --------------------------------------------------------------
    status, body, _ = admin.request("GET", "/api/v1/audit-logs?limit=100")
    audit = json.loads(body)
    actions = {item["action"] for item in audit["items"]}
    checks.equal("audit log is readable", status, 200)
    for expected in (
        "auth.login",
        "events.import",
        "detections.run",
        "investigations.run",
        "alerts.status_change",
        "reports.finalize",
    ):
        checks.record(f"audit records {expected}", expected in actions, "")

    # Rows written by the CLI or the bootstrap path have no HTTP request, so no
    # request id; everything a request produced must carry one.
    without_request = [
        item
        for item in audit["items"]
        if not item.get("request_id") and item["action"] != "users.create"
    ]
    checks.record(
        "every request-scoped audit row carries a request id",
        not without_request,
        f"{len(without_request)} missing",
    )

    # --- logout -------------------------------------------------------------
    status, _, _ = admin.request("POST", "/api/v1/auth/logout")
    checks.equal("logout succeeds", status, 204)
    status, _, _ = admin.request("GET", "/api/v1/alerts")
    checks.equal("the token is dead after logout", status, 401)

    return facts


def run_security_checks(checks: Checks, base_url: str) -> None:
    """The things that must be refused.

    Kept separate from `run()` because these are negative assertions: each one
    passes only when the product says no. A regression here is usually silent
    (the request simply starts succeeding), which is why they are checked on
    every acceptance run rather than once by hand.
    """
    client = Client(base_url)
    client.login(ADMIN[0], ADMIN[1])

    # --- rate limiting -----------------------------------------------------
    # A fresh username, so the failed logins the business flow already made
    # against `admin` do not consume this budget.
    throttle = Client(base_url)
    codes = []
    for _ in range(7):
        status, _, _ = throttle.request(
            "POST",
            "/api/v1/auth/login",
            {"username": "throttle.probe", "password": "wrong"},
            auth=False,
        )
        codes.append(status)
    throttle.close()
    checks.record(
        "repeated failed logins are throttled",
        429 in codes,
        f"status codes {codes}",
    )

    # --- injection attempts are just strings -------------------------------
    for payload in ("' OR 1=1 --", "'; DROP TABLE security_events; --"):
        status, body, _ = client.request(
            "GET", f"/api/v1/events?username={quote(payload, safe='')}&limit=5"
        )
        checks.equal(f"filter value {payload!r} is not executed", status, 200)

    # --- error bodies do not describe the internals ------------------------
    status, body, _ = client.request(
        "POST", "/api/v1/events/import", {"events": [{"event_id": "nope"}]}
    )
    text = body.decode("utf-8", "replace").lower()
    leaked = [
        word
        for word in ("traceback", "sqlalchemy", "psycopg", "/src/", "line ")
        if word in text
    ]
    checks.equal("malformed event is rejected", status, 422)
    checks.record(
        "validation errors do not leak internals", not leaked, f"found {leaked}"
    )

    # --- oversized body ----------------------------------------------------
    # Its own client: the server answers 413 without reading the body, so the
    # connection is not reusable afterwards.
    big = Client(base_url)
    big.login(ADMIN[0], ADMIN[1])
    status, _, _ = big.request(
        "POST",
        "/api/v1/events/import",
        {"events": [], "pad": "x" * (6 * 1024 * 1024)},
    )
    big.close()
    checks.equal("oversized request body is rejected", status, 413)


def run_timeout_check(checks: Checks, database: str) -> None:
    """A provider that never answers must fail the task, not wedge the worker."""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    held: list[socket.socket] = []

    import threading

    def stall() -> None:
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            held.append(connection)

    threading.Thread(target=stall, daemon=True).start()

    try:
        with running_server(
            database_url(database),
            extra_env={
                "LLM_PROVIDER": "stub",
                "LLM_MODEL": "stub",
                "LLM_API_BASE": f"http://127.0.0.1:{port}/v1",
                "LLM_API_KEY": "sk-not-used",
                "LLM_TIMEOUT_SECONDS": "1",
                "AGENT_RETRY_BACKOFF_SECONDS": "1",
            },
        ) as server:
            client = Client(server.base)
            client.login(ADMIN[0], ADMIN[1])
            _, body, _ = client.request("GET", "/api/v1/alerts?limit=1")
            alert_id = json.loads(body)["items"][0]["id"]
            status, body, _ = client.request(
                "POST", f"/api/v1/alerts/{alert_id}/investigations"
            )
            checks.equal("a task is accepted while the model is dead", status, 202)
            investigation_id = json.loads(body)["id"]

            started = time.perf_counter()
            state, error_code = None, None
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                _, body, _ = client.request(
                    "GET", f"/api/v1/investigations/{investigation_id}"
                )
                payload = json.loads(body)
                state, error_code = payload["status"], payload.get("error_code")
                if state not in ("pending", "running"):
                    break
                time.sleep(0.2)

            elapsed = time.perf_counter() - started
            checks.equal("the task ends failed, not stuck", state, "failed")
            checks.equal(
                "the failure is labelled model_timeout", error_code, "model_timeout"
            )
            checks.record(
                "the failure is bounded in time", elapsed < 40, f"{elapsed:.1f}s"
            )

            status, _, _ = client.request("GET", "/health/ready", auth=False)
            checks.equal("the API stays ready while the model hangs", status, 200)
            client.close()
    finally:
        for connection in held:
            connection.close()
        listener.close()


def bootstrap(url: str) -> None:
    """Create the two accounts the run needs, on a freshly migrated database."""
    import os

    # The service layer reads settings once per process; point it at this
    # database before the first import.
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("JWT_SECRET", "acceptance-only-secret-0123456789abcdef")

    from sentinelflow.core.permissions import UserRole
    from sentinelflow.db.session import get_session_factory
    from sentinelflow.services.auth import create_user

    with get_session_factory()() as session:
        create_user(session, username=ADMIN[0], password=ADMIN[1], role=UserRole.ADMIN)
        create_user(
            session, username=ANALYST[0], password=ANALYST[1], role=UserRole.ANALYST
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SentinelFlow V1 acceptance run")
    parser.add_argument(
        "--database",
        default="sentinelflow_v1",
        help="name of an already-migrated database on PERF_DATABASE_BASE",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop and recreate the database, migrate it, and create the two users",
    )
    parser.add_argument("--skip-timeout", action="store_true")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    if args.reset:
        url = reset_database(args.database)
        bootstrap(url)
        print(f"database {args.database} recreated and migrated\n")
    url = database_url(args.database)
    stub = StubModel()
    checks = Checks()
    facts: dict = {}

    try:
        with running_server(
            url,
            extra_env={
                "LLM_PROVIDER": "stub",
                "LLM_MODEL": "stub",
                "LLM_API_BASE": stub.base,
                "LLM_API_KEY": "sk-not-used",
                "LLM_TIMEOUT_SECONDS": "10",
                "AGENT_MAX_ROUNDS": "3",
            },
        ) as server:
            print("business flow")
            facts = run(server.base, checks)
            print("\nnegative checks")
            run_security_checks(checks, server.base)
    finally:
        stub.stop()

    if not args.skip_timeout:
        print("\nfailure handling")
        run_timeout_check(checks, args.database)

    failed = checks.failed
    print()
    print(f"{len(checks.rows) - len(failed)}/{len(checks.rows)} checks passed")
    if failed:
        print()
        for name, _, detail in failed:
            print(f"  FAILED  {name}  {detail}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "checks": [
                        {"name": name, "status": status, "detail": detail}
                        for name, status, detail in checks.rows
                    ],
                    "facts": facts,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
