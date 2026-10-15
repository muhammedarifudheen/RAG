from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
    log_level: str = "INFO"

    # Where repositories are cloned. Defaults to the OS temp dir (/tmp on Linux).
    clone_dir: Path | None = None
    # Only needed for private repositories.
    github_token: str | None = None

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Memory while embedding grows with this: about 18 MB per text in a batch.
    embedding_batch_size: int = 16
    # Larger files are almost always generated or minified.
    max_file_bytes: int = 1_000_000


settings = Settings()
