"""Provider-independent LLM adapters. All return parsed JSON objects (structured output)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.errors import ProviderError, ProviderNotConfigured


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    actual_usage: bool = False  # provider reported token counts


@dataclass
class LLMConfig:
    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


JSON_RULES = (
    "Respond with ONE valid JSON object only. No markdown fences, no commentary before or after."
)


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError("LLM did not return JSON")
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"LLM returned malformed JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ProviderError("LLM JSON root must be an object")
    return obj


class LLMProvider:
    name = "base"
    is_paid = False

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def generate_json(self, system: str, prompt: str, *, task: str, context: dict[str, Any]) -> LLMResult:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        raise NotImplementedError


# --------------------------------------------------------------------------- Anthropic
class AnthropicProvider(LLMProvider):
    """Claude via the official SDK. Default model: claude-opus-5-5 (configurable).
    Server-side refusal fallbacks are enabled; refusals are surfaced as errors."""

    name = "anthropic"
    is_paid = True

    def _client(self):
        if not self.cfg.api_key:
            raise ProviderNotConfigured("Anthropic API key is not configured")
        import anthropic

        return anthropic.Anthropic(api_key=self.cfg.api_key, max_retries=2, timeout=300)

    def generate_json(self, system, prompt, *, task, context):
        import anthropic

        client = self._client()
        effort = self.cfg.params.get("effort", "medium")
        try:
            resp = client.beta.messages.create(
                model=self.cfg.model,
                max_tokens=int(self.cfg.params.get("max_tokens", 16000)),
                system=f"{system}\n\n{JSON_RULES}",
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise ProviderError(f"Anthropic rate limited: {e.message}", retryable=True) from e
        except anthropic.AuthenticationError as e:
            raise ProviderNotConfigured(f"Anthropic authentication failed: {e.message}") from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"Anthropic rejected the request: {e.message}", retryable=False) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}", retryable=e.status_code >= 500) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Cannot reach Anthropic: {e}", retryable=True) from e
        if resp.stop_reason == "refusal":
            raise ProviderError("Claude declined this request (refusal); topic skipped", retryable=False)
        if resp.stop_reason == "max_tokens":
            raise ProviderError("Claude response hit max_tokens before finishing", retryable=False)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMResult(
            data=extract_json(text),
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=resp.model,
            actual_usage=True,
        )

    def health(self):
        import anthropic

        try:
            m = self._client().models.retrieve(self.cfg.model)
            return True, f"model {m.id} available"
        except ProviderNotConfigured as e:
            return False, str(e)
        except anthropic.APIError as e:
            return False, f"Anthropic: {getattr(e, 'message', e)}"


# --------------------------------------------------------------------------- OpenAI (and compatible)
class OpenAIProvider(LLMProvider):
    name = "openai"
    is_paid = True

    @property
    def base(self) -> str:
        return (self.cfg.base_url or "https://api.openai.com/v1").rstrip("/")

    def _headers(self):
        if not self.cfg.api_key:
            raise ProviderNotConfigured("OpenAI API key is not configured")
        return {"Authorization": f"Bearer {self.cfg.api_key}"}

    def generate_json(self, system, prompt, *, task, context):
        body = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": f"{system}\n\n{JSON_RULES}"}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        try:
            r = httpx.post(f"{self.base}/chat/completions", json=body, headers=self._headers(), timeout=300)
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach OpenAI: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}", retryable=r.status_code in (429, 500, 502, 503))
        j = r.json()
        usage = j.get("usage", {})
        return LLMResult(
            data=extract_json(j["choices"][0]["message"]["content"]),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=j.get("model", self.cfg.model),
            actual_usage=bool(usage),
        )

    def health(self):
        try:
            r = httpx.get(f"{self.base}/models", headers=self._headers(), timeout=20)
            return (r.status_code == 200, "ok" if r.status_code == 200 else f"HTTP {r.status_code}: {r.text[:200]}")
        except (ProviderNotConfigured, httpx.HTTPError) as e:
            return False, str(e)


# --------------------------------------------------------------------------- Gemini
class GeminiProvider(LLMProvider):
    name = "gemini"
    is_paid = True
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def _key(self):
        if not self.cfg.api_key:
            raise ProviderNotConfigured("Gemini API key is not configured")
        return self.cfg.api_key

    def generate_json(self, system, prompt, *, task, context):
        body = {
            "systemInstruction": {"parts": [{"text": f"{system}\n\n{JSON_RULES}"}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            r = httpx.post(
                f"{self.BASE}/models/{self.cfg.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._key()},
                timeout=300,
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Gemini: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Gemini error {r.status_code}: {r.text[:300]}", retryable=r.status_code in (429, 500, 503))
        j = r.json()
        try:
            text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Gemini returned no content (blocked?): {str(j)[:300]}", retryable=False) from e
        um = j.get("usageMetadata", {})
        return LLMResult(
            data=extract_json(text),
            input_tokens=um.get("promptTokenCount", 0),
            output_tokens=um.get("candidatesTokenCount", 0),
            model=self.cfg.model,
            actual_usage=bool(um),
        )

    def health(self):
        try:
            r = httpx.get(f"{self.BASE}/models/{self.cfg.model}", headers={"x-goog-api-key": self._key()}, timeout=20)
            return (r.status_code == 200, "ok" if r.status_code == 200 else f"HTTP {r.status_code}: {r.text[:200]}")
        except (ProviderNotConfigured, httpx.HTTPError) as e:
            return False, str(e)


# --------------------------------------------------------------------------- Ollama (local, free)
class OllamaProvider(LLMProvider):
    name = "ollama"
    is_paid = False

    @property
    def base(self):
        return (self.cfg.base_url or "http://localhost:11434").rstrip("/")

    def generate_json(self, system, prompt, *, task, context):
        body = {
            "model": self.cfg.model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "system", "content": f"{system}\n\n{JSON_RULES}"}, {"role": "user", "content": prompt}],
            "options": {"num_ctx": int(self.cfg.params.get("num_ctx", 8192))},
        }
        try:
            r = httpx.post(f"{self.base}/api/chat", json=body, timeout=900)
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Ollama at {self.base}: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:300]}")
        j = r.json()
        return LLMResult(
            data=extract_json(j["message"]["content"]),
            input_tokens=j.get("prompt_eval_count", 0),
            output_tokens=j.get("eval_count", 0),
            model=self.cfg.model,
            actual_usage=True,
        )

    def health(self):
        try:
            r = httpx.get(f"{self.base}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            if not any(m.split(":")[0] == self.cfg.model.split(":")[0] for m in models):
                return False, f"Ollama is running but model '{self.cfg.model}' is not pulled (have: {', '.join(models) or 'none'})"
            return True, f"ok ({len(models)} models)"
        except httpx.HTTPError as e:
            return False, f"Ollama not reachable at {self.base}: {e}"


PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}
