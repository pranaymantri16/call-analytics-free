from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://callanalytics:callanalytics@localhost:5432/callanalytics"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    hf_token: str | None = None
    webhook_secret: str | None = None
    max_upload_mb: int = 200
    audio_dir: str = "/data/audio"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
