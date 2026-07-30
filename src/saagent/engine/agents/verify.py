"""Adversarial verification: spawn N skeptics to refute a claim, then majority-vote.

This is what lets a weaker model stay reliable — a single judgment may be wrong,
but "generate then independently try to refute" filters out the bad ones.
"""
from __future__ import annotations

import asyncio

from ..llm.base import LLMClient, extract_json
from .workspace import Trace

_SYS = (
    "You are a rigorous bibliometric reviewer assessing a claim. Refute it ONLY if it is "
    "clearly wrong — e.g. the paper is clearly unrelated to the field, or clearly not "
    "foundational/seminal for it. If the paper is plausibly a seminal work or a direct "
    "progenitor of the field's core ideas, do NOT refute. Avoid both rubber-stamping and "
    "over-refusing. Answer STRICT JSON only."
)


def _prompt(claim: str, context: str) -> str:
    return (
        f"Claim:\n{claim}\n\nEvidence/context:\n{context}\n\n"
        "Judge the claim fairly. Refute only if clearly unjustified. "
        'Return JSON: {"refuted": true|false, "reason": "<one line>"}'
    )


async def verify_claim(
    llm: LLMClient,
    claim: str,
    context: str,
    n: int = 3,
    trace: Trace | None = None,
) -> dict:
    """Return {verdict: bool, support: int, n: int, reasons: [str]}."""
    if not llm.available or n <= 0:
        return {"verdict": True, "support": 0, "n": 0, "reasons": ["(no verifier)"]}

    async def one():
        raw = await asyncio.to_thread(llm.complete_text, _SYS, _prompt(claim, context))
        out = extract_json(raw)
        if not isinstance(out, dict):
            return {"refuted": True, "reason": "unparseable -> treated as refuted"}
        return out

    votes = await asyncio.gather(*(one() for _ in range(n)))
    support = sum(1 for v in votes if not v.get("refuted", True))  # votes that did NOT refute
    verdict = support * 2 > n  # strict majority must fail to refute
    reasons = [v.get("reason", "") for v in votes]
    if trace:
        trace.add("verifier", "verify", {"claim": claim[:120], "support": support, "n": n, "verdict": verdict})
    return {"verdict": verdict, "support": support, "n": n, "reasons": reasons}
