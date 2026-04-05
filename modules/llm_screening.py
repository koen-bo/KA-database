"""
OpenAI-backed two-lane screening execution helpers.

This module prepares a document once, then supports:
- factual screening first
- exploratory screening second
- shared context selection across both calls
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Optional

import requests

import config
from modules.screening import (
    ExploratoryLLMScreeningRequest,
    ExploratoryScreeningOutput,
    FactualScreeningOutput,
    LLMScreeningRequest,
    NormalizedExploratoryResult,
    NormalizedFactualResult,
    ScreeningInput,
    build_exploratory_llm_screening_request,
    build_exploratory_screening_user_message,
    build_llm_screening_request,
    build_screening_input,
    build_screening_user_message,
    compile_exploratory_system_prompt,
    compile_factual_system_prompt,
    normalize_exploratory_screening_output,
    normalize_factual_screening_output,
    parse_raw_exploratory_screening_output,
    parse_raw_factual_screening_output,
    serialize_exploratory_llm_screening_request,
    serialize_llm_screening_request,
    serialize_screening_input,
)
from modules.screening_context import (
    ScreeningContextSelection,
    load_core_context,
    load_rvo_footholds,
    load_strategic_lenses,
    select_context_for_document,
    serialize_context_selection,
)


PostFunc = Callable[..., requests.Response]


@dataclass(frozen=True)
class LaneScreeningRunResult:
    success: bool
    input_json: str
    output_json: Optional[str]
    model: str
    error_text: Optional[str] = None
    warnings: Optional[list[str]] = None
    repairs_applied: Optional[list[str]] = None


@dataclass(frozen=True)
class PreparedScreeningRun:
    screening_input: ScreeningInput
    screening_input_json: str
    context_selection: ScreeningContextSelection
    context_json: str
    factual_request: LLMScreeningRequest
    factual_input_json: str
    factual_system_prompt: str
    factual_user_message: str
    model: str


@dataclass(frozen=True)
class FactualScreeningRunResult(LaneScreeningRunResult):
    output: Optional[FactualScreeningOutput] = None
    normalized: Optional[NormalizedFactualResult] = None


@dataclass(frozen=True)
class ExploratoryScreeningRunResult(LaneScreeningRunResult):
    output: Optional[ExploratoryScreeningOutput] = None
    normalized: Optional[NormalizedExploratoryResult] = None


@dataclass(frozen=True)
class TwoLaneScreeningRunResult:
    prepared: PreparedScreeningRun
    factual: FactualScreeningRunResult
    exploratory: Optional[ExploratoryScreeningRunResult]


def prepare_document_for_screening(
    document: Any,
    prompts: Optional[dict[str, str]] = None,
) -> PreparedScreeningRun:
    """Prepare excerpt, context selection, and factual prompt payload once."""
    prompt_map = prompts or config.load_prompts()
    screening_input = build_screening_input(document)
    context_selection = select_context_for_document(
        title=screening_input.title,
        keyword_tags=screening_input.keyword_tags,
        excerpt_text=screening_input.excerpt_text,
        lenses=load_strategic_lenses(),
        footholds=load_rvo_footholds(),
    )
    factual_request = build_llm_screening_request(screening_input)
    factual_input_json = serialize_llm_screening_request(factual_request)
    factual_system_prompt = compile_factual_system_prompt(
        prompt_map,
        selected_lenses=context_selection.selected_lenses,
        selected_footholds=context_selection.selected_footholds,
        core_context_text=load_core_context(),
    )
    return PreparedScreeningRun(
        screening_input=screening_input,
        screening_input_json=serialize_screening_input(screening_input),
        context_selection=context_selection,
        context_json=serialize_context_selection(context_selection),
        factual_request=factual_request,
        factual_input_json=factual_input_json,
        factual_system_prompt=factual_system_prompt,
        factual_user_message=build_screening_user_message(factual_request),
        model=config.OPENAI_MODEL,
    )


def screen_factual_document(
    prepared: PreparedScreeningRun,
    post_func: Optional[PostFunc] = None,
) -> FactualScreeningRunResult:
    """Run the factual screening lane."""
    try:
        response_text = _call_openai_screening(
            system_prompt=prepared.factual_system_prompt,
            user_message=prepared.factual_user_message,
            model=prepared.model,
            post_func=post_func,
        )
        parsed = _parse_response_json(response_text)
        normalized = normalize_factual_screening_output(parse_raw_factual_screening_output(parsed))
        output_json = json.dumps(asdict(normalized.output), ensure_ascii=False, sort_keys=True)
        return FactualScreeningRunResult(
            success=True,
            input_json=prepared.factual_input_json,
            output=normalized.output,
            output_json=output_json,
            model=prepared.model,
            warnings=normalized.warnings,
            repairs_applied=normalized.repairs_applied,
            normalized=normalized,
        )
    except Exception as exc:
        return FactualScreeningRunResult(
            success=False,
            input_json=prepared.factual_input_json,
            output=None,
            output_json=None,
            model=prepared.model,
            error_text=_sanitize_error_text(exc),
            warnings=[],
            repairs_applied=[],
            normalized=None,
        )


def prepare_exploratory_prompt(
    prepared: PreparedScreeningRun,
    factual_output: FactualScreeningOutput,
    prompts: Optional[dict[str, str]] = None,
) -> tuple[ExploratoryLLMScreeningRequest, str, str, str]:
    """Build exploratory request, serialized input, system prompt, and user message."""
    prompt_map = prompts or config.load_prompts()
    request = build_exploratory_llm_screening_request(prepared.screening_input, factual_output)
    input_json = serialize_exploratory_llm_screening_request(request)
    system_prompt = compile_exploratory_system_prompt(
        prompt_map,
        selected_lenses=prepared.context_selection.exploratory_lenses,
        selected_footholds=prepared.context_selection.exploratory_footholds,
        core_context_text=load_core_context(),
    )
    user_message = build_exploratory_screening_user_message(request)
    return request, input_json, system_prompt, user_message


def screen_exploratory_document(
    prepared: PreparedScreeningRun,
    factual_output: FactualScreeningOutput,
    prompts: Optional[dict[str, str]] = None,
    post_func: Optional[PostFunc] = None,
) -> ExploratoryScreeningRunResult:
    """Run the exploratory screening lane after factual success."""
    _, input_json, system_prompt, user_message = prepare_exploratory_prompt(
        prepared,
        factual_output=factual_output,
        prompts=prompts,
    )

    try:
        response_text = _call_openai_screening(
            system_prompt=system_prompt,
            user_message=user_message,
            model=prepared.model,
            post_func=post_func,
        )
        parsed = _parse_response_json(response_text)
        normalized = normalize_exploratory_screening_output(
            parse_raw_exploratory_screening_output(parsed),
            factual_output=factual_output,
        )
        output_json = json.dumps(asdict(normalized.output), ensure_ascii=False, sort_keys=True)
        return ExploratoryScreeningRunResult(
            success=True,
            input_json=input_json,
            output=normalized.output,
            output_json=output_json,
            model=prepared.model,
            warnings=normalized.warnings,
            repairs_applied=normalized.repairs_applied,
            normalized=normalized,
        )
    except Exception as exc:
        return ExploratoryScreeningRunResult(
            success=False,
            input_json=input_json,
            output=None,
            output_json=None,
            model=prepared.model,
            error_text=_sanitize_error_text(exc),
            warnings=[],
            repairs_applied=[],
            normalized=None,
        )


def screen_document(
    document: Any,
    prompts: Optional[dict[str, str]] = None,
    post_func: Optional[PostFunc] = None,
) -> TwoLaneScreeningRunResult:
    """Convenience wrapper that runs both lanes in sequence."""
    prepared = prepare_document_for_screening(document=document, prompts=prompts)
    factual = screen_factual_document(prepared=prepared, post_func=post_func)

    if not factual.success or not factual.output:
        return TwoLaneScreeningRunResult(prepared=prepared, factual=factual, exploratory=None)

    exploratory = screen_exploratory_document(
        prepared=prepared,
        factual_output=factual.output,
        prompts=prompts,
        post_func=post_func,
    )
    return TwoLaneScreeningRunResult(prepared=prepared, factual=factual, exploratory=exploratory)


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
