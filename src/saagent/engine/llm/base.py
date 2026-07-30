"""Pluggable LLM interface. Implement to add a new model backend."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod


class LLMClient(ABC):
    available: bool = False

    @abstractmethod
    def complete_text(self, system: str, prompt: str) -> str | None:
        """Return raw text, or None if unavailable/failed."""

    def complete_json(self, system: str, prompt: str):
        """Return parsed JSON (dict/list), or None. Default: parse complete_text."""
        text = self.complete_text(system, prompt)
        return extract_json(text)


def extract_json(text: str | None):
    """Best-effort JSON extraction from an LLM response.

    Handles ```json fences, trailing prose, and malformed JSON (unescaped quotes,
    trailing commas, etc.) via json_repair as a fallback.
    """
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # fall back: grab the first {...} or [...] block
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            block = t[i : j + 1]
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass
            # use json_repair for malformed LLM output
            try:
                from json_repair import repair_json
                repaired = repair_json(block, return_objects=True)
                if isinstance(repaired, (dict, list)):
                    return repaired
            except Exception:
                pass
    return None
