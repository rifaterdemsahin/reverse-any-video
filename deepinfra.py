"""Minimal DeepInfra client: OpenAI-compatible chat completions, standard library only.

Environment:
  DEEPINFRA_API_KEY        turns the LLM steps on (unset: they are skipped)
  DEEPINFRA_BASE_URL       default https://api.deepinfra.com/v1/openai
  DEEPINFRA_VISION_MODEL   model that reads frames   (default Qwen/Qwen2.5-VL-32B-Instruct)
  DEEPINFRA_TEXT_MODEL     model that writes text    (default meta-llama/Llama-3.3-70B-Instruct)

Model names change often. Check the live list at deepinfra.com and set these if a default is retired.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai").rstrip("/")
VISION_MODEL = os.environ.get("DEEPINFRA_VISION_MODEL", "Qwen/Qwen2.5-VL-32B-Instruct")
TEXT_MODEL = os.environ.get("DEEPINFRA_TEXT_MODEL", "meta-llama/Llama-3.3-70B-Instruct")


class DeepInfraError(RuntimeError):
    """The API refused, timed out, or returned something unusable."""


def api_key() -> str | None:
    return os.environ.get("DEEPINFRA_API_KEY", "").strip() or None


def image_part(jpg: bytes) -> dict:
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}}


def text_only(messages: list[dict]) -> list[dict]:
    """The prompt without image data: images become a short marker. Used for the saved trace."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    parts.append("[image]")
            content = "\n".join(parts)
        out.append({"role": m.get("role", ""), "content": content})
    return out


def _request(messages: list[dict], model: str, key: str, max_tokens: int, timeout: int) -> str:
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens,
                       "temperature": 0.2}).encode()
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace")
        raise DeepInfraError(f"DeepInfra HTTP {e.code} for {model}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise DeepInfraError(f"DeepInfra unreachable for {model}: {getattr(e, 'reason', e)}") from None
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise DeepInfraError(f"DeepInfra returned no message for {model}") from None


def chat(messages: list[dict], model: str, key: str, max_tokens: int = 3000, timeout: int = 180,
         record=None) -> str:
    """One chat call. If `record` is given, it gets one entry per call: the prompt (no image data),
    and the reply or the error."""
    try:
        answer = _request(messages, model, key, max_tokens, timeout)
    except DeepInfraError as e:
        if record:
            record({"at": time.time(), "model": model, "prompt": text_only(messages), "error": str(e)})
        raise
    if record:
        record({"at": time.time(), "model": model, "prompt": text_only(messages), "response": answer})
    return answer


def parse_json(text: str):
    """Models often wrap JSON in code fences or add a sentence. Take the first JSON array or object."""
    t = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\[.*\]|\{.*\})", t, flags=re.S)
    if not m:
        raise DeepInfraError("the model's answer contained no JSON")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise DeepInfraError(f"the model's JSON did not parse: {e.msg}") from None
