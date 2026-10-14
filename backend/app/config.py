from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

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
    erpnext_enabled: bool = False
    erpnext_base_url: str = ""
    erpnext_api_key: SecretStr = SecretStr("")
    erpnext_api_secret: SecretStr = SecretStr("")
    erpnext_analysis_endpoint: str = "/api/method/call_analytics_integration.api.receive_call_analysis"
    erpnext_request_timeout: float = 30
    erpnext_max_retries: int = 5
    erpnext_allow_http: bool = False
    erpnext_admin_token: SecretStr = SecretStr("")
    mobile_enabled: bool = False
    mobile_devices: dict[str, SecretStr] = {}
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
