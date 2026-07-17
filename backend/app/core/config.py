from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Call ASR Platform"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/call_asr.sqlite3")
    sensitive_words_path: Path = Path("data/sensitive_words.sample.json")
    asr_provider: str = "paraformer"
    asr_model_size: str = "base"
    preferred_device: str = "auto"
    target_language: str = "en"
    max_audio_bytes: int = 50 * 1024 * 1024
    download_timeout_seconds: float = 30.0
    job_retention_days: int = 7
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "CALL_ASR_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "CALL_ASR_DEEPSEEK_BASE_URL"),
    )
    deepseek_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias=AliasChoices("DEEPSEEK_MODEL", "CALL_ASR_DEEPSEEK_MODEL"),
    )
    deepseek_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("DEEPSEEK_TIMEOUT_SECONDS", "CALL_ASR_DEEPSEEK_TIMEOUT_SECONDS"),
    )
    cosyvoice_worker_url: str = "http://127.0.0.1:18081"
    cosyvoice_worker_token: str | None = None
    cosyvoice_timeout_seconds: float = 180.0
    tts_retention_days: int = 7
    tts_max_reference_bytes: int = 20 * 1024 * 1024

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

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def tts_dir(self) -> Path:
        return self.data_dir / "tts"


def get_settings() -> Settings:
    return Settings()
