"""The OpenAI-compatible model services, and finding which are configured.

Each is used once its key is set. Pollinations needs no key. OpenRouter's free
models change often, so "auto" reads them from its public catalogue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2

logger = logging.getLogger("atlas.api.assistant")


@dataclass(frozen=True)
class Service:
    name: str
    label: str
    # The chat-completions base URL; may contain {account} (Cloudflare).
    base_url: str
    key_setting: str | None  # None: no key needed
    models_setting: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    account_setting: str | None = None


SERVICES: tuple[Service, ...] = (
    Service("groq", "Groq", "https://api.groq.com/openai/v1", "groq_api_key", "groq_models"),
    Service(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "openrouter_api_key",
        "openrouter_models",
        extra_headers={"X-Title": "Atlas"},
    ),
    Service(
        "deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek_api_key", "deepseek_models"
    ),
    Service("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral_api_key", "mistral_models"),
    Service(
        "cerebras", "Cerebras", "https://api.cerebras.ai/v1", "cerebras_api_key", "cerebras_models"
    ),
    Service(
        "github",
        "GitHub Models",
        "https://models.github.ai/inference",
        "github_models_token",
        "github_models_models",
    ),
    Service(
        "cloudflare",
        "Cloudflare",
        "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
        "cloudflare_api_token",
        "cloudflare_models",
        account_setting="cloudflare_account_id",
    ),
    Service(
        "huggingface",
        "Hugging Face",
        "https://router.huggingface.co/v1",
        "huggingface_api_key",
        "huggingface_models",
    ),
    Service(
        "sambanova",
        "SambaNova",
        "https://api.sambanova.ai/v1",
        "sambanova_api_key",
        "sambanova_models",
    ),
    Service(
        "nvidia", "NVIDIA", "https://integrate.api.nvidia.com/v1", "nvidia_api_key", "nvidia_models"
    ),
    Service(
        "cohere",
        "Cohere",
        "https://api.cohere.ai/compatibility/v1",
        "cohere_api_key",
        "cohere_models",
    ),
    Service(
        "together",
        "Together",
        "https://api.together.xyz/v1",
        "together_api_key",
        "together_models",
    ),
    Service(
        "pollinations",
        "Pollinations",
        "https://text.pollinations.ai/openai",
        None,
        "pollinations_text_models",
    ),
)

OPENROUTER_CATALOGUE = "https://openrouter.ai/api/v1/models"
# Free models that are no use as a general assistant.
_SKIP = ("safety", "guard", "embed", "tts", "whisper", "moderation")


def openrouter_free_models(client: httpx2.Client, limit: int = 12) -> list[str]:
    """The free chat models OpenRouter lists now, largest context first."""
    try:
        response = client.get(OPENROUTER_CATALOGUE, timeout=15.0)
        response.raise_for_status()
        models = response.json().get("data", [])
    except (httpx2.HTTPError, ValueError) as error:
        logger.warning("OpenRouter's model list could not be read: %s", error)
        return []
    free = [
        m
        for m in models
        if str(m.get("id", "")).endswith(":free")
        and "text" in (m.get("architecture") or {}).get("output_modalities", ["text"])
        and not any(word in m["id"] for word in _SKIP)
    ]
    free.sort(key=lambda m: -(m.get("context_length") or 0))
    return [m["id"] for m in free[:limit]]


def configured(
    get: Callable[[str], object], models_of: Callable[[str], list[str]]
) -> list[tuple[Service, str | None, str, list[str]]]:
    """(service, key, base URL, models) for each service that can be used.

    `get` reads a setting; `models_of` turns a models setting into a list.
    """
    usable = []
    for service in SERVICES:
        key = get(service.key_setting) if service.key_setting else None
        if service.key_setting and not key:
            continue
        if service.name == "pollinations" and not get("pollinations_text"):
            continue
        base = service.base_url
        if service.account_setting:
            account = get(service.account_setting)
            if not account:
                continue
            base = base.format(account=account)
        models = models_of(service.models_setting)
        if models:
            usable.append((service, key if isinstance(key, str) else None, base, models))
    return usable
