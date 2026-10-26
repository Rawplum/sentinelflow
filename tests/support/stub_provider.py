"""A local OpenAI-compatible stub provider.

Used to exercise the real HTTP client without a model provider. It returns
canned responses, so it proves protocol handling only - never model quality.
"""

from __future__ import annotations

import json
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: Sentinel response that makes the stub sleep before replying.
SLOW = 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )

        status, payload = self.server.next_response()  # type: ignore[attr-defined]
        if status == SLOW:
            time.sleep(payload)
            status, payload = 200, {"choices": []}

        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


class StubProvider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.responses: deque[tuple[Any, Any]] = deque()
        self.requests: list[dict[str, Any]] = []

    def next_response(self) -> tuple[Any, Any]:
        if len(self.responses) > 1:
            return self.responses.popleft()
        return self.responses[0] if self.responses else (500, {"error": "no stub"})

    @property
    def base_url(self) -> str:
        host = str(self.server_address[0])
        port = int(self.server_address[1])
        return f"http://{host}:{port}/v1"

    def queue_tool_call(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> None:
        self.responses.append(
            (
                200,
                completion(
                    {
                        "tool_calls": [
                            {
                                "id": f"call-{len(self.requests) + len(self.responses)}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments or {}),
                                },
                            }
                        ]
                    }
                ),
            )
        )

    def queue_findings(
        self,
        *,
        cited_event_ids: list[str],
        summary: str = "Investigation completed against a stub provider.",
        risk_level: str = "high",
    ) -> None:
        self.responses.append(
            (
                200,
                completion(
                    {
                        "content": json.dumps(
                            {
                                "summary": summary,
                                "risk_level": risk_level,
                                "reasoning": "Evidence was read with a read-only tool.",
                                "recommended_actions": ["Review manually."],
                                "limitations": [
                                    "Stub provider: not a real model.",
                                ],
                                "cited_event_ids": cited_event_ids,
                            }
                        )
                    }
                ),
            )
        )


def completion(message: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": message}]}


__all__ = ["SLOW", "StubProvider", "completion"]
