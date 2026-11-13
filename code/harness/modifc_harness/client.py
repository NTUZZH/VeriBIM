"""Minimal client for an OpenAI-compatible chat-completions endpoint.

Only the standard library is used, so the harness environment needs nothing
beyond ifcopenshell. Requests are non-streaming, which keeps a run reproducible
and removes streaming-timeout failure modes from the protocol.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class TransportError(RuntimeError):
    """The inference call failed at the transport or protocol level."""


class ContextOverflow(RuntimeError):
    """The server refused the request because the context window is full."""


@dataclass
class ChatResponse:
    content: str
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_message: dict = field(default_factory=dict)
    #: One log-probability per generated token, empty unless the request asked
    #: for them. vLLM 0.27 reports raw log-probabilities, taken before
    #: temperature and top-p are applied, so these are the values of the
    #: distribution at temperature 1 whatever temperature the request used.
    token_logprobs: list[float] = field(default_factory=list)
    #: Token ids for the same positions when the server reports them, and the
    #: token strings otherwise. vLLM's OpenAI-compatible schema carries the
    #: strings and may omit the ids.
    token_ids: list[int] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    #: Prompt tokens served from, and written to, the provider's prompt cache.
    #: Only the native Messages transport reports them; they are already
    #: included in ``prompt_tokens``, which stays the full prompt length.
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        request_timeout: float = 1800.0,
        max_attempts: int = 2,
        retry_delay: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.request_timeout = request_timeout
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_tokens: int | None = None,
        logprobs: bool = False,
    ) -> ChatResponse:
        """One chat completion.

        ``logprobs`` asks the server for the log-probability of each generated
        token. It is off by default and adds nothing to the payload when off,
        so the evaluation protocol sends exactly the request it always sent.
        The values come back from vLLM 0.27 in its default mode, which reports
        the distribution before temperature and top-p are applied, so they are
        log-probabilities at temperature 1 whatever ``temperature`` this request
        used. Anything comparing them against a locally computed value has to
        divide the local logits by 1 rather than by the sampling temperature.
        """
        if os.environ.get("VERIBIM_REQUEST_STYLE", "") == "anthropic_native":
            if logprobs:
                raise ValueError("the native Messages transport has no log-probabilities")
            return self._chat_anthropic_native(messages, tools, max_tokens)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        # Hosted-endpoint request shape (frontier arms), opt-in through
        # VERIBIM_REQUEST_STYLE so every local run sends the request above
        # unchanged. "gpt5": OpenAI's GPT-5 family takes max_completion_tokens
        # and only its default temperature and top_p; an optional
        # VERIBIM_REASONING_EFFORT is passed through when set.
        style = os.environ.get("VERIBIM_REQUEST_STYLE", "")
        if style == "gpt5":
            payload.pop("temperature", None)
            payload.pop("top_p", None)
            if max_tokens:
                payload["max_completion_tokens"] = payload.pop("max_tokens")
            effort = os.environ.get("VERIBIM_REASONING_EFFORT", "")
            if effort:
                payload["reasoning_effort"] = effort
        # "anthropic": the OpenAI-compatible endpoint of the Claude 5 models
        # refuses temperature and top_p; max_tokens stays.
        elif style == "anthropic":
            payload.pop("temperature", None)
            payload.pop("top_p", None)
        # Local sampling knobs (base-model re-read with the model card's
        # recommended settings). Every knob is opt-in through the environment, so a
        # run that sets none of them sends exactly the request above.
        if not style:
            for env, key, cast in (("VERIBIM_LOCAL_TEMPERATURE", "temperature", float),
                                   ("VERIBIM_LOCAL_TOP_P", "top_p", float),
                                   ("VERIBIM_LOCAL_TOP_K", "top_k", int),
                                   ("VERIBIM_LOCAL_PRESENCE_PENALTY", "presence_penalty", float),
                                   ("VERIBIM_LOCAL_SEED", "seed", int)):
                val = os.environ.get(env, "")
                if val:
                    payload[key] = cast(val)
            kwargs = os.environ.get("VERIBIM_CHAT_TEMPLATE_KWARGS", "")
            if kwargs:
                payload["chat_template_kwargs"] = json.loads(kwargs)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if logprobs:
            payload["logprobs"] = True

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                body = self._post("/chat/completions", payload)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:2000]
                if exc.code == 400 and (
                    "maximum context length" in detail
                    or "longer than the maximum" in detail
                    or "context length" in detail
                ):
                    raise ContextOverflow(detail) from exc
                last_error = TransportError(f"HTTP {exc.code}: {detail}")
            except Exception as exc:  # noqa: BLE001 - transport failures of every kind
                last_error = TransportError(f"{type(exc).__name__}: {exc}")
            if attempt < self.max_attempts:
                time.sleep(self.retry_delay)
        else:
            raise last_error or TransportError("inference call failed")

        choice = body["choices"][0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        entries = ((choice.get("logprobs") or {}).get("content") or []) if logprobs else []
        return ChatResponse(
            content=message.get("content") or "",
            # vLLM 0.27.1 returns this as "reasoning"; other servers use
            # "reasoning_content". Accept either.
            reasoning_content=(
                message.get("reasoning") or message.get("reasoning_content") or ""
            ),
            tool_calls=list(message.get("tool_calls") or []),
            finish_reason=choice.get("finish_reason") or "",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            raw_message=message,
            token_logprobs=[float(e.get("logprob") or 0.0) for e in entries],
            token_ids=[int(e["token_id"]) for e in entries if e.get("token_id") is not None],
            tokens=[str(e.get("token") or "") for e in entries],
        )

    def _post_anthropic(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _chat_anthropic_native(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        max_tokens: int | None,
    ) -> ChatResponse:
        """One turn through the native Messages endpoint, with prompt caching.

        The conversation is converted from the chat-completions shape the
        agent keeps, and the reply is converted back, so the agent loop, the
        transcripts and the token accounting are the same as on the
        chat-completions path. Retries and the context-overflow check follow
        ``chat``.
        """
        payload = to_anthropic_request(self.model, messages, tools, max_tokens)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                body = self._post_anthropic("/messages", payload)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:2000]
                if exc.code in (400, 413) and _is_anthropic_overflow(detail):
                    raise ContextOverflow(detail) from exc
                last_error = TransportError(f"HTTP {exc.code}: {detail}")
            except Exception as exc:  # noqa: BLE001 - transport failures of every kind
                last_error = TransportError(f"{type(exc).__name__}: {exc}")
            if attempt < self.max_attempts:
                time.sleep(self.retry_delay)
        else:
            raise last_error or TransportError("inference call failed")
        return from_anthropic_response(body)

    def wait_until_ready(self, timeout: float = 1800.0, poll: float = 5.0) -> dict:
        """Block until the server answers ``/models``, then return the payload."""
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(poll)
        raise TransportError(f"server not ready within {timeout:.0f} s: {last}")


# ---------------------------------------------------------------------------
# Native Messages transport (VERIBIM_REQUEST_STYLE=anthropic_native).
# The chat-completions compatibility endpoint of the Claude models accepts no
# prompt-cache markers, so every round of a trajectory pays for the whole
# transcript again. The native endpoint caches the growing prefix. The two
# functions below convert the agent's chat-completions conversation into a
# native request and a native reply back into ``ChatResponse``; nothing else
# in the harness changes.

ANTHROPIC_VERSION = "2023-06-01"

_CACHE = {"type": "ephemeral"}

#: Native stop reasons and the chat-completions finish reasons they stand for.
_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "refusal": "content_filter",
    "pause_turn": "stop",
}


def _is_anthropic_overflow(detail: str) -> bool:
    text = detail.lower()
    return (
        "prompt is too long" in text
        or "exceed context limit" in text
        or "context window" in text
        or "maximum context length" in text
    )


def _text_of(content: Any) -> str:
    """The text of a chat-completions message content (string or text parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            else:
                raise ValueError(f"unsupported content part: {part!r}")
        return "".join(parts)
    raise ValueError(f"unsupported message content: {content!r}")


def _single_parameter(tools: list[dict] | None, name: str) -> str | None:
    """The one parameter of tool ``name``, or None if it has more or none."""
    for tool in tools or []:
        function = tool.get("function") or {}
        if function.get("name") == name:
            properties = (function.get("parameters") or {}).get("properties") or {}
            if len(properties) == 1:
                return next(iter(properties))
            return None
    return None


def _tool_input(arguments: Any, name: str, tools: list[dict] | None) -> dict:
    """The native ``input`` object for a recorded tool call's arguments.

    Arguments that parse as a JSON object pass through unchanged. A string
    that does not parse (a malformed call from another model or from the
    compatibility endpoint) is kept whole under the tool's single parameter,
    so the model sees what it sent; a tool with several parameters gets it
    under "arguments".
    """
    if isinstance(arguments, dict):
        return arguments
    raw = "" if arguments is None else str(arguments)
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    key = _single_parameter(tools, name) or "arguments"
    return {key: raw}


def to_anthropic_request(
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int | None,
) -> dict:
    """Convert a chat-completions conversation into a native Messages request.

    System messages are lifted into ``system`` and joined with a newline.
    Tool results that answer one assistant turn share one user message. Three
    cache breakpoints are set: the system text, the last tool definition and
    the last content block of the last message, so each round reads the
    prefix the previous round wrote. Temperature and top-p are not sent, as
    on the "anthropic" chat-completions style.
    """
    if not max_tokens:
        raise ValueError("the native Messages endpoint needs max_tokens")
    system_parts: list[str] = []
    converted: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role in ("system", "developer"):
            system_parts.append(_text_of(message.get("content")))
            continue
        if role == "user":
            text = _text_of(message.get("content"))
            converted.append({"role": "user", "content": [{"type": "text", "text": text}]})
            continue
        if role == "assistant":
            blocks: list[dict] = []
            text = _text_of(message.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                name = function.get("name") or ""
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id") or "",
                    "name": name,
                    "input": _tool_input(function.get("arguments"), name, tools),
                })
            if not blocks:
                # An empty assistant turn carries nothing; the native endpoint
                # refuses empty text blocks.
                continue
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id") or "",
                "content": _text_of(message.get("content")),
            }
            previous = converted[-1] if converted else None
            if (previous is not None and previous["role"] == "user"
                    and previous["content"]
                    and all(b.get("type") == "tool_result" for b in previous["content"])):
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        raise ValueError(f"unsupported message role: {role!r}")

    if converted:
        converted[-1]["content"][-1]["cache_control"] = dict(_CACHE)

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens),
        "messages": converted,
    }
    if system_parts:
        payload["system"] = [{
            "type": "text",
            "text": "\n".join(system_parts),
            "cache_control": dict(_CACHE),
        }]
    if tools:
        native_tools = []
        for tool in tools:
            function = tool.get("function") or {}
            entry: dict[str, Any] = {
                "name": function.get("name") or "",
                "input_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
            if function.get("description"):
                entry["description"] = function["description"]
            native_tools.append(entry)
        native_tools[-1]["cache_control"] = dict(_CACHE)
        payload["tools"] = native_tools
        payload["tool_choice"] = {"type": "auto"}
    thinking = os.environ.get("VERIBIM_ANTHROPIC_THINKING", "")
    if thinking:
        # "disabled" or "adaptive"; unset leaves the model's own default.
        payload["thinking"] = {"type": thinking}
    return payload


def from_anthropic_response(body: dict) -> ChatResponse:
    """Convert a native Messages reply into the chat-completions ``ChatResponse``.

    ``prompt_tokens`` is the whole prompt: uncached input plus the tokens
    written to and read from the cache, which is what the chat-completions
    endpoints report as prompt tokens. The cache split is kept alongside.
    """
    texts: list[str] = []
    thoughts: list[str] = []
    tool_calls: list[dict] = []
    for block in body.get("content") or []:
        kind = block.get("type")
        if kind == "text":
            texts.append(block.get("text") or "")
        elif kind == "thinking":
            thoughts.append(block.get("thinking") or "")
        elif kind == "tool_use":
            tool_calls.append({
                "id": block.get("id") or "",
                "type": "function",
                "function": {
                    "name": block.get("name") or "",
                    "arguments": json.dumps(block.get("input") or {}),
                },
            })
    usage = body.get("usage") or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    content = "".join(texts)
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    message["native_content"] = body.get("content") or []
    stop = body.get("stop_reason") or ""
    return ChatResponse(
        content=content,
        reasoning_content="\n".join(t for t in thoughts if t),
        tool_calls=tool_calls,
        finish_reason=_FINISH.get(stop, stop),
        prompt_tokens=int(usage.get("input_tokens") or 0) + cache_creation + cache_read,
        completion_tokens=int(usage.get("output_tokens") or 0),
        raw_message=message,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
    )
