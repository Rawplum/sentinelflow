"""Model client abstraction.

Only this module talks to a model provider. Everything above it works with
plain dataclasses, which keeps the orchestration testable with a scripted
client and keeps provider-specific HTTP details out of the business logic.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sentinelflow.core.config import get_settings


class ModelNotConfiguredError(RuntimeError):
    """The model provider is not configured; the agent must fail closed."""


class ModelClientError(RuntimeError):
    """The provider call failed or returned something unusable.

    ``retryable`` marks failures that may succeed on a second attempt
    (transport errors, timeouts, 5xx, 429). Deterministic failures such as a
    schema violation are not retryable: repeating the same call would burn
    tokens and produce the same result.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


RiskLevel = Literal["low", "medium", "high", "critical"]


class AgentFindings(BaseModel):
    """The structured result the model must produce to end an investigation."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    risk_level: RiskLevel
    reasoning: str = Field(min_length=1, max_length=8000)
    recommended_actions: list[str] = Field(min_length=1, max_length=10)
    limitations: list[str] = Field(min_length=1, max_length=10)
    cited_event_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @field_validator("recommended_actions", "limitations")
    @classmethod
    def _non_empty_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-empty item")
        return cleaned


@dataclass(frozen=True)
class ToolCallRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    """One model response: either tool calls or a final answer."""

    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    findings: AgentFindings | None = None
    #: Token counts as reported by the provider, when it reports them. Used to
    #: measure cost; never inferred or estimated locally.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ModelClient(Protocol):
    provider: str
    model: str

    def complete(
        self,
        *,
        system_prompt: str,
        transcript: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn: ...


class OpenAICompatibleClient:
    """Minimal chat-completions client for OpenAI-compatible endpoints.

    Uses the standard library so the project does not gain a runtime HTTP
    dependency. Only the configured base URL is ever contacted.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        provider: str = "openai",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.provider = provider
        self.timeout = timeout

    def _payload(
        self,
        system_prompt: str,
        transcript: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        messages = [{"role": "system", "content": system_prompt}, *transcript]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def complete(
        self,
        *,
        system_prompt: str,
        transcript: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(self._payload(system_prompt, transcript, tools)).encode(
                "utf-8"
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx (except 429) is a request problem and will not fix itself.
            retryable = exc.code >= 500 or exc.code == 429
            raise ModelClientError(
                f"Model request failed: HTTP {exc.code}",
                retryable=retryable,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Never include the request (and therefore the API key) in the error.
            raise ModelClientError(
                f"Model request failed: {exc.__class__.__name__}",
                retryable=True,
            ) from exc
        except json.JSONDecodeError as exc:
            raise ModelClientError(
                "Model returned invalid JSON", retryable=True
            ) from exc

        return _parse_completion(body)


def _parse_completion(body: dict[str, Any]) -> ModelTurn:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelClientError("Model response is missing choices") from exc

    usage = body.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    raw_calls = message.get("tool_calls") or []
    calls: list[ToolCallRequest] = []
    for index, raw in enumerate(raw_calls):
        function = raw.get("function") or {}
        name = function.get("name")
        if not name:
            raise ModelClientError("Tool call is missing a function name")
        arguments = function.get("arguments") or "{}"
        try:
            parsed_arguments = (
                json.loads(arguments) if isinstance(arguments, str) else arguments
            )
        except json.JSONDecodeError as exc:
            raise ModelClientError("Tool call arguments are not valid JSON") from exc
        if not isinstance(parsed_arguments, dict):
            raise ModelClientError("Tool call arguments must be a JSON object")
        calls.append(
            ToolCallRequest(
                call_id=str(raw.get("id") or f"call-{index}"),
                name=name,
                arguments=parsed_arguments,
            )
        )

    if calls:
        return ModelTurn(
            tool_calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ModelClientError("Model returned neither tool calls nor content")
    return ModelTurn(
        findings=parse_findings(content),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def parse_findings(content: str) -> AgentFindings:
    """Parse and validate the model's final answer.

    The model is asked for raw JSON. Any deviation is a hard failure rather
    than a best-effort guess, because this object becomes a persisted report.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return AgentFindings.model_validate_json(text)
    except ValidationError as exc:
        raise ModelClientError(
            "Model output did not match the required findings schema"
        ) from exc


def model_is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.llm_provider
        and settings.llm_model
        and settings.llm_api_base
        and settings.llm_api_key is not None
    )


def build_model_client() -> ModelClient:
    """Build the configured client, or raise :class:`ModelNotConfiguredError`."""
    settings = get_settings()
    if not model_is_configured():
        raise ModelNotConfiguredError(
            "AI agent is not configured. Set LLM_PROVIDER, LLM_MODEL, "
            "LLM_API_BASE and LLM_API_KEY."
        )
    assert settings.llm_api_key is not None  # guarded by model_is_configured
    return OpenAICompatibleClient(
        base_url=str(settings.llm_api_base),
        api_key=settings.llm_api_key.get_secret_value(),
        model=str(settings.llm_model),
        provider=str(settings.llm_provider),
        timeout=settings.llm_timeout_seconds,
    )
