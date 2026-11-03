"""Streaming chat requests to Claude or any OpenAI-compatible server. No UI code.

Uses only the standard library (urllib), so it installs anywhere Inkmill
does, Termux included. API keys come from an environment variable or from a
key file in Inkmill's config folder, never from settings.toml.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

TIMEOUT = 120


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    kind: str  # "anthropic" or "openai"
    base_url: str
    model: str
    key_env: str = ""
    needs_key: bool = True

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url


PRESETS = {
    "anthropic": Provider("anthropic", "Claude (Anthropic)", "anthropic", "https://api.anthropic.com", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    "ollama": Provider("ollama", "Ollama, on this computer", "openai", "http://localhost:11434/v1", "llama3.1", needs_key=False),
    "openai": Provider("openai", "OpenAI-compatible server", "openai", "https://api.openai.com/v1", "", "OPENAI_API_KEY"),
}


def provider_from_settings(table: dict) -> Provider:
    preset = PRESETS.get(str(table.get("provider", "anthropic")), PRESETS["anthropic"])
    return replace(
        preset,
        base_url=str(table.get("base_url") or preset.base_url).rstrip("/"),
        model=str(table.get("model") or preset.model),
        key_env=str(table.get("key_env") or preset.key_env),
    )


class AIError(Exception):
    pass


def key_file(config: Path, provider: Provider) -> Path:
    return config / "ai" / f"{provider.id}.key"


def load_key(config: Path, provider: Provider) -> str | None:
    if provider.key_env and os.environ.get(provider.key_env):
        return os.environ[provider.key_env].strip()
    path = key_file(config, provider)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def save_key(config: Path, provider: Provider, key: str) -> Path:
    path = key_file(config, provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip() + "\n", encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return path


def _post(url: str, headers: dict, body: dict) -> urllib.request.Request:
    return urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"content-type": "application/json", **headers}, method="POST")


def _error_text(exc: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(exc.read().decode("utf-8", "replace"))
        err = data.get("error", data)
        message = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:
        message = exc.reason
    if exc.code in (401, 403):
        return f"the server refused the API key ({exc.code}): {message}"
    if exc.code == 404:
        return f"not found ({exc.code}); check the model name and address: {message}"
    if exc.code == 429:
        return f"rate limited ({exc.code}); wait a moment: {message}"
    return f"HTTP {exc.code}: {message}"


def stream(
    provider: Provider,
    key: str | None,
    system: str,
    messages: list[dict],
    on_text: Callable[[str], None],
    *,
    context: str = "",
    max_tokens: int = 2048,
    cancel: threading.Event | None = None,
) -> str:
    """Send a conversation and call ``on_text`` with each piece of the reply.

    ``context`` (a manuscript, research notes) goes with the system prompt;
    for Claude it is marked for prompt caching, so asking several questions
    about the same long text is cheaper and faster after the first.
    Returns the whole reply.
    """
    if provider.needs_key and not key:
        raise AIError("no API key; set one with AI > Set API Key")
    if not provider.model:
        raise AIError("no model chosen; set one with AI > Settings")
    if provider.kind == "anthropic":
        blocks = [{"type": "text", "text": system}]
        if context:
            blocks.append({"type": "text", "text": context, "cache_control": {"type": "ephemeral"}})
        request = _post(
            f"{provider.base_url}/v1/messages",
            {"x-api-key": key or "", "anthropic-version": "2023-06-01"},
            {"model": provider.model, "max_tokens": max_tokens, "system": blocks, "messages": messages, "stream": True},
        )
    else:
        headers = {"authorization": f"Bearer {key}"} if key else {}
        full_system = system + ("\n\n" + context if context else "")
        request = _post(
            f"{provider.base_url}/chat/completions",
            headers,
            {"model": provider.model, "max_tokens": max_tokens, "stream": True,
             "messages": [{"role": "system", "content": full_system}, *messages]},
        )
    parts: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            for raw in response:
                if cancel is not None and cancel.is_set():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                text = _piece(provider, data)
                if text:
                    parts.append(text)
                    on_text(text)
    except urllib.error.HTTPError as exc:
        raise AIError(_error_text(exc)) from exc
    except urllib.error.URLError as exc:
        raise AIError(f"cannot reach {provider.host}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise AIError(f"{provider.host} stopped responding: {exc}") from exc
    return "".join(parts)


def _piece(provider: Provider, data: dict) -> str:
    if provider.kind == "anthropic":
        if data.get("type") == "error":
            raise AIError(str(data.get("error", {}).get("message", "the server reported an error")))
        if data.get("type") == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return str(delta.get("text", ""))
        return ""
    if "error" in data:
        err = data["error"]
        raise AIError(str(err.get("message") if isinstance(err, dict) else err))
    choices = data.get("choices") or []
    if choices:
        return str((choices[0].get("delta") or {}).get("content") or "")
    return ""
