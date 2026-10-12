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

    # Unset means the Anthropic SDK resolves credentials itself (environment or profile).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_max_tokens: int = 16000

    # Requests per client IP per minute; 0 disables. /ask has its own, lower limit
    # because every call is billed.
    rate_limit_per_minute: int = 60
    ask_rate_limit_per_minute: int = 10
    ingest_rate_limit_per_minute: int = 5


settings = Settings()
