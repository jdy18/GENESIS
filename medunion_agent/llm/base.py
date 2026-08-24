"""LLM interface.

One protocol, three roles: the reasoning engine that proposes and revises the
differential, the working model that drives the agents and the audit narrative,
and — behind the tool layer — whatever serves phenotype extraction and record
condensation. Those are three bindings of the same interface, so callers accept a
`ChatModel` and the wiring decides which weights answer.

Deliberately minimal: `chat()` and nothing else. Retry policy, concurrency caps
and provider-specific request shaping belong in an adapter, not in a workflow
other people have to read.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatModel(Protocol):
    """A chat-completion endpoint.

    Implementations should raise on transport failure rather than returning a
    sentinel string. The workflow catches per-stage and degrades explicitly —
    an agent that fails is recorded as `AgentReport(failed=True)` so the audit
    can tell "no evidence found" apart from "the retrieval broke", which are
    very different inputs to a diagnostic decision.
    """

    async def chat(self, system: str, user: str, *,
                   temperature: float = 0.0,
                   max_tokens: int = 4096) -> str:
        ...


# ── JSON coercion ────────────────────────────────────────────────────────────

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def parse_json(text: str) -> Any:
    """Best-effort JSON out of a model reply.

    In the library because every caller needs it and getting it wrong fails
    silently: a parser that rejects fenced replies turns them into wrong answers
    rather than parse errors, making the pipeline look less accurate than it is.

    Order matters: strip fences, try whole-string, then fall back to the
    outermost balanced object or array.
    """
    if not text:
        return None
    s = _FENCE.sub("", text.strip())
    try:
        return json.loads(s)
    except Exception:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except Exception:
                        break
    return None
