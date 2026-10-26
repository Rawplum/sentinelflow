"""Concurrency checks that look for inconsistencies, not for speed.

Three questions the single-threaded runs cannot answer:

1. When several requests change the same alert's status at once, does the
   history stay a coherent chain, or do rows disagree about where the alert was?
2. When several requests start an investigation for the same alert, does the
   duplicate guard hold, and does every task reach a terminal state?
3. When the model hangs, does the request return promptly and the task end in a
   bounded time, or does the worker hold the lease until it expires?

    python -m perf.concurrency
"""

from __future__ import annotations

import contextlib
import itertools
import json
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from perf.dataset import DatasetSpec, generate_events, insert_events
from perf.harness import (
    Client,
    reset_database,
    running_server,
    session_factory_for,
)

ADMIN_PASSWORD = "perf-password-123"

#: A citation that can never match a real event, so the task ends quickly in a
#: terminal state. This scenario is about the queue and the duplicate guard, not
#: about the model succeeding.
FAKE_FINDINGS = {
    "summary": "concurrency probe",
    "risk_level": "low",
    "reasoning": "probe",
    "recommended_actions": ["none"],
    "limitations": ["probe"],
    "cited_event_ids": ["00000000-0000-4000-8000-000000000000"],
}


@dataclass
class Outcome:
    name: str
    detail: str
    ok: bool
    evidence: dict = field(default_factory=dict)


