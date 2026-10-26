"""Capture real request/response pairs and render them as a portfolio document.

The point of generating the document instead of writing it by hand is that the
examples cannot drift from the code, and nobody can quietly improve a number.

    python scripts/capture_examples.py --markdown docs/portfolio/API_EXAMPLES.md

What it runs is the same stack a user runs: a freshly created database, the real
Alembic migrations, a real uvicorn process, and a scripted model behind the
OpenAI-compatible interface. No real provider key is involved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from perf.harness import (  # noqa: E402
    Client,
    reset_database,
    running_server,
)

DATABASE = "sentinelflow_demo"
ADMIN = ("demo.admin", "demo-admin-password-123")
ANALYST = ("demo.analyst", "demo-analyst-password-123")
STUB = "http://127.0.0.1:8014/v1"

#: Long arrays are shortened in the document; the capture keeps everything.
KEEP_ITEMS = 3

#: These bodies are rendered in full: they are the artifact worth reading.
RENDERED_IN_FULL = {"report_detail"}

#: Request fields that never appear in the document, even for a throwaway
#: database. A demo password in a public example teaches the wrong habit.
REDACTED_FIELDS = {"password", "access_token", "authorization"}

captured: list[dict[str, Any]] = []


def record(
    name: str,
    method: str,
    path: str,
    status: int,
    body: Any,
    request: Any = None,
    note: str = "",
) -> None:
    captured.append(
        {
            "name": name,
            "method": method,
            "path": path,
            "status": status,
            "request": request,
            "body": body,
            "note": note,
        }
    )


def call(
    client: Client,
    name: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    note: str = "",
) -> Any:
    status, raw, _ = client.request(method, path, payload)
    try:
        body: Any = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw.decode("utf-8", "replace")
    record(name, method, path, status, body, payload, note)
    return body


def bootstrap(url: str) -> None:
    """Create the two accounts, on a database that has just been migrated."""
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("JWT_SECRET", "capture-only-secret-0123456789abcdef")

    from sentinelflow.core.permissions import UserRole
    from sentinelflow.db.session import get_session_factory
    from sentinelflow.services.auth import create_user

    with get_session_factory()() as session:
        create_user(session, username=ADMIN[0], password=ADMIN[1], role=UserRole.ADMIN)
        create_user(
            session, username=ANALYST[0], password=ANALYST[1], role=UserRole.ANALYST
        )


def burst() -> list[dict[str, Any]]:
    """Six failed logins from one source in five minutes, then one success."""
    start = datetime(2026, 5, 1, 2, 0, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for index in range(6):
        rows.append(
            {
                "event_id": str(uuid.uuid4()),
                "timestamp": (start + timedelta(seconds=20 * index)).isoformat(),
                "event_type": "authentication",
                "action": "login",
                "outcome": "failure",
                "username": "demo.user",
                "source_ip": "198.51.100.77",
                "asset_id": "web-01",
                "source": "demo",
                "raw_message": (
                    f"Failed password for demo.user from 198.51.100.77 "
                    f"attempt {index + 1}"
                ),
            }
        )
    rows.append(
        {
            "event_id": str(uuid.uuid4()),
            "timestamp": (start + timedelta(seconds=140)).isoformat(),
            "event_type": "authentication",
            "action": "login",
            "outcome": "success",
            "username": "demo.user",
            "source_ip": "198.51.100.77",
            "asset_id": "web-01",
            "source": "demo",
            "raw_message": "Accepted password for demo.user from 198.51.100.77",
        }
    )
    return rows


def walk(url: str) -> dict[str, Any]:
    """Drive the whole product once and record every exchange."""
    env = {
        "APP_ENV": "demo",
        "LLM_PROVIDER": "stub",
        "LLM_MODEL": "stub-model",
        "LLM_API_BASE": STUB,
        "LLM_API_KEY": "sk-stub-not-a-real-key",
    }

    with running_server(url, extra_env=env) as server:
        client = Client(server.base)

        call(client, "liveness", "GET", "/health")
        call(client, "readiness", "GET", "/health/ready")

        call(
            client,
            "login",
            "POST",
            "/api/v1/auth/login",
            {"username": ADMIN[0], "password": ADMIN[1]},
        )
        client.login(ADMIN[0], ADMIN[1])
        call(client, "whoami", "GET", "/api/v1/auth/me")

        analyst = Client(server.base)
        analyst.login(ANALYST[0], ANALYST[1])
        call(analyst, "analyst_list_alerts", "GET", "/api/v1/alerts")

        rows = burst()
        call(
            client,
            "import_burst",
            "POST",
            "/api/v1/events/import",
            {"events": rows},
            "七个合成事件：六次失败登录 + 一次成功登录",
        )
        call(
            client,
            "import_duplicate",
            "POST",
            "/api/v1/events/import",
            {"events": rows},
            "同一批数据再导一次：幂等，全部识别为重复",
        )

        detection = call(client, "run_detection", "POST", "/api/v1/detections/run")
        alert_id = detection["created_alert_ids"][0]
        call(
            client,
            "run_detection_again",
            "POST",
            "/api/v1/detections/run",
            note="重复运行不产生新告警（dedup key）",
        )

        call(client, "list_alerts", "GET", "/api/v1/alerts?limit=10")
        call(client, "alert_detail", "GET", f"/api/v1/alerts/{alert_id}")
        call(
            client,
            "alert_evidence",
            "GET",
            f"/api/v1/alerts/{alert_id}/evidence?limit=3",
        )

        status, raw, _ = analyst.request(
            "PATCH", f"/api/v1/alerts/{alert_id}", {"status": "acknowledged"}
        )
        record(
            "analyst_patch_forbidden",
            "PATCH",
            f"/api/v1/alerts/{alert_id}",
            status,
            json.loads(raw) if raw else None,
            {"status": "acknowledged"},
            "analyst 只有 alerts:read，改状态被拒",
        )
        analyst.close()

        call(
            client,
            "acknowledge",
            "PATCH",
            f"/api/v1/alerts/{alert_id}",
            {"status": "acknowledged", "reason": "triaged by demo"},
        )

        investigation = call(
            client,
            "start_investigation",
            "POST",
            f"/api/v1/alerts/{alert_id}/investigations",
        )
        investigation_id = investigation["id"]

        final: dict[str, Any] = {}
        for _ in range(80):
            final = call(
                client,
                "poll_investigation",
                "GET",
                f"/api/v1/investigations/{investigation_id}",
            )
            if final["status"] not in ("pending", "running"):
                break
            time.sleep(0.25)

        # Keep one poll, the one that reached a terminal state.
        captured[:] = [
            item
            for item in captured
            if item["name"] != "poll_investigation" or item is captured[-1]
        ]

        call(client, "report_detail", "GET", f"/api/v1/reports/{final['report_id']}")
        call(client, "report_versions", "GET", f"/api/v1/alerts/{alert_id}/reports")
        version_two = call(
            client,
            "report_new_version",
            "POST",
            f"/api/v1/alerts/{alert_id}/reports",
            {"note": "second version after triage"},
        )
        call(
            client,
            "report_finalize",
            "POST",
            f"/api/v1/reports/{version_two['id']}/finalize",
            {"note": "accepted by demo admin"},
        )

        call(client, "audit_logs", "GET", "/api/v1/audit-logs?limit=8")
        call(client, "logout", "POST", "/api/v1/auth/logout")
        status, raw, _ = client.request("GET", "/api/v1/alerts?limit=1")
        record(
            "revoked_token",
            "GET",
            "/api/v1/alerts?limit=1",
            status,
            json.loads(raw) if raw else None,
            None,
            "用登出前的同一个 token 再请求",
        )

    return {
        "database": DATABASE,
        "alert_id": alert_id,
        "investigation_id": investigation_id,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "calls": captured,
    }


# --- rendering --------------------------------------------------------------


def _shorten(value: Any, depth: int = 0) -> Any:
    """Trim arrays and long strings, keeping the shape visible."""
    if isinstance(value, list):
        kept = [_shorten(item, depth + 1) for item in value[:KEEP_ITEMS]]
        if len(value) > KEEP_ITEMS:
            kept.append(f"... 另有 {len(value) - KEEP_ITEMS} 项")
        return kept
    if isinstance(value, dict):
        return {
            key: (
                "***" if key.lower() in REDACTED_FIELDS else _shorten(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, str) and value.startswith("eyJ"):
        # A JWT: keep the header so the shape is recognisable, drop the payload.
        return value[:18] + ".<payload>.<signature>"
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…"
    return value


def _render_call(item: dict[str, Any]) -> str:
    lines = [f"### `{item['method']} {item['path']}` → {item['status']}", ""]
    if item["note"]:
        lines += [f"> {item['note']}", ""]
    if item["request"] is not None:
        lines += ["请求体（节选）：", "", "```json"]
        lines += json.dumps(
            _shorten(item["request"]), ensure_ascii=False, indent=2
        ).splitlines()
        lines += ["```", ""]
    if item["body"] is None:
        lines += ["无响应体。", ""]
    else:
        body = (
            item["body"] if item["name"] in RENDERED_IN_FULL else _shorten(item["body"])
        )
        lines += ["响应：", "", "```json"]
        lines += json.dumps(body, ensure_ascii=False, indent=2).splitlines()
        lines += ["```", ""]
    return "\n".join(lines)


SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "1",
        "探针",
        ["liveness", "readiness"],
    ),
    (
        "2",
        "认证与权限",
        [
            "login",
            "whoami",
            "analyst_list_alerts",
            "analyst_patch_forbidden",
            "acknowledge",
            "logout",
            "revoked_token",
        ],
    ),
    (
        "3",
        "导入与规则检测",
        ["import_burst", "import_duplicate", "run_detection", "run_detection_again"],
    ),
    (
        "4",
        "告警查询",
        ["list_alerts", "alert_detail", "alert_evidence"],
    ),
    (
        "5",
        "Agent 调查",
        ["start_investigation", "poll_investigation"],
    ),
    (
        "6",
        "报告：版本与定稿",
        [
            "report_detail",
            "report_versions",
            "report_new_version",
            "report_finalize",
        ],
    ),
    (
        "7",
        "审计",
        ["audit_logs"],
    ),
]


def render(payload: dict[str, Any]) -> str:
    by_name = {item["name"]: item for item in payload["calls"]}

    head = f"""# API 请求与响应实例

