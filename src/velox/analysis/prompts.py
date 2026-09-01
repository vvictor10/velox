"""Prompt loading and version parsing."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PromptTemplate(BaseModel):
    name: str
    version: str
    body: str


@lru_cache(maxsize=16)
def load_prompt(name: str) -> PromptTemplate:
    path = PROMPT_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)
    return PromptTemplate(
        name=metadata.get("name", name),
        version=metadata.get("version", "0.0.0"),
        body=body.strip(),
    )


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, raw_metadata, body = text.split("---", 2)
    metadata: dict[str, str] = {}
    for line in raw_metadata.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body
