"""Client LLM minimal, sans dépendance. Fournisseur choisi par variables d'environnement, aucune clé en dur.

CHESSCOACH_LLM_PROVIDER = deepseek | ollama | anthropic   (défaut : deepseek, décision D-010)
CHESSCOACH_LLM_MODEL    = nom du modèle (défauts : deepseek-chat / qwen2.5:7b / claude-sonnet-5)
DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, OLLAMA_HOST (défaut http://localhost:11434)
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from chesscoach.env import load_dotenv

Message = dict[str, str]
Chat = Callable[[list[Message]], str]

DEFAULT_MODELS = {"deepseek": "deepseek-chat", "ollama": "qwen2.5:7b", "anthropic": "claude-sonnet-5"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    temperature: float = 0.2
    max_tokens: int = 800

    @classmethod
    def from_env(cls) -> LLMConfig:
        load_dotenv()
        provider = os.environ.get("CHESSCOACH_LLM_PROVIDER", "deepseek").lower()
        model = os.environ.get("CHESSCOACH_LLM_MODEL") or DEFAULT_MODELS.get(provider, "")
        if provider == "deepseek":
            return cls(provider, model, "https://api.deepseek.com", os.environ.get("DEEPSEEK_API_KEY"))
        if provider == "anthropic":
            return cls(provider, model, "https://api.anthropic.com", os.environ.get("ANTHROPIC_API_KEY"))
        if provider == "ollama":
            return cls(provider, model, os.environ.get("OLLAMA_HOST", "http://localhost:11434"), None)
        raise ValueError(f"fournisseur LLM inconnu : {provider}")


def _post(url: str, headers: dict[str, str], payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def chat_factory(cfg: LLMConfig | None = None) -> Chat:
    """Retourne une fonction ``messages -> texte`` pour le fournisseur configuré."""
    cfg = cfg or LLMConfig.from_env()

    def openai_compatible(messages: list[Message]) -> str:
        if cfg.provider == "deepseek" and not cfg.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY manquante")
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        data = _post(
            f"{cfg.base_url}/v1/chat/completions",
            headers,
            {"model": cfg.model, "messages": messages, "temperature": cfg.temperature, "max_tokens": cfg.max_tokens},
        )
        return data["choices"][0]["message"]["content"]

    def anthropic(messages: list[Message]) -> str:
        if not cfg.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY manquante")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        data = _post(
            f"{cfg.base_url}/v1/messages",
            {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
            {
                "model": cfg.model,
                "system": system,
                "messages": rest,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
            },
        )
        return "".join(block.get("text", "") for block in data["content"])

    return anthropic if cfg.provider == "anthropic" else openai_compatible
