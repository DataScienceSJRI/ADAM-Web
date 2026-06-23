from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ads_base_url: str = "https://datatools.sjri.res.in/ADS"
    ads_username: str = "test55@example.com"
    ads_password: str = "test12"

    vlm_backend: Literal["openai", "ollama"] = "ollama"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    ollama_host: str = "http://10.60.23.101:11434"
    ollama_model: str = "gemma4:26b"


def get_settings() -> Settings:
    return Settings()
