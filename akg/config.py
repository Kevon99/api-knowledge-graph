from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"

    pg_user: str = "akg"
    pg_password: str = "akg_dev_password"
    pg_db: str = "akg"
    pg_host: str = "localhost"
    pg_port: int = 55432

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_dev_password"

    redis_url: str = "redis://localhost:6379/0"

    akg_secret: str = "change-me-in-prod"


settings = Settings()