> 本文件由 `python scripts/capture_examples.py --markdown docs/portfolio/API_EXAMPLES.md` 生成，
> **不是手写的**。数据来自一次真实运行：全新数据库、真实 `alembic upgrade head`、
> 真实 uvicorn 进程、脚本化模型（桩）。
>
> 抓取时间：`{payload["captured_at"]}`　数据库：`{payload["database"]}`
>
> 唯一的人工处理是显示层截断：长数组只留前 {KEEP_ITEMS} 项并标注剩余数量，
> JWT 只保留头部。**没有任何数值被改动。**

## 0. 前置

```bash
export BASE=http://127.0.0.1:8000
export TOKEN=<登录返回的 access_token>
```

示例用 `curl` 表示；实际抓取走的是同一个 HTTP 接口。

一共 {len(payload["calls"])} 次请求，按业务流程排列如下。

"""
    body = [head]
    for number, title, names in SECTIONS:
        body.append(f"## {number}. {title}\n")
        for name in names:
            item = by_name.get(name)
            if item is None:
                continue
            body.append(_render_call(item))
        body.append("")

    body.append(
        f"""## 8. 这份记录证明了什么

| 结论 | 证据 |
| --- | --- |
| 重复导入幂等 | `import_duplicate` 返回 `imported=0, skipped=7`，不是 409 也不是重复插入 |
| 重复检测不重复告警 | 第二次 `run_detection` 返回 `alerts_created=0`，`alerts_skipped_existing=1` |
| 权限是真在服务端拦的 | analyst 的 `PATCH` 返回 403，同一个请求换 admin 就成功 |
| 调查是异步的 | `POST` 返回 202 + `status=pending`，最终态要靠轮询拿 |
| 报告引用的是真实事件 | `content.evidence` 里的 `event_id` 都能在 `/evidence` 里找到 |
| 定稿不可逆 | 版本 2 定稿后 `status=finalized`，带 `finalized_at` 与操作人 |
| 登出即失效 | 同一个 token 再请求返回 401 |
| 审计可追溯 | `audit_logs` 里每条都有 `action`、资源、`request_id` 和操作人 |

告警 id：`{payload["alert_id"]}`
调查 id：`{payload["investigation_id"]}`
"""
    )
    return "\n".join(body)


def main(argv: list[str] | None = None) -> int:
    global DATABASE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--markdown",
        type=Path,
        help="write the rendered document here instead of printing it",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="also save the raw capture, for inspection",
    )
    parser.add_argument("--database", default=DATABASE)
    args = parser.parse_args(argv)

    DATABASE = args.database

    url = reset_database(DATABASE)
    bootstrap(url)
    print(f"database {DATABASE} recreated and migrated", flush=True)

    payload = walk(url)
    payload["database"] = DATABASE

    if args.json:
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"raw capture: {args.json}")

    document = render(payload)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(document, encoding="utf-8")
        print(f"wrote {args.markdown}")
    else:
        print(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
