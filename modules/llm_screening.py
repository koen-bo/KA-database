"""
OpenAI-backed Step 3 screening execution helpers.

This module keeps LLM execution backend-controlled and lightweight:
- build prompt/messages from existing screening helpers
- call OpenAI Chat Completions
- parse and validate JSON output
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Optional

import requests

import config
from modules.screening import (
    ScreeningOutput,
    build_llm_screening_request,
    build_screening_input,
    build_screening_user_message,
    compile_screening_system_prompt,
    serialize_llm_screening_request,
    validate_screening_output,
)


PostFunc = Callable[..., requests.Response]


@dataclass(frozen=True)
class ScreeningRunResult:
    success: bool
    input_json: str
    output: Optional[ScreeningOutput]
    output_json: Optional[str]
    model: str
    error_text: Optional[str] = None


def screen_document(
    document: Any,
    prompts: Optional[dict[str, str]] = None,
    post_func: Optional[PostFunc] = None,
) -> ScreeningRunResult:
    """Run the full Step 3 screening flow for one document."""
    screening_input = build_screening_input(document)
    llm_request = build_llm_screening_request(screening_input)
    input_json = serialize_llm_screening_request(llm_request)
    prompt_map = prompts or config.load_prompts()
    system_prompt = compile_screening_system_prompt(prompt_map)
    user_message = build_screening_user_message(llm_request)
    model = config.OPENAI_MODEL

    try:
        response_text = _call_openai_screening(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            post_func=post_func,
        )
        parsed = _parse_response_json(response_text)
        validated = validate_screening_output(parsed)
        output_json = json.dumps(asdict(validated), ensure_ascii=False, sort_keys=True)
        return ScreeningRunResult(
            success=True,
            input_json=input_json,
            output=validated,
            output_json=output_json,
            model=model,
        )
    except Exception as exc:
        return ScreeningRunResult(
            success=False,
            input_json=input_json,
            output=None,
            output_json=None,
            model=model,
            error_text=_sanitize_error_text(exc),
        )


def _call_openai_screening(
    system_prompt: str,
    user_message: str,
    model: str,
    post_func: Optional[PostFunc] = None,
) -> str:
    """Call OpenAI Chat Completions and return the raw model text."""
    if not config.OPENAI_API_KEY:
        raise ValueError("KA_OPENAI_API_KEY is not configured")

    post = post_func or requests.post
    url = f"{config.OPENAI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "response_format": {"type": "json_object"},
    }

    attempts = max(1, config.OPENAI_MAX_RETRIES + 1)
    last_error: Optional[Exception] = None

    for _ in range(attempts):
        try:
            response = post(
                url,
                headers=headers,
                json=payload,
                timeout=config.OPENAI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            return _extract_message_text(data)
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            last_error = exc

    raise RuntimeError(f"OpenAI screening call failed after {attempts} attempts: {last_error}")


def _extract_message_text(data: dict[str, Any]) -> str:
    """Extract assistant text from a Chat Completions response payload."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI response contained no choices")

    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenAI response contained no assistant message")

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    raise ValueError("OpenAI response contained empty assistant content")


def _parse_response_json(response_text: str) -> dict[str, Any]:
    """Parse model output into a JSON object, allowing one fenced-json cleanup pass."""
    text = (response_text or "").strip()
    if not text:
        raise ValueError("LLM response was empty")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        cleaned = _strip_json_fence(text)
        parsed = json.loads(cleaned)

    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def _strip_json_fence(text: str) -> str:
    """Strip a simple fenced-json wrapper if the model returned one."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _sanitize_error_text(exc: Exception) -> str:
    """Keep persisted error strings short and safe."""
    message = str(exc).strip() or exc.__class__.__name__
    return message[:1000]
