"""Structured output parsing for LLM responses."""

import json
import re
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

RepairFn = Callable[[str], str | Awaitable[str]]


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse JSON from LLM response text."""
    cleaned = strip_markdown_fences(text)
    return json.loads(cleaned)


def salvage_json_array(text: str, array_key: str) -> dict[str, Any] | None:
    """Extract complete objects from a truncated JSON array (e.g. cut off by token limit)."""
    cleaned = strip_markdown_fences(text)
    marker = f'"{array_key}"'
    key_idx = cleaned.find(marker)
    if key_idx < 0:
        return None

    bracket = cleaned.find("[", key_idx)
    if bracket < 0:
        return None

    items: list[Any] = []
    i = bracket + 1
    length = len(cleaned)

    while i < length:
        while i < length and cleaned[i] in " \t\n\r,":
            i += 1
        if i >= length or cleaned[i] == "]":
            break
        if cleaned[i] != "{":
            break

        depth = 0
        start = i
        in_string = False
        escape = False
        closed = False

        for j in range(i, length):
            char = cleaned[j]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        items.append(json.loads(cleaned[start : j + 1]))
                    except json.JSONDecodeError:
                        pass
                    i = j + 1
                    closed = True
                    break

        if not closed:
            break

    if not items:
        return None
    return {array_key: items}


def parse_structured_output(text: str, schema: type[T]) -> T:
    """Parse and validate LLM output against a Pydantic schema."""
    data = parse_json_response(text)
    return schema.model_validate(data)


async def parse_with_repair(
    text: str,
    schema: type[T],
    repair_fn: RepairFn | None = None,
    *,
    salvage_array_key: str | None = None,
) -> T:
    """Parse structured output with salvage and one repair attempt on failure."""
    try:
        return parse_structured_output(text, schema)
    except (json.JSONDecodeError, ValidationError):
        if salvage_array_key:
            salvaged = salvage_json_array(text, salvage_array_key)
            if salvaged is not None:
                try:
                    return schema.model_validate(salvaged)
                except ValidationError:
                    pass
        if repair_fn is None:
            raise
        repaired = repair_fn(text)
        if isinstance(repaired, Awaitable):
            repaired = await repaired
        return parse_structured_output(repaired, schema)
