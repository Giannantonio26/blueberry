from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
MAX_LLM_REQUEST_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 8.0
OPENAI_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


def build_llm_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _is_openai_compatible_chat_url(base_url: str) -> bool:
    normalized = base_url.strip().lower()
    return (
        "generativelanguage.googleapis.com" in normalized
        or "/openai/" in normalized
        or normalized.endswith(OPENAI_CHAT_COMPLETIONS_SUFFIX)
        or normalized.endswith(f"/v1{OPENAI_CHAT_COMPLETIONS_SUFFIX}")
        or normalized.endswith(f"/v1beta{OPENAI_CHAT_COMPLETIONS_SUFFIX}")
    )


def derive_llm_endpoint_url(base_url: str, endpoint: str) -> str:
    parsed = urlsplit(base_url)
    normalized_endpoint = endpoint.strip().lstrip("/")
    if not normalized_endpoint:
        raise ValueError("Endpoint cannot be empty.")

    stripped_path = parsed.path.rstrip("/")
    if "/api/" in stripped_path:
        prefix, _separator, _tail = stripped_path.rpartition("/")
        next_path = f"{prefix}/{normalized_endpoint}"
    else:
        next_path = f"/api/{normalized_endpoint}"

    return urlunsplit((parsed.scheme, parsed.netloc, next_path, "", ""))


def derive_openai_compatible_endpoint_url(base_url: str, endpoint: str) -> str:
    parsed = urlsplit(base_url)
    normalized_endpoint = endpoint.strip().lstrip("/")
    if not normalized_endpoint:
        raise ValueError("Endpoint cannot be empty.")

    stripped_path = parsed.path.rstrip("/")
    if stripped_path.endswith(OPENAI_CHAT_COMPLETIONS_SUFFIX):
        base_path = stripped_path[: -len(OPENAI_CHAT_COMPLETIONS_SUFFIX)]
    else:
        base_path = stripped_path

    if not base_path:
        next_path = f"/{normalized_endpoint}"
    else:
        next_path = f"{base_path}/{normalized_endpoint}"

    return urlunsplit((parsed.scheme, parsed.netloc, next_path, "", ""))


def _parse_retry_after_seconds(raw_retry_after: str | None) -> float | None:
    if not raw_retry_after:
        return None

    stripped = raw_retry_after.strip()
    if not stripped:
        return None

    try:
        retry_after_seconds = float(stripped)
    except ValueError:
        retry_after_seconds = None

    if retry_after_seconds is not None:
        return max(0.0, min(retry_after_seconds, MAX_BACKOFF_SECONDS))

    try:
        retry_after_datetime = datetime.strptime(stripped, "%a, %d %b %Y %H:%M:%S GMT")
        retry_after_datetime = retry_after_datetime.replace(tzinfo=timezone.utc)
        delta_seconds = (retry_after_datetime - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(delta_seconds, MAX_BACKOFF_SECONDS))
    except ValueError:
        return None


def _compute_retry_delay_seconds(
    attempt_index: int,
    *,
    retry_after_seconds: float | None = None,
) -> float:
    if retry_after_seconds is not None:
        return retry_after_seconds

    exponential_backoff = min(1.0 * (2**attempt_index), MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0.0, 0.25)
    return min(exponential_backoff + jitter, MAX_BACKOFF_SECONDS)


def _extract_error_message(response_body: str) -> str | None:
    if not response_body:
        return None

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body

    if isinstance(parsed, dict):
        raw_error = parsed.get("error")
        if isinstance(raw_error, str) and raw_error.strip():
            return raw_error.strip()
        if isinstance(raw_error, dict):
            nested_message = raw_error.get("message")
            if isinstance(nested_message, str) and nested_message.strip():
                return nested_message.strip()

        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return response_body


