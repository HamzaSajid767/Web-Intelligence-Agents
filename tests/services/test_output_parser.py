"""Output parser repair tests."""

import pytest
from pydantic import BaseModel

from app.ai.output_parser import (
    parse_structured_output,
    parse_with_repair,
    salvage_json_array,
    strip_markdown_fences,
)
from app.ai.schemas import RecommendationsOutput


class SampleOutput(BaseModel):
    name: str
    value: int


def test_strip_markdown_fences():
    """Should remove JSON code fences."""
    text = '```json\n{"name": "test", "value": 1}\n```'
    assert strip_markdown_fences(text) == '{"name": "test", "value": 1}'


def test_parse_structured_output():
    """Should parse and validate JSON against schema."""
    result = parse_structured_output('{"name": "test", "value": 42}', SampleOutput)
    assert result.name == "test"
    assert result.value == 42


@pytest.mark.asyncio
async def test_parse_with_repair_async():
    """Should repair invalid JSON using async repair function."""

    async def repair_fn(_text: str) -> str:
        return '{"name": "repaired", "value": 99}'

    result = await parse_with_repair("not json", SampleOutput, repair_fn)
    assert result.name == "repaired"
    assert result.value == 99


def test_salvage_truncated_recommendations_array():
    """Should recover complete objects from truncated JSON."""
    truncated = """{
  "recommendations": [
    {"problem": "Missing H1", "fix": "Add an H1", "expected_benefit": "Better SEO", "priority": "high"},
    {"problem": "Long title", "fix": "Shorten title", "expected_benefit": "Better CTR", "priority": "medium"},
    {"problem": "Unfinished", "fix": "This string never ends
"""
    salvaged = salvage_json_array(truncated, "recommendations")
    assert salvaged is not None
    assert len(salvaged["recommendations"]) == 2

    result = RecommendationsOutput.model_validate(salvaged)
    assert len(result.recommendations) == 2
