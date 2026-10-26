"""Preflight check for the configured model endpoint.

A benchmark run makes up to nine cases x five model rounds. If the endpoint is
misconfigured, the first failure is an opaque error and the other eight cases
just repeat it, hiding the cause behind a table of noise. This does one tiny
call first and says exactly what is wrong.

    python -m benchmark.runner --probe

It answers three questions in order:

1. Is a provider configured at all (env vars present)?
2. Does ``GET {base}/models`` accept the key? Diagnostic only: some gateways
   disable that route, so a 404/405 is reported but not treated as fatal.
3. Does a real ``POST {base}/chat/completions`` return a schema-valid findings
   object? This is the check that matters - it exercises the same code path the
   benchmark uses, including the JSON contract the agent depends on.

The API key is never printed in full and never written to disk.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

from sentinelflow.ai.model_client import (
    ModelClientError,
    build_model_client,
    model_is_configured,
)
from sentinelflow.core.config import get_settings

#: A minimal findings object. Kept valid so a 200 means "the model follows the
#: JSON contract", not just "the socket opened".
PROBE_PROMPT = (
    "Return only a JSON object, no prose and no code fences, with exactly these "
    "keys: summary (string), risk_level (one of low/medium/high/critical), "
    "reasoning (string), recommended_actions (array of strings), "
    "limitations (array of strings), cited_event_ids (array containing the "
    "string 00000000-0000-4000-8000-000000000000)."
)


def _mask(secret: str) -> str:
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}...{secret[-4:]}"


def _models_status(base_url: str, api_key: str, timeout: float) -> tuple[int, str]:
    """GET {base}/models. Diagnostic only; never raises."""
    url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, body[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def probe() -> int:
    """Return 0 when the endpoint is usable, 2 otherwise."""
    settings = get_settings()

    if not model_is_configured():
        print(
            "not configured: set LLM_PROVIDER, LLM_MODEL, LLM_API_BASE and LLM_API_KEY",
            file=sys.stderr,
        )
        return 2

    base_url = str(settings.llm_api_base)
    api_key = (
        settings.llm_api_key.get_secret_value()
        if settings.llm_api_key is not None
        else ""
    )
    print(f"provider: {settings.llm_provider}")
    print(f"model:    {settings.llm_model}")
    print(f"base:     {base_url}")
    print(f"key:      {_mask(api_key)}")
    # Keep diagnostics ordered: stdout is block-buffered when redirected.
    sys.stdout.flush()

    status, body = _models_status(base_url, api_key, settings.llm_timeout_seconds)
    if status == 200:
        print("GET /models: 200")
    elif status == 0:
        print(f"GET /models: unreachable ({body})", file=sys.stderr)
    else:
        # Not fatal: the benchmark only needs chat/completions.
        print(f"GET /models: {status} (diagnostic only) {body}", file=sys.stderr)
    sys.stdout.flush()

    try:
        client = build_model_client()
        turn = client.complete(
            system_prompt="You are a connectivity check.",
            transcript=[{"role": "user", "content": PROBE_PROMPT}],
            tools=[],
        )
    except ModelClientError as exc:
        print(f"chat/completions: FAILED - {exc}", file=sys.stderr)
        if exc.retryable:
            print("  (the client classified this as retryable)", file=sys.stderr)
        return 2

    if turn.findings is None:
        # A tool call instead of an answer still proves auth and protocol work,
        # but it means the model ignored the instruction, which the benchmark
        # would penalise. Report it rather than hiding it.
        print(
            "chat/completions: reachable, but the model called a tool instead "
            "of answering; the benchmark passes tools, so this may be fine",
            file=sys.stderr,
        )
        return 0

    print("chat/completions: 200, findings schema valid")
    print(
        "risk_level:",
        turn.findings.risk_level,
        "| cited:",
        len(turn.findings.cited_event_ids),
    )
    print()
    print(
        "endpoint is usable. Next: python -m benchmark.runner --baseline all --model real"
    )
    return 0


def main() -> int:
    return probe()


if __name__ == "__main__":
    raise SystemExit(main())
