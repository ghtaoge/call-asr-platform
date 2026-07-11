from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Call ASR Platform"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/call_asr.sqlite3")
    sensitive_words_path: Path = Path("data/sensitive_words.sample.json")
    asr_provider: str = "mock"
    asr_model_size: str = "base"
    preferred_device: str = "auto"
    target_language: str = "en"

    model_config = SettingsConfigDict(env_prefix="CALL_ASR_", env_file=".env", extra="ignore")

    @property
    def resolved_device(self) -> str:
        if self.preferred_device != "auto":
            return self.preferred_device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"


def get_settings() -> Settings:
    return Settings()
