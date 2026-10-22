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
    # More providers: each one is used once its key is set. All but Claude have
    # free tiers. Model lists are tried in order; the router reorders them per
    # question type (coding models for code, reasoning models for reasoning).
    groq_api_key: str | None = None
    groq_models: str = "openai/gpt-oss-120b,groq/compound,llama-3.3-70b-versatile,qwen/qwen3-32b"
    openrouter_api_key: str | None = None
    openrouter_models: str = (
        "deepseek/deepseek-chat-v3.1:free,deepseek/deepseek-r1-0528:free,"
        "qwen/qwen3-coder:free,meta-llama/llama-3.3-70b-instruct:free"
    )
    mistral_api_key: str | None = None
    mistral_models: str = "mistral-large-latest,mistral-medium-latest,codestral-latest"
    # How many of one provider's models to try before moving to the next provider.
    assistant_models_per_provider: int = 2
    # "Best model + fallbacks" order, strongest first.
    assistant_best_order: str = "claude,gemini,openrouter,mistral,groq"
    # Let models search the web for recent facts: Gemini through Google (its search
    # quota is separate; refused, it answers without), Groq through its compound models.
    assistant_web_search: bool = True
    # Knowledge-base excerpts less similar than this are not shown to the model.
    assistant_min_score: float = 0.3
    assistant_max_tokens: int = 8000
    # Pictures are drawn by Pollinations (free, no key); {prompt} and {seed} are filled in.
    image_url_template: str = (
        "https://image.pollinations.ai/prompt/{prompt}"
        "?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    )

    # When set, adding and removing sources needs `Authorization: Bearer <token>`;
    # searching and asking stay open. Unset, everything is open (local use).
    admin_token: str | None = None

    # Requests per client IP per minute; 0 disables. /ask has its own, lower limit
    # because every call is billed.
    rate_limit_per_minute: int = 60
    ask_rate_limit_per_minute: int = 10
    ingest_rate_limit_per_minute: int = 5


settings = Settings()