class _StubModel:
    """Answers slowly, with findings whose citation cannot be valid.

    The delay matters: with an instant answer the first investigation is already
    finished before the second request arrives, and a second one is then
    legitimately allowed. The guard is about *simultaneous* work.
    """

    def __init__(self, delay_seconds: float = 1.5) -> None:
        payload = json.dumps(
            {"choices": [{"message": {"content": json.dumps(FAKE_FINDINGS)}}]}
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                time.sleep(delay_seconds)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _bootstrap(url: str, *, alerts: int = 3) -> None:
    from sentinelflow.core.permissions import UserRole
    from sentinelflow.services.auth import create_user

    engine, factory = session_factory_for(url)
    try:
        with factory() as session:
            create_user(
                session,
                username="perf.admin",
                password=ADMIN_PASSWORD,
                role=UserRole.ADMIN,
            )
            insert_events(session, generate_events(DatasetSpec(alerts=alerts)))
    finally:
        engine.dispose()


def _login(base: str) -> Client:
    client = Client(base)
    client.login("perf.admin", ADMIN_PASSWORD)
    return client


def _ensure_alerts(client: Client, wanted: int) -> list[str]:
    status, data, _ = client.request("POST", "/api/v1/detections/run")
    assert status == 200, data[:200]
    ids = json.loads(data)["created_alert_ids"]
    if len(ids) < wanted:
        _, listing, _ = client.request("GET", "/api/v1/alerts?limit=20")
        ids = [item["id"] for item in json.loads(listing)["items"]]
    return ids


# --- 1. concurrent status updates -------------------------------------------


def concurrent_status_updates(
    url: str, *, workers: int = 8, rounds: int = 6
) -> Outcome:
    targets = ["acknowledged", "investigating", "closed"]
    codes: Counter[int] = Counter()
    lock = threading.Lock()

    with running_server(url) as server:
        client = _login(server.base)
        alert_id = _ensure_alerts(client, 1)[0]
        client.close()

        barrier = threading.Barrier(workers)

        def worker(index: int) -> None:
            local = _login(server.base)
            try:
                barrier.wait()
                for step in range(rounds):
                    target = targets[(index + step) % len(targets)]
                    status, _, _ = local.request(
                        "PATCH", f"/api/v1/alerts/{alert_id}", {"status": target}
                    )
                    with lock:
                        codes[status] += 1
            finally:
                local.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        checker = _login(server.base)
        _, body, _ = checker.request("GET", f"/api/v1/alerts/{alert_id}")
        alert = json.loads(body)
        checker.close()

    history = alert.get("status_history") or []
    chain_problem = ""
    if history:
        if history[0]["from_status"] != "open":
            chain_problem = f"first row starts at {history[0]['from_status']}, not open"
        else:
            for previous, current in itertools.pairwise(history):
                if previous["to_status"] != current["from_status"]:
                    chain_problem = (
                        f"row ending at '{previous['to_status']}' is followed by a row "
                        f"starting at '{current['from_status']}'"
                    )
                    break
            if not chain_problem and history[-1]["to_status"] != alert["status"]:
                chain_problem = (
                    f"history ends at '{history[-1]['to_status']}' but the alert is "
                    f"'{alert['status']}'"
                )

    accepted = codes.get(200, 0)
    rejected = codes.get(409, 0)
    server_errors = sum(count for code, count in codes.items() if code >= 500)

    ok = not chain_problem and server_errors == 0
    detail = (
        f"{workers} workers x {rounds} rounds: {accepted} accepted, {rejected} rejected, "
        f"{server_errors} server errors; final '{alert['status']}', "
        f"{len(history)} history rows"
    )
    if chain_problem:
        detail += f"; CHAIN BROKEN: {chain_problem}"

    return Outcome(
        name="concurrent status updates",
        ok=ok,
        detail=detail,
        evidence={
            "status_codes": dict(codes),
            "final_status": alert["status"],
            "history_rows": len(history),
            "accepted": accepted,
            "chain_ok": not chain_problem,
        },
    )


# --- 2. concurrent investigations for one alert ------------------------------


def concurrent_investigations(
    url: str, *, workers: int = 6, alerts: int = 3
) -> Outcome:
    stub = _StubModel(delay_seconds=1.5)
    env = {
        "LLM_PROVIDER": "stub",
        "LLM_MODEL": "stub",
        "LLM_API_BASE": stub.base,
        "LLM_API_KEY": "sk-not-used",
        "LLM_TIMEOUT_SECONDS": "10",
    }
    try:
        with running_server(url, extra_env=env) as server:
            client = _login(server.base)
            alert_ids = _ensure_alerts(client, alerts)[:alerts]
            client.close()

            codes: Counter[int] = Counter()
            created: list[str] = []
            per_alert: dict[str, int] = {}
            lock = threading.Lock()

            def worker(alert_id: str) -> None:
                local = _login(server.base)
                try:
                    status, body, _ = local.request(
                        "POST", f"/api/v1/alerts/{alert_id}/investigations"
                    )
                    with lock:
                        codes[status] += 1
                        if status == 202:
                            created.append(json.loads(body)["id"])
                            per_alert[alert_id] = per_alert.get(alert_id, 0) + 1
                finally:
                    local.close()

            threads = [
                threading.Thread(target=worker, args=(alert_id,))
                for alert_id in alert_ids
                for _ in range(workers)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            checker = _login(server.base)
            deadline = time.monotonic() + 120
            terminal: dict[str, str] = {}
            while time.monotonic() < deadline:
                busy = 0
                for investigation_id in created:
                    _, body, _ = checker.request(
                        "GET", f"/api/v1/investigations/{investigation_id}"
                    )
                    state = json.loads(body)["status"]
                    terminal[investigation_id] = state
                    if state in ("pending", "running"):
                        busy += 1
                if busy == 0:
                    break
                time.sleep(0.3)
            checker.close()
    finally:
        stub.stop()

    accepted = codes.get(202, 0)
    rejected = codes.get(409, 0)
    errors = sum(count for code, count in codes.items() if code >= 500)
    stuck = [key for key, value in terminal.items() if value in ("pending", "running")]
    states = Counter(terminal.values())

    overlaps = _overlapping_intervals(url, alert_ids)
    duplicates = len(created) - len(set(created))

    ok = (
        accepted == len(alert_ids)
        and errors == 0
        and not stuck
        and not overlaps
        and duplicates == 0
    )
    detail = (
        f"{len(alert_ids)} alerts x {workers} simultaneous POSTs: {accepted} accepted "
        f"(expected {len(alert_ids)}), {rejected} rejected while one was in flight, "
        f"{errors} server errors; final states {dict(states)}; "
        f"{len(overlaps)} overlapping interval(s)"
    )
    if stuck:
        detail += f"; {len(stuck)} task(s) never finished"
    if overlaps:
        detail += f"; two investigations ran at once for {overlaps[0]}"

    return Outcome(
        name="concurrent investigations",
        ok=ok,
        detail=detail,
        evidence={
            "status_codes": dict(codes),
            "states": dict(states),
            "stuck": len(stuck),
            "overlaps": overlaps,
            "per_alert_accepted": per_alert,
        },
    )


def _overlapping_intervals(url: str, alert_ids: list[str]) -> list[str]:
    """Alert ids whose investigations have overlapping run windows."""
    from sqlalchemy import text

    engine, _ = session_factory_for(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT alert_id, started_at, completed_at FROM investigations "
                    "WHERE alert_id = ANY(:ids) AND started_at IS NOT NULL "
                    "ORDER BY alert_id, started_at"
                ),
                {"ids": alert_ids},
            ).fetchall()
    finally:
        engine.dispose()

    bad: list[str] = []
    previous_alert = None
    previous_end = None
    for alert_id, started, completed in rows:
        if (
            alert_id == previous_alert
            and previous_end is not None
            and started < previous_end
        ):
            bad.append(str(alert_id))
        previous_alert = alert_id
        previous_end = completed
    return bad


# --- 3. model timeout --------------------------------------------------------


def model_timeout(url: str, *, timeout_seconds: int = 2) -> Outcome:
    """A provider that accepts the connection and never answers."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    held: list[socket.socket] = []

    def accept_and_stall() -> None:
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            held.append(connection)  # keep it open, never reply

    threading.Thread(target=accept_and_stall, daemon=True).start()

    env = {
        "LLM_PROVIDER": "stub",
        "LLM_MODEL": "stub",
        "LLM_API_BASE": f"http://127.0.0.1:{port}/v1",
        "LLM_API_KEY": "sk-not-used",
        "LLM_TIMEOUT_SECONDS": str(timeout_seconds),
    }
    try:
        with running_server(url, extra_env=env) as server:
            client = _login(server.base)
            alert_id = _ensure_alerts(client, 1)[0]

            started = time.perf_counter()
            status, body, _ = client.request(
                "POST", f"/api/v1/alerts/{alert_id}/investigations"
            )
            post_seconds = time.perf_counter() - started
            investigation_id = json.loads(body)["id"] if status == 202 else None

            # While the worker waits on the provider, the API must still answer.
            health_started = time.perf_counter()
            health_status, _, _ = client.request("GET", "/health/ready", auth=False)
            health_seconds = time.perf_counter() - health_started

            state = None
            error_code = None
            finished_in = None
            if investigation_id:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    _, state_body, _ = client.request(
                        "GET", f"/api/v1/investigations/{investigation_id}"
                    )
                    payload = json.loads(state_body)
                    state = payload["status"]
                    error_code = payload.get("error_code")
                    if state not in ("pending", "running"):
                        finished_in = time.perf_counter() - started
                        break
                    time.sleep(0.2)
            client.close()
    finally:
        for connection in held:
            with contextlib.suppress(OSError):
                connection.close()
        listener.close()

    ok = (
        status == 202
        and post_seconds < 2.0
        and health_status == 200
        and state == "failed"
        and error_code == "model_timeout"
        and finished_in is not None
        and finished_in < 60
    )
    detail = (
        f"POST returned {status} in {post_seconds * 1000:.0f} ms; readiness answered "
        f"{health_status} in {health_seconds * 1000:.0f} ms while the worker was blocked; "
        f"task ended '{state}' ({error_code})"
        + (f" after {finished_in:.1f}s" if finished_in else " but never finished")
        + f"; provider timeout {timeout_seconds}s"
    )
    return Outcome(
        name="model timeout",
        ok=ok,
        detail=detail,
        evidence={
            "post_ms": round(post_seconds * 1000),
            "health_ms": round(health_seconds * 1000),
            "state": state,
            "error_code": error_code,
            "finished_in_seconds": round(finished_in, 2) if finished_in else None,
        },
    )


def main() -> int:
    url = reset_database("sentinelflow_perf_conc")
    _bootstrap(url, alerts=3)

    outcomes = [
        concurrent_status_updates(url),
        concurrent_investigations(url),
        model_timeout(url),
    ]

    width = max(len(outcome.name) for outcome in outcomes)
    print("concurrency")
    for outcome in outcomes:
        mark = "OK  " if outcome.ok else "FAIL"
        print(f"  {mark}  {outcome.name.ljust(width)}  {outcome.detail}")

    print()
    print(
        json.dumps({o.name: o.evidence for o in outcomes}, indent=2, ensure_ascii=False)
    )
    return 0 if all(outcome.ok for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
