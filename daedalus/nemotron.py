"""NVIDIA Nemotron client.

Cloud: Nemotron 3 Ultra on OpenRouter (free). Local: an OpenAI-compatible
endpoint (Ollama/NIM) for sensitive inference, selected when a prompt touches
cards, customer data, or the ledger. This mirrors NemoClaw's privacy router:
sensitive prompts never leave the box.

Nemotron sometimes stops before emitting valid structured output, so EVERY
structured call goes through `structured()`, which parses, validates, and
retries with a corrective nudge, then raises rather than returning garbage.

With no key and no local URL it runs a labelled offline stub so the system is
runnable without network. The stub never claims to be the real model.
"""

import json
import re

import httpx

from . import config


class NemotronError(RuntimeError):
    pass


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


class Nemotron:
    def __init__(self, transport=None, timeout=60.0):
        # transport(messages, model) -> str  lets tests run offline & deterministic
        self.transport = transport
        self.timeout = timeout
        self.last_route = None

    def _route(self, sensitive):
        if sensitive and config.LOCAL_NEMOTRON_URL:
            return "local", config.LOCAL_NEMOTRON_URL, config.LOCAL_NEMOTRON_MODEL, ""
        return "cloud", config.OPENROUTER_BASE_URL, config.OPENROUTER_MODEL, config.OPENROUTER_API_KEY

    def complete(self, messages, sensitive=False, max_tokens=900):
        route, base, model, key = self._route(sensitive)
        self.last_route = route
        if sensitive and route != "local":
            raise NemotronError("sensitive inference requested but LOCAL_NEMOTRON_URL is not set; "
                                "refusing to send sensitive data to the cloud")
        if self.transport is not None:
            return self.transport(messages, model)
        if not key and route == "cloud":
            return self._stub(messages)
        return self._http(base, model, key, messages, max_tokens)

    def _http(self, base, model, key, messages, max_tokens):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
            headers["HTTP-Referer"] = "https://github.com/esaradev/daedalus"
            headers["X-Title"] = config.PROJECT_NAME
        body = {"model": model, "messages": messages,
                "temperature": 0.6, "top_p": 0.95, "max_tokens": max_tokens}
        try:
            r = httpx.post(base.rstrip("/") + "/chat/completions",
                           json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise NemotronError(f"Nemotron request failed: {e}")
        choices = data.get("choices") or []
        if not choices:
            raise NemotronError("Nemotron returned no choices")
        return choices[0].get("message", {}).get("content", "") or ""

    def chat(self, prompt, sensitive=False):
        return self.complete([{"role": "user", "content": prompt}], sensitive=sensitive)

    def structured(self, messages, validate, max_retries=3, sensitive=False):
        """Return a validated dict, or raise. validate(obj) must return truthy."""
        messages = list(messages)
        last_err = None
        for _ in range(max_retries):
            text = self.complete(messages, sensitive=sensitive)
            try:
                obj = _extract_json(text)
                if not validate(obj):
                    raise ValueError("validation failed")
                return obj
            except Exception as e:
                last_err = e
                messages = messages + [{
                    "role": "user",
                    "content": f"That reply was not valid ({e}). Reply with ONLY the JSON object, nothing else.",
                }]
        raise NemotronError(f"no valid structured output after {max_retries} attempts: {last_err}")

    def _stub(self, messages):
        last = messages[-1]["content"] if messages else ""
        return f"[stub Nemotron — no OPENROUTER_API_KEY set] re: {last[:80]}"
