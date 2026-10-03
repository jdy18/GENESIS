"""An OpenAI-compatible `ChatModel`.

Covers vLLM, SGLang, Ollama and most gateways, since they all speak
`POST /v1/chat/completions`. Included so the `ChatModel` protocol has one working
binding, and because the two things that bite when wiring a local server are
handled here:

  * `content` can be `null` on reasoning models, with the text in
    `reasoning_content`. A caller that reads only `content` sees an empty reply
    and scores the case as a non-answer.
  * per-endpoint concurrency has to be capped somewhere, and the workflow fans
    out three pathways x several sources x several candidates.

`urllib` rather than `httpx`/`aiohttp` so the package stays dependency-free;
requests run in a thread. If you already have an async HTTP client, write your
own adapter instead — the protocol is one method.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request


class OpenAIChat:
    """Minimal chat client.

    Args:
        base_url: e.g. ``http://127.0.0.1:8000/v1``
        model:    model id as the server advertises it at ``/v1/models``. Must
                  match exactly — servers reject ids they do not list, and the
                  error ("invalid model identifier") does not say which name it
                  wanted.
        api_key:  sent as ``Authorization: Bearer ...`` when set.
        max_concurrency: in-flight request cap for this endpoint.
        thinking: pass ``False`` to disable reasoning mode on servers that
                  support the ``chat_template_kwargs`` switch. Auxiliary models
                  can use this for short extraction and record-matching tasks.
                  ``None`` retains the server's default mode.
        requires_external_access: set ``False`` for a locally hosted endpoint
                  whose requests stay within the deployment network. Public
                  gateways, including those reached through a local proxy,
                  require external access. The default is ``True``.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        max_concurrency: int = 16,
        timeout: float = 180.0,
        thinking: bool | None = None,
        requires_external_access: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.requires_external_access = requires_external_access
        self._key = api_key
        self._sem = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
        self._thinking = thinking

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self._thinking}
        async with self._sem:
            payload = await asyncio.to_thread(self._post, body)
        return _content(payload)

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from None


def _content(payload: dict) -> str:
    """Text out of a completion, tolerating reasoning-model shapes."""
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"unexpected response shape: {str(payload)[:200]}") from None
    for key in ("content", "reasoning_content", "reasoning"):
        v = msg.get(key)
        if isinstance(v, str) and v.strip():
            return v
    # Distinguish "the model was cut off" from "the server returned nothing",
    # because the fix differs: raise max_tokens vs. check the request.
    reason = (payload.get("choices") or [{}])[0].get("finish_reason")
    if reason == "length":
        raise RuntimeError("reply truncated (finish_reason=length); raise max_tokens")
    raise RuntimeError("empty reply from model")
