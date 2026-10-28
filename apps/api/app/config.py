from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    # Must match the model the worker embedded the symbols with.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Longest snippet returned for one symbol, and sent to Claude, in lines.
    snippet_max_lines: int = 80

    # Which model provider answers /ask.
    llm_provider: Literal["anthropic", "gemini"] = "anthropic"

    gemini_api_key: str | None = None
    # Tried in order; the next is used when one is overloaded or over quota.
    gemini_models: str = "gemini-flash-latest,gemini-3.5-flash,gemini-flash-lite-latest"
    gemini_max_tokens: int = 16000

    # Unset means the Anthropic SDK resolves credentials itself (environment or profile).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_max_tokens: int = 16000

    # --- The assistant: the chat that answers anything (see app/assistant) ---------
    # Every service below is used once its key is set; all have free tiers. Model
    # lists are comma-separated and tried in order; the router puts coding models
    # first for code and reasoning models for reasoning.
    groq_api_key: str | None = None  # console.groq.com/keys
    groq_models: str = "openai/gpt-oss-120b,openai/gpt-oss-20b"
    openrouter_api_key: str | None = None  # openrouter.ai/keys
    # "auto": every free model in OpenRouter's public catalogue (it changes often).
    openrouter_models: str = "auto"
    mistral_api_key: str | None = None  # console.mistral.ai/api-keys
    mistral_models: str = "mistral-large-latest,mistral-medium-latest,codestral-latest"
    cerebras_api_key: str | None = None  # cloud.cerebras.ai
    cerebras_models: str = "gpt-oss-120b,llama-3.3-70b,qwen-3-32b"
    # A GitHub token with the "Models" permission (github.com/settings/tokens).
    github_models_token: str | None = None
    github_models_models: str = (
        "openai/gpt-4.1,openai/gpt-4.1-mini,meta/Llama-3.3-70B-Instruct,deepseek/DeepSeek-V3-0324"
    )
    cloudflare_account_id: str | None = None  # dash.cloudflare.com → Workers AI
    cloudflare_api_token: str | None = None
    cloudflare_models: str = (
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast,@cf/qwen/qwq-32b,"
        "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b"
    )
    huggingface_api_key: str | None = None  # huggingface.co/settings/tokens
    huggingface_models: str = (
        "meta-llama/Llama-3.3-70B-Instruct,Qwen/Qwen2.5-72B-Instruct,deepseek-ai/DeepSeek-V3-0324"
    )
    sambanova_api_key: str | None = None  # cloud.sambanova.ai
    sambanova_models: str = "DeepSeek-V3.2,gpt-oss-120b,Meta-Llama-3.3-70B-Instruct,MiniMax-M3"
    deepseek_api_key: str | None = None  # platform.deepseek.com (paid, very cheap)
    deepseek_models: str = "deepseek-chat,deepseek-reasoner"
    nvidia_api_key: str | None = None  # build.nvidia.com
    nvidia_models: str = (
        "nvidia/nemotron-3.5-super-vl-120b-a12b,nvidia/nemotron-3-ultra-550b-a55b,"
        "minimaxai/minimax-m3.1-flash,stepfun-ai/step-5-preview,nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    cohere_api_key: str | None = None  # dashboard.cohere.com/api-keys
    cohere_models: str = "command-a-03-2025"
    together_api_key: str | None = None  # api.together.ai
    together_models: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"
    # Free without any key.
    pollinations_text: bool = True
    pollinations_text_models: str = "openai-fast"
    # AI Horde: volunteers' machines; anonymous use ("0000000000") is free but slow.
    horde_enabled: bool = True
    horde_api_key: str = "0000000000"
    horde_text_models: str = "google/gemma-4-31b"
    # One picture agent per model, drawn in parallel. Anonymous requests wait behind
    # everyone with kudos; a free key from https://aihorde.net/register moves them up.
    horde_image_models: str = "AlbedoBase XL (SDXL),Juggernaut XL,Deliberate"

    # How many of one provider's models to try before moving to the next provider.
    assistant_models_per_provider: int = 2
    # "Best model + fallbacks" order, strongest first.
    assistant_best_order: str = (
        "claude,gemini,deepseek,openrouter,github,mistral,cerebras,groq,sambanova,nvidia,"
        "cohere,huggingface,cloudflare,together,pollinations,horde"
    )
    # The council: this many agents answer each question in parallel and one model
    # merges their best points. 1 turns the council off (one model answers).
    assistant_council_size: int = 12
    # Once two agents have answered, wait this many more seconds for the rest.
    assistant_council_grace: float = 4.0
    # And never wait longer than this for the panel (the first answer is waited for).
    assistant_council_max_wait: float = 35.0
    # Services that merge the drafts first when one of their models answered: the quickest,
    # since the merged answer is what the user waits for.
    assistant_fast_mergers: str = "groq,cerebras"
    # After those, the agents that answered merge in order of how quickly they wrote
    # their own draft.
    assistant_merge_by_speed: bool = True
    # At most this many drafts go to the merge (the best-suited agents' first).
    assistant_merge_drafts: int = 5
    # Search the web before every answer (except small talk) and give every agent the
    # results, so answers carry today's facts. Gemini also searches Google itself (its
    # search quota is separate; refused, it answers without).
    assistant_web_search: bool = True
    # Google News and Wikipedia need no key; Tavily (1,000 free searches a month) and
    # Brave Search add whole-web results when their key is set.
    web_news: bool = True
    web_wikipedia: bool = True
    tavily_api_key: str | None = None  # https://app.tavily.com
    brave_api_key: str | None = None  # https://brave.com/search/api
    web_max_wait: float = 5.0
    # Knowledge-base excerpts less similar than this are not shown to the model.
    assistant_min_score: float = 0.3
    assistant_max_tokens: int = 8000

    # Pictures: a gallery from several services at once. Pollinations needs no key
    # ({prompt} and {seed} are filled in); Cloudflare and Hugging Face use their keys
    # above; AI Horde is free but often slow.
    image_url_template: str = (
        "https://image.pollinations.ai/prompt/{prompt}"
        "?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    )
    image_gallery_size: int = 8
    image_max_wait: float = 90.0
    cloudflare_image_model: str = "@cf/black-forest-labs/flux-1-schnell"
    huggingface_image_model: str = "black-forest-labs/FLUX.1-schnell"
    # Together's free FLUX endpoint, used once TOGETHER_API_KEY is set.
    together_image_model: str = "black-forest-labs/FLUX.1-schnell-Free"
    # Gemini's image model has no free quota: on only for a key with billing.
    gemini_images: bool = False
    gemini_image_model: str = "gemini-2.5-flash-image"

    # When set, adding and removing sources needs `Authorization: Bearer <token>`;
    # searching and asking stay open. Unset, everything is open (local use).
    admin_token: str | None = None

    # Requests per client IP per minute; 0 disables. /ask has its own, lower limit
    # because every call is billed.
    rate_limit_per_minute: int = 60
    ask_rate_limit_per_minute: int = 30
    ingest_rate_limit_per_minute: int = 5


settings = Settings()
