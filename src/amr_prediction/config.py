
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/amr_prediction_bundle.joblib"
    database_url: str | None = None
    log_level: str = "INFO"

    model_config = {"env_file": ".env"}

settings = Settings()