"""Claude-backed extraction: forced tool call, schema validation, bounded repair loop."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Protocol

from pydantic import ValidationError

from .documents import Chunk
from .schema import Extraction, tool_schema

PROMPT_VERSION = "extract_v1"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = os.environ.get("FSE_MODEL", "claude-sonnet-4-5")
TOOL_NAME = "record_statement"


class MessagesClient(Protocol):  # the slice of anthropic.Anthropic we use; lets tests pass a fake
    def create(self, **kwargs: Any) -> Any: ...


def render_prompt(statement_type: str, chunks: list[Chunk], version: str = PROMPT_VERSION) -> str:
    template = (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
    excerpts = "\n\n".join(f"--- page {c.page} ---\n{c.text}" for c in chunks)
    return template.replace("{{statement_type}}", statement_type).replace("{{excerpts}}", excerpts)


def _tool_input(response: Any) -> Optional[dict]:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            return block.input
    return None


def extract(
    chunks: list[Chunk],
    statement_type: str,
    client: Optional[MessagesClient] = None,
    model: str = DEFAULT_MODEL,
    max_repairs: int = 2,
) -> tuple[Extraction, dict]:
    """Returns (extraction, trace). trace records prompt version, model and attempts for audit."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic().messages  # reads ANTHROPIC_API_KEY; key is never logged

    messages: list[dict] = [{"role": "user", "content": render_prompt(statement_type, chunks)}]
    tools = [{"name": TOOL_NAME, "description": "Record the extracted statement fields.", "input_schema": tool_schema()}]
    errors: list[str] = []

    for attempt in range(1, max_repairs + 2):
        response = client.create(
            model=model,
            max_tokens=2048,
            temperature=0,
            tools=tools,
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=messages,
        )
        raw = _tool_input(response)
        try:
            if raw is None:
                raise ValueError("no tool call returned")
            result = Extraction.model_validate(raw)
            trace = {"prompt_version": PROMPT_VERSION, "model": model, "attempts": attempt, "repairs": errors}
            return result, trace
        except (ValidationError, ValueError) as e:
            errors.append(str(e)[:500])
            # Repair turn: show the model its own output and the validation error.
            tool_id = next((b.id for b in getattr(response, "content", []) if getattr(b, "type", None) == "tool_use"), None)
            messages.append({"role": "assistant", "content": response.content})
            if tool_id:
                messages.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": tool_id, "is_error": True,
                    "content": f"Validation failed: {errors[-1]}. Call {TOOL_NAME} again with corrected input.",
                }]})
            else:
                messages.append({"role": "user", "content": f"Call {TOOL_NAME}. Previous error: {errors[-1]}"})

    raise RuntimeError(f"Extraction failed schema validation after {max_repairs + 1} attempts: {errors}")
