
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/amr_prediction_bundle.joblib"
    # с MODEL_NAME модель берётся из реестра MLflow по алиасу, без него - из файла model_path
    model_name: str | None = None
    model_alias: str = "champion"
    mlflow_tracking_uri: str = "http://mlflow.mlops:5000"
    database_url: str | None = None
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "protected_namespaces": ()}

settings = Settings()