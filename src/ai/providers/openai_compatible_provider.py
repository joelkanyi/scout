"""OpenAI-compatible provider.

Works with any endpoint that speaks the OpenAI /chat/completions API:
Alibaba Qwen (DashScope compatible-mode), DeepSeek, OpenAI, Groq, Together, and
others. The base URL, API key, and model are set during `scout setup`.
"""

import httpx

from src.ai.providers.base import AIProvider, ProviderError, RateLimitedError


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, api_key: str, model: str, base_url: str):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "OpenAI-compatible"

    def _post(self, system_prompt: str, user_prompt: str, max_tokens: int, json_mode: bool) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=120,
        )
        if resp.status_code == 429:
            raise RateLimitedError("Rate limited (429)")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        try:
            return self._post(system_prompt, user_prompt, max_tokens, json_mode=True)
        except RateLimitedError:
            raise
        except httpx.HTTPStatusError as e:
            # Some endpoints or models reject response_format; retry once plain.
            if e.response is not None and e.response.status_code == 400:
                try:
                    return self._post(system_prompt, user_prompt, max_tokens, json_mode=False)
                except httpx.HTTPStatusError as e2:
                    raise ProviderError(f"OpenAI-compatible HTTP error: {e2}") from e2
            raise ProviderError(f"OpenAI-compatible HTTP error: {e}") from e
        except httpx.TimeoutException as e:
            raise ProviderError(f"Request timed out: {e}") from e
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected response format: {e}") from e

    def validate_key(self) -> bool:
        try:
            resp = httpx.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
