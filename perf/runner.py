"""Measure the API against synthetic data at a chosen scale.

    python -m perf.runner --alerts 100            # ~1.6k events
    python -m perf.runner --alerts 1000           # ~16k events
    python -m perf.runner --alerts 6000           # ~96k events

Each run drops and recreates its own database, seeds deterministic data, starts
a real uvicorn process and replays the queries the console actually issues. The
numbers are whatever they are: nothing here is tuned to look good.

Reported per scenario: sample count, P50, P95, worst case, error rate and the
largest response body. Throughput is not reported because these are sequential
requests from one client; a throughput number from that setup would describe the
client, not the server.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from perf.dataset import (
    BASE_TIME,
    DatasetSpec,
    generate_events,
    insert_events,
    seed_alert,
)
from perf.harness import (
    Client,
    Sample,
    reset_database,
    running_server,
    session_factory_for,
    timed,
)

ADMIN_PASSWORD = "perf-password-123"
DEFAULT_ITERATIONS = 30
REPORT_EVIDENCE = 150  # above the 100-row report cap on purpose


def _seed(url: str, spec: DatasetSpec) -> tuple[dict, str]:
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
            rows = generate_events(spec)
            started = time.perf_counter()
            insert_events(session, rows)
            insert_seconds = time.perf_counter() - started

            big_alert = seed_alert(session, index=0, events=REPORT_EVIDENCE)

        with factory() as session:
            from sqlalchemy import func, select

            from sentinelflow.models.security_event import SecurityEvent

            total = session.scalar(select(func.count()).select_from(SecurityEvent))
            usernames = session.execute(
                select(SecurityEvent.username)
                .where(SecurityEvent.outcome == "failure")
                .limit(1)
            ).scalar_one_or_none()
    finally:
        engine.dispose()

    return (
        {
            "events": total,
            "insert_seconds": round(insert_seconds, 2),
            "sample_username": usernames,
            "big_alert_id": str(big_alert),
        },
        url,
    )


def _read_scenarios_cold(client: Client, meta: dict) -> list[Sample]:
    """The two scenarios whose plan depends most on statistics."""
    deep = max(0, min(20000, meta["events"] - 50))
    samples = []
    for name, path in (
        ("events:deep_page_cold", f"/api/v1/events?limit=50&offset={deep}"),
        ("events:count_cold", "/api/v1/events?limit=50&outcome=failure"),
    ):
        sample = Sample(name=name)
        for _ in range(5):
            timed(sample, client, "GET", path)
        samples.append(sample)
    return samples


def _analyze(url: str) -> None:
    """Refresh planner statistics after a bulk load.

    Without this the planner works from the pre-import row estimates and can
    pick a sequential scan with a full sort. Measured separately below, because
    "first query after an import" is a real state worth knowing about.
    """
    engine, _ = session_factory_for(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("ANALYZE security_events"))
            connection.execute(text("ANALYZE alerts"))
            connection.commit()
    finally:
        engine.dispose()


def _read_scenarios(client: Client, meta: dict, iterations: int) -> list[Sample]:
    samples: dict[str, Sample] = {}

    def run(name: str, path: str, repeat: int = iterations) -> bytes:
        sample = samples.setdefault(name, Sample(name=name))
        # One untimed request per scenario: the first call to a new path pays for
        # connection setup and lazy imports, and would otherwise land in P95.
        timed(Sample(name="warmup"), client, "GET", path)
        body = b""
        for _ in range(repeat):
            body = timed(sample, client, "GET", path)
        return body

    # Warm up: the first request pays for connection setup and any lazy import.
    timed(Sample(name="warmup"), client, "GET", "/api/v1/alerts?limit=1")

    # Deep pagination: OFFSET still walks the skipped rows, so this is where a
    # large table starts to hurt. Clamped so small datasets still exercise it.
    deep = max(0, min(20000, meta["events"] - 50))
    run("events:page1", "/api/v1/events?limit=50")
    run("events:deep_page", f"/api/v1/events?limit=50&offset={deep}")
    run("events:filter_outcome", "/api/v1/events?limit=50&outcome=failure")
    run(
        "events:filter_user",
        f"/api/v1/events?limit=50&username={meta['sample_username']}",
    )
    run("events:keyword", "/api/v1/events?limit=50&q=synthetic")
    # 'Z' rather than '+00:00': a literal '+' in a query string decodes as a
    # space, and the server would reject the timestamp.
    start = (BASE_TIME + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (BASE_TIME + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    run("events:time_window", f"/api/v1/events?limit=50&start={start}&end={end}")
    run("events:no_raw_message", "/api/v1/events?limit=50&include_raw_message=false")

    run("alerts:list", "/api/v1/alerts?limit=50")
    run("alerts:filter", "/api/v1/alerts?limit=50&severity=high")

    listing = json.loads(
        run("alerts:detail_source", "/api/v1/alerts?limit=1", repeat=1)
    )
    alert_id = listing["items"][0]["id"]
    run("alerts:detail", f"/api/v1/alerts/{alert_id}")
    run("alerts:evidence", f"/api/v1/alerts/{alert_id}/evidence?limit=50")

    run("reports:small", f"/api/v1/alerts/{alert_id}/report")
    run("reports:150_evidence", f"/api/v1/alerts/{meta['big_alert_id']}/report")

    return list(samples.values())


def _api_rows(alerts: int, seed: int) -> list[dict]:
    """Generate rows in the shape POST /events/import accepts."""
    rows = []
    for row in generate_events(DatasetSpec(alerts=alerts, seed=seed)):
        rows.append(
            {
                "event_id": str(row["event_id"]),
                "timestamp": row["timestamp"].isoformat(),
                "event_type": row["event_type"],
                "username": row["username"],
                "source_ip": row["source_ip"],
                "asset_id": row["asset_id"],
                "action": row["action"],
                "outcome": row["outcome"],
                "raw_message": row["raw_message"],
                "source": row["source"],
            }
        )
    return rows


def _write_scenarios(client: Client, spec: DatasetSpec, meta: dict) -> list[Sample]:
    samples: list[Sample] = []

    # The import endpoint accepts at most 500 rows; measure the worst allowed
    # batch rather than a comfortable one.
    fresh = _api_rows(31, spec.seed + 1)[:500]
    sample = Sample(name="import:new_500")
    for _ in range(3):
        timed(sample, client, "POST", "/api/v1/events/import", {"events": fresh})
    samples.append(sample)

    # Same rows again: every event must be recognised as a duplicate, which is
    # the expensive path (each row is looked up before insert).
    sample = Sample(name="import:duplicate_500")
    for _ in range(3):
        timed(sample, client, "POST", "/api/v1/events/import", {"events": fresh})
    samples.append(sample)

    # Detection over the whole table, run twice: the second run must create
    # nothing but still pays for the scan.
    for label in ("detections:first", "detections:repeat"):
        sample = Sample(name=label)
        timed(sample, client, "POST", "/api/v1/detections/run")
        samples.append(sample)

    return samples


def run(alerts: int, iterations: int, database: str) -> dict:
    spec = DatasetSpec(alerts=alerts)
    url = reset_database(database)
    meta, _ = _seed(url, spec)
    # Deliberately NOT analysed yet: the cold scenario needs stale statistics.
    meta["planned_events"] = spec.approx_events
    meta["seed"] = spec.seed

    results: list[Sample] = []
    with running_server(url) as server:
        client = Client(server.base)
        try:
            client.login("perf.admin", ADMIN_PASSWORD)
            cold = _read_scenarios_cold(client, meta)
            _analyze(url)
            results.extend(cold)
            results.extend(_read_scenarios(client, meta, iterations))
            results.extend(_write_scenarios(client, spec, meta))
        finally:
            client.close()

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "database": "PostgreSQL 16 (local cluster)",
            "server": "uvicorn, single process, single worker",
            "client": "sequential keep-alive HTTP from one process",
        },
        "dataset": meta,
        "iterations": iterations,
        "scenarios": [
            {
                "name": sample.name,
                "n": sample.count,
                "p50_ms": round(sample.p50, 2),
                "p95_ms": round(sample.p95, 2),
                "max_ms": round(max(sample.latencies_ms), 2),
                "mean_ms": round(sample.mean, 2),
                "error_rate": round(sample.error_rate, 4),
                "max_response_bytes": sample.payload_bytes,
            }
            for sample in results
            if sample.count
        ],
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SentinelFlow performance run")
    parser.add_argument(
        "--alerts", type=int, default=100, help="number of alert bursts"
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--database", default="sentinelflow_perf")
    parser.add_argument(
        "--json", dest="json_path", default=str(Path(__file__).parent / "last_run.json")
    )
    args = parser.parse_args(argv)

    payload = run(args.alerts, args.iterations, args.database)

    print(
        f"dataset: {payload['dataset']['events']} events "
        f"({payload['dataset']['planned_events']} planned), "
        f"seed {payload['dataset']['seed']}, "
        f"insert {payload['dataset']['insert_seconds']}s"
    )
    print(
        f"python {payload['environment']['python']} on {payload['environment']['platform']}"
    )
    print()
    print(_format_from_payload(payload))

    Path(args.json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"report written to {args.json_path}")
    return 0


def _format_from_payload(payload: dict) -> str:
    header = (
        f"{'scenario':26} {'n':>4} {'p50 ms':>9} {'p95 ms':>9} "
        f"{'max ms':>9} {'err%':>6} {'resp KB':>8}"
    )
    lines = [header, "-" * len(header)]
    for row in payload["scenarios"]:
        lines.append(
            f"{row['name']:26} {row['n']:>4} {row['p50_ms']:>9.1f} {row['p95_ms']:>9.1f} "
            f"{row['max_ms']:>9.1f} {row['error_rate'] * 100:>5.0f}% "
            f"{row['max_response_bytes'] / 1024:>8.1f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
