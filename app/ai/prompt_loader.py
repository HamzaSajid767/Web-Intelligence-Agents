"""Prompt loading utilities."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str, **kwargs: str) -> str:
    """Load and format a prompt template by filename."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {name}")
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)
