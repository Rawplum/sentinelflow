"""Narrated end-to-end demo against a running SentinelFlow API.

Two phases:

1. Offline, no model key: import synthetic logs, run detection, open the alert,
   read the deterministic report. This is the part that must always work.
2. Optional (``--with-agent``): queue an Agent investigation, poll it, print the
   report it produced. Needs ``LLM_*`` configured on the server.

The synthetic events use fixed UUIDs derived from their index, so a second run
imports nothing and detection creates no second alert. That is the point: the
demo shows idempotency instead of quietly duplicating data.

    python scripts/demo.py --username demo.admin
    python scripts/demo.py --username demo.admin --with-agent

Password comes from ``DEMO_PASSWORD``, not from argv: a password on the command
line lands in the shell history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

#: Fixed namespace so the same run produces the same event ids.
NAMESPACE = uuid.UUID("6f1a4c2e-0d3b-4f7a-9c55-2b8e1d4a7c90")
BASE_TIME = datetime(2026, 5, 1, 2, 0, 0, tzinfo=UTC)
USERNAME = "demo.user"
SOURCE_IP = "198.51.100.77"


def event_id(index: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"demo-event-{index}")


def synthetic_events() -> list[dict[str, Any]]:
    """Six failures twenty seconds apart, then one success."""
    rows: list[dict[str, Any]] = []
    for index in range(6):
        rows.append(
            {
                "event_id": str(event_id(index)),
                "timestamp": (BASE_TIME + timedelta(seconds=20 * index)).isoformat(),
                "event_type": "authentication",
                "action": "login",
                "outcome": "failure",
                "username": USERNAME,
                "source_ip": SOURCE_IP,
                "asset_id": "web-01",
                "source": "demo",
                "raw_message": (
                    f"Failed password for {USERNAME} from {SOURCE_IP} "
                    f"attempt {index + 1}"
                ),
            }
        )
    rows.append(
        {
            "event_id": str(event_id(6)),
            "timestamp": (BASE_TIME + timedelta(seconds=140)).isoformat(),
            "event_type": "authentication",
            "action": "login",
            "outcome": "success",
            "username": USERNAME,
            "source_ip": SOURCE_IP,
            "asset_id": "web-01",
            "source": "demo",
            "raw_message": f"Accepted password for {USERNAME} from {SOURCE_IP}",
        }
    )
    return rows


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return exc.code, raw.decode("utf-8", "replace")


def step(number: int, total: int, title: str) -> None:
    print(f"\n[{number}/{total}] {title}")


def detail(text: str) -> None:
    print(f"      {text}")


def fail(message: str) -> int:
    print(f"\n失败：{message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="demo.admin")
    parser.add_argument("--with-agent", action="store_true")
    parser.add_argument(
        "--agent-timeout", type=float, default=120.0, help="seconds to wait"
    )
    args = parser.parse_args(argv)

    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        return fail(
            "DEMO_PASSWORD 未设置。先导出它：export DEMO_PASSWORD='...'（不要写在命令行里）"
        )

    api = Api(args.base)
    total = 6 if args.with_agent else 5

    print("SentinelFlow 演示")
    print(f"  服务  {api.base}")
    print(f"  账号  {args.username}")

    # --- 0. reachability ---------------------------------------------------
    status, ready = api.call("GET", "/health/ready")
    if status != 200:
        return fail(f"/health/ready 返回 {status}，数据库可能没起：{ready}")
    detail(f"就绪：database={ready['database']}")

    status, login = api.call(
        "POST", "/api/v1/auth/login", {"username": args.username, "password": password}
    )
    if status != 200:
        return fail(
            f"登录失败（{status}）。账号不存在就先建一个：\n"
            "  sentinelflow-create-user --username demo.admin --role admin"
        )
    api.token = login["access_token"]
    detail(f"登录成功：role={login['role']}")

    # --- 1. import ---------------------------------------------------------
    rows = synthetic_events()
    step(1, total, "导入合成日志")
    detail(f"{len(rows)} 条：同一账号从同一来源，5 分钟内 6 次失败，随后 1 次成功")
    status, imported = api.call("POST", "/api/v1/events/import", {"events": rows})
    if status not in (200, 201):
        return fail(f"导入返回 {status}：{imported}")
    detail(
        f"HTTP {status}  imported={imported['imported']}  skipped={imported['skipped']}"
    )

    # --- 2. re-import ------------------------------------------------------
    step(2, total, "再导一次（幂等性）")
    status, again = api.call("POST", "/api/v1/events/import", {"events": rows})
    detail(f"HTTP {status}  imported={again['imported']}  skipped={again['skipped']}")
    detail("不是报错，是识别为重复：事件主键已经存在，整批被跳过")

    # --- 3. detection ------------------------------------------------------
    step(3, total, "运行规则检测")
    detail("规则 AUTH-001：同一账号 + 同一来源，任意 5 分钟窗口内 ≥5 次失败")
    status, detection = api.call("POST", "/api/v1/detections/run")
    if status != 200:
        return fail(f"检测返回 {status}：{detection}")
    detail(
        f"扫描 {detection['events_scanned']} 条事件 → "
        f"{detection['windows_detected']} 个窗口 → "
        f"新建 {detection['alerts_created']} 个告警，跳过 {detection['alerts_skipped_existing']} 个已存在"
    )

    status, second = api.call("POST", "/api/v1/detections/run")
    detail(
        f"再跑一次：新建 {second['alerts_created']}，跳过 "
        f"{second['alerts_skipped_existing']}（dedup_key 唯一约束兜底）"
    )

    # --- 4. alert ----------------------------------------------------------
    step(4, total, "查看告警与证据")
    status, page = api.call("GET", f"/api/v1/alerts?username={USERNAME}&limit=1")
    if not page["items"]:
        return fail("没有找到告警，检测可能没有命中")
    alert = page["items"][0]
    alert_id = alert["id"]
    detail(
        f"告警 {alert_id[:8]}…  severity={alert['severity']}  status={alert['status']}"
    )
    detail(f"标题：{alert['title']}")
    detail(f"证据：{alert['evidence_count']} 条（点击任一条都能回到原始日志）")

    status, evidence = api.call("GET", f"/api/v1/alerts/{alert_id}/evidence?limit=3")
    for item in evidence["items"]:
        detail(
            f"  {item['timestamp']}  {item['action']}/{item['outcome']}  "
            f"{item['username']}@{item['source_ip']}"
        )

    # --- 5. deterministic report ------------------------------------------
    step(5, total, "生成确定性报告（不需要模型）")
    status, report = api.call("GET", f"/api/v1/alerts/{alert_id}/report")
    if status != 200:
        return fail(f"报告返回 {status}：{report}")
    detail(f"结论：{report['summary'][:80]}")
    detail(f"风险：{report['risk_level']}　引用事件：{len(report['evidence'])} 条")
    detail("这份报告是模板化的：它永远给结论，永远按 severity 分级——")
    detail(
        "这也正是它的局限，下面用 Agent 对照。"
        if args.with_agent
        else "这也正是它的局限。加 --with-agent 可以用 Agent 对照。"
    )

    # --- 6. agent ----------------------------------------------------------
    if args.with_agent:
        step(6, total, "Agent 调查（需要服务端配置 LLM_*）")
        status, started = api.call("POST", f"/api/v1/alerts/{alert_id}/investigations")
        if status == 503:
            return fail("服务端没有配置模型：这是 503，不是崩溃")
        if status not in (200, 202):
            return fail(f"发起调查返回 {status}：{started}")
        investigation_id = started["id"]
        detail(f"HTTP {status}  status={started['status']}（异步，立即返回）")

        final: dict[str, Any] = {}
        deadline = time.monotonic() + args.agent_timeout
        while time.monotonic() < deadline:
            status, final = api.call(
                "GET", f"/api/v1/investigations/{investigation_id}"
            )
            if final["status"] not in ("pending", "running"):
                break
            time.sleep(0.4)

        detail(
            f"最终：{final['status']}  轮次={final['rounds_used']}  "
            f"工具调用={final['tool_calls_used']}  耗时={final['duration_ms']}ms"
        )
        for call in final.get("tool_calls", []):
            detail(
                f"  调用 {call['tool_name']}({call['arguments']}) → {call['status']}"
            )

        if final["status"] == "failed":
            detail(f"error_code={final['error_code']}：{final['error']}")
            detail("失败是可见的，不是静默产出一份错误报告。")
        elif final.get("report_id"):
            status, agent_report = api.call(
                "GET", f"/api/v1/reports/{final['report_id']}"
            )
            content = agent_report["content"]
            detail(
                f"报告版本 v{agent_report['version']}　状态={agent_report['status']}"
            )
            detail(f"结论：{content['summary']}")
            detail(
                f"引用：{len(content['evidence'])} 条 / 全量 {content['evidence_total']} 条"
            )
            detail(f"局限（模型自述）：{content['limitations'][0]}")
            detail("每个引用 id 都经过数据库校验，编造的 id 会让整次调查失败。")

    print("\n演示结束。所有数据都是合成数据，不含真实日志或凭据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