def post_llm_json(
    api_key: str,
    url: str,
    payload: dict[str, Any],
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(MAX_LLM_REQUEST_ATTEMPTS):
        try:
            response = requests.post(
                url,
                headers=build_llm_headers(api_key),
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            last_error = error
            status_code = error.response.status_code if error.response is not None else None
            response_body = ""
            retry_after_seconds: float | None = None
            if error.response is not None:
                response_body = (error.response.text or "").strip()[:800]
                retry_after_seconds = _parse_retry_after_seconds(
                    error.response.headers.get("Retry-After")
                )

            is_transient = (
                status_code is not None and status_code in TRANSIENT_STATUS_CODES
            )
            if is_transient and attempt < MAX_LLM_REQUEST_ATTEMPTS - 1:
                retry_delay = _compute_retry_delay_seconds(
                    attempt, retry_after_seconds=retry_after_seconds
                )
                if retry_delay > 0:
                    time.sleep(retry_delay)
                continue

            extracted_error = _extract_error_message(response_body)
            suffix = f" Error: {extracted_error}" if extracted_error else ""
            if status_code is not None and status_code >= 500:
                raise RuntimeError(
                    "LLM API returned a server error while processing the request."
                    + suffix
                ) from error

            raise RuntimeError(
                f"LLM API request failed with status {status_code or 'unknown'}."
                + suffix
            ) from error
        except requests.RequestException as error:
            last_error = error
            if attempt < MAX_LLM_REQUEST_ATTEMPTS - 1:
                retry_delay = _compute_retry_delay_seconds(attempt)
                if retry_delay > 0:
                    time.sleep(retry_delay)
                continue
            raise RuntimeError(f"LLM API request failed: {error}") from error

    if last_error is not None:
        raise RuntimeError(f"LLM API request failed: {last_error}") from last_error

    raise RuntimeError("LLM API request failed for an unknown reason.")


def _coerce_openai_content(raw_content: Any) -> str:
    if isinstance(raw_content, str):
        return raw_content

    if isinstance(raw_content, list):
        text_parts: list[str] = []
        for part in raw_content:
            if not isinstance(part, dict):
                continue
            maybe_text = part.get("text")
            if isinstance(maybe_text, str) and maybe_text:
                text_parts.append(maybe_text)
        return "\n".join(text_parts).strip()

    if raw_content is None:
        return ""

    return str(raw_content)


def _coerce_openai_tool_arguments(raw_arguments: Any) -> str:
    if isinstance(raw_arguments, str):
        return raw_arguments

    if raw_arguments is None:
        return "{}"

    try:
        return json.dumps(raw_arguments, ensure_ascii=False)
    except TypeError:
        return "{}"


def _coerce_openai_json_value(raw_value: Any) -> Any:
    if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
        return raw_value

    if isinstance(raw_value, list):
        return [_coerce_openai_json_value(item) for item in raw_value]

    if isinstance(raw_value, dict):
        return {
            str(key): _coerce_openai_json_value(value) for key, value in raw_value.items()
        }

    return str(raw_value)


def _normalize_model_name(raw_model_name: Any) -> str:
    if not isinstance(raw_model_name, str):
        return ""

    normalized_model_name = raw_model_name.strip().lower()
    if normalized_model_name.startswith("models/"):
        normalized_model_name = normalized_model_name[len("models/") :]
    return normalized_model_name


def _requires_gemini_tool_thought_signatures(raw_model_name: Any) -> bool:
    normalized_model_name = _normalize_model_name(raw_model_name)
    return normalized_model_name.startswith("gemini-3")


def _extract_google_thought_signature(
    raw_call: dict[str, Any], normalized_function: dict[str, Any]
) -> str | None:
    raw_extra_content = raw_call.get("extra_content")
    if isinstance(raw_extra_content, dict):
        raw_google_content = raw_extra_content.get("google")
        if isinstance(raw_google_content, dict):
            raw_google_signature = raw_google_content.get("thought_signature")
            if (
                isinstance(raw_google_signature, str)
                and raw_google_signature.strip()
            ):
                return raw_google_signature

    for key in ("thought_signature", "thoughtSignature"):
        raw_signature = raw_call.get(key)
        if isinstance(raw_signature, str) and raw_signature.strip():
            return raw_signature

    for key in ("thought_signature", "thoughtSignature"):
        raw_function_signature = normalized_function.get(key)
        if (
            isinstance(raw_function_signature, str)
            and raw_function_signature.strip()
        ):
            return raw_function_signature

    return None


def _normalize_openai_tool_calls(
    raw_tool_calls: Any,
    *,
    require_google_tool_thought_signatures: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(raw_tool_calls, list):
        return []

    normalized_tool_calls: list[dict[str, Any]] = []
    for index, raw_call in enumerate(raw_tool_calls):
        if not isinstance(raw_call, dict):
            continue

        function_payload = raw_call.get("function")
        if not isinstance(function_payload, dict):
            continue

        tool_name = function_payload.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue

        normalized_call: dict[str, Any] = {}
        for key, value in raw_call.items():
            if key in {"id", "type", "function"}:
                continue
            normalized_call[str(key)] = _coerce_openai_json_value(value)

        normalized_function_payload: dict[str, Any] = {}
        for key, value in function_payload.items():
            if key in {"name", "arguments"}:
                continue
            normalized_function_payload[str(key)] = _coerce_openai_json_value(value)

        raw_call_id = raw_call.get("id")
        call_id = (
            raw_call_id.strip()
            if isinstance(raw_call_id, str) and raw_call_id.strip()
            else f"tool_call_{index + 1}"
        )

        normalized_function_payload["name"] = tool_name.strip()
        normalized_function_payload["arguments"] = _coerce_openai_tool_arguments(
            function_payload.get("arguments")
        )

        normalized_call["id"] = call_id
        normalized_call["type"] = "function"
        normalized_call["function"] = normalized_function_payload

        thought_signature = _extract_google_thought_signature(
            raw_call, normalized_function_payload
        )
        if (
            require_google_tool_thought_signatures
            and index == 0
            and not thought_signature
        ):
            # Official Gemini guidance allows this placeholder for custom function-call blocks.
            thought_signature = "skip_thought_signature_validator"

        if thought_signature:
            extra_content = normalized_call.get("extra_content")
            if not isinstance(extra_content, dict):
                extra_content = {}
            google_content = extra_content.get("google")
            if not isinstance(google_content, dict):
                google_content = {}
            google_content["thought_signature"] = thought_signature
            extra_content["google"] = google_content
            normalized_call["extra_content"] = extra_content

        normalized_tool_calls.append(normalized_call)

    return normalized_tool_calls


def _normalize_openai_messages(
    raw_messages: Any,
    *,
    require_google_tool_thought_signatures: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(raw_messages, list):
        raise RuntimeError("LLM payload is missing a valid messages list.")

    normalized_messages: list[dict[str, Any]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        if not isinstance(role, str):
            continue

        if role in {"system", "user"}:
            normalized_messages.append(
                {
                    "role": role,
                    "content": _coerce_openai_content(message.get("content")),
                }
            )
            continue

        if role == "assistant":
            normalized_assistant: dict[str, Any] = {
                "role": "assistant",
                "content": _coerce_openai_content(message.get("content")),
            }
            tool_calls = _normalize_openai_tool_calls(
                message.get("tool_calls"),
                require_google_tool_thought_signatures=require_google_tool_thought_signatures,
            )
            if tool_calls:
                normalized_assistant["tool_calls"] = tool_calls
            normalized_messages.append(normalized_assistant)
            continue

        if role == "tool":
            raw_tool_call_id = message.get("tool_call_id")
            tool_content = _coerce_openai_content(message.get("content"))
            if isinstance(raw_tool_call_id, str) and raw_tool_call_id.strip():
                normalized_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": raw_tool_call_id.strip(),
                        "content": tool_content,
                    }
                )
                continue

            tool_name = message.get("tool_name")
            if isinstance(tool_name, str) and tool_name.strip():
                normalized_messages.append(
                    {
                        "role": "system",
                        "content": f"Tool result ({tool_name.strip()}):\n{tool_content}",
                    }
                )
                continue

            normalized_messages.append(
                {
                    "role": "system",
                    "content": f"Tool result:\n{tool_content}",
                }
            )
            continue

    if not normalized_messages:
        raise RuntimeError("LLM payload messages list is empty after normalization.")

    return normalized_messages


def _build_openai_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    converted_payload: dict[str, Any] = {}
    require_google_tool_thought_signatures = _requires_gemini_tool_thought_signatures(
        payload.get("model")
    )
    passthrough_keys = (
        "model",
        "messages",
        "stream",
        "tools",
        "tool_choice",
        "temperature",
        "top_p",
        "max_tokens",
    )
    for key in passthrough_keys:
        if key not in payload:
            continue

        value = payload[key]
        if key == "messages":
            converted_payload["messages"] = _normalize_openai_messages(
                value,
                require_google_tool_thought_signatures=require_google_tool_thought_signatures,
            )
            continue

        if key == "stream":
            converted_payload["stream"] = bool(value)
            continue

        if key == "tools":
            if isinstance(value, list) and value:
                converted_payload["tools"] = value
            continue

        if key in {"temperature", "top_p"}:
            if isinstance(value, (int, float)):
                converted_payload[key] = float(value)
            continue

        if key == "max_tokens":
            if isinstance(value, int) and value > 0:
                converted_payload[key] = value
            continue

        converted_payload[key] = value

    if "stream" not in converted_payload:
        converted_payload["stream"] = False

    if "format" in payload:
        converted_payload["response_format"] = {"type": "json_object"}

    return converted_payload


def _normalize_openai_chat_content(raw_content: Any) -> str:
    if isinstance(raw_content, str):
        return raw_content

    if isinstance(raw_content, list):
        text_parts: list[str] = []
        for part in raw_content:
            if not isinstance(part, dict):
                continue
            maybe_text = part.get("text")
            if isinstance(maybe_text, str) and maybe_text.strip():
                text_parts.append(maybe_text.strip())
        return "\n".join(text_parts).strip()

    return ""


def _normalize_openai_chat_response(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM API returned an invalid chat response payload.")

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("LLM API chat response is missing a valid message payload.")

    normalized_message: dict[str, Any] = {
        "content": _normalize_openai_chat_content(message.get("content")),
    }
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        normalized_message["tool_calls"] = tool_calls

    return {"message": normalized_message}


def call_llm(api_key: str, base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_base_url = base_url.strip()
    if not normalized_base_url:
        raise ValueError("LLM base URL cannot be empty.")

    if _is_openai_compatible_chat_url(normalized_base_url):
        converted_payload = _build_openai_chat_payload(payload)
        try:
            raw_response = post_llm_json(
                api_key,
                normalized_base_url,
                converted_payload,
            )
        except RuntimeError as error:
            normalized_error = str(error).lower()
            if (
                "response_format" in converted_payload
                and "status 400" in normalized_error
                and "invalid argument" in normalized_error
            ):
                fallback_payload = dict(converted_payload)
                fallback_payload.pop("response_format", None)
                raw_response = post_llm_json(
                    api_key,
                    normalized_base_url,
                    fallback_payload,
                )
            else:
                raise
        return _normalize_openai_chat_response(raw_response)

    return post_llm_json(api_key, normalized_base_url, payload)


def _parse_openai_embeddings(
    response: dict[str, Any], expected_count: int
) -> list[list[float]] | None:
    raw_data = response.get("data")
    if not isinstance(raw_data, list):
        return None

    parsed_embeddings: list[list[float]] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        raw_embedding = item.get("embedding")
        if not isinstance(raw_embedding, list):
            continue
        parsed_embeddings.append(
            [
                float(value)
                for value in raw_embedding
                if isinstance(value, (int, float))
            ]
        )

    if len(parsed_embeddings) == expected_count:
        return parsed_embeddings
    return None


def embed_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    inputs: list[str],
) -> list[list[float]]:
    normalized_inputs = [text for text in inputs if text.strip()]
    if not normalized_inputs:
        return []

    normalized_base_url = base_url.strip()
    if not normalized_base_url:
        raise ValueError("Embedding base URL cannot be empty.")

    if _is_openai_compatible_chat_url(normalized_base_url):
        response = post_llm_json(
            api_key,
            derive_openai_compatible_endpoint_url(normalized_base_url, "embeddings"),
            {
                "model": model,
                "input": normalized_inputs,
            },
        )
        parsed_openai_embeddings = _parse_openai_embeddings(
            response, len(normalized_inputs)
        )
        if parsed_openai_embeddings is not None:
            return parsed_openai_embeddings
        raise RuntimeError("Embedding request returned an invalid embeddings payload.")

    response = post_llm_json(
        api_key,
        derive_llm_endpoint_url(normalized_base_url, "embed"),
        {
            "model": model,
            "input": normalized_inputs,
        },
    )

    raw_embeddings = response.get("embeddings")
    if isinstance(raw_embeddings, list):
        parsed_embeddings: list[list[float]] = []
        for embedding in raw_embeddings:
            if not isinstance(embedding, list):
                continue
            parsed_embeddings.append(
                [
                    float(value)
                    for value in embedding
                    if isinstance(value, (int, float))
                ]
            )
        if len(parsed_embeddings) == len(normalized_inputs):
            return parsed_embeddings

    raw_embedding = response.get("embedding")
    if isinstance(raw_embedding, list):
        single_embedding = [
            float(value) for value in raw_embedding if isinstance(value, (int, float))
        ]
        if single_embedding:
            return [single_embedding]

    raise RuntimeError("Embedding request returned an invalid embeddings payload.")

