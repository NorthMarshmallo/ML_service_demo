"""Обучение модели AMR: чистка данных (amr_prediction.data), обучение, запись в MLflow, регистрация и гейт.

  MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.train

Новая версия всегда получает алиас challenger. Алиас champion она получает, только если
macro F1 на отложенной выборке лучше, чем у текущего champion (или champion ещё нет).
"""
import hashlib
import json
import os

import mlflow
import numpy as np
import pandas as pd
import sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import ConfusionMatrixDisplay, accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline

from amr_prediction.data import CLASSES, DATA_PATH, FEATURES, TARGET, clean

MODEL_NAME = os.getenv("MODEL_NAME", "amr_prediction")
EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "amr_prediction")
HIDDEN_DIM = int(os.getenv("HIDDEN_DIM", "256"))
MIN_GAIN = float(os.getenv("GATE_MIN_GAIN", "0.005"))
SEED = 42
NUM_EPOCHS = 20
SKOPS_TRUSTED = ["sklearn.neural_network._stochastic_optimizers.AdamOptimizer"]


def upsample(x, y: np.ndarray) -> tuple:
    # редкие классы дополняем повторами до размера самого частого
    rng = np.random.default_rng(SEED)
    classes, counts = np.unique(y, return_counts=True)
    idx = np.concatenate([
        np.concatenate([cls_idx, rng.choice(cls_idx, size=counts.max() - len(cls_idx), replace=True)])
        for cls_idx in (np.flatnonzero(y == cls) for cls in classes)
    ])
    return x[idx], y[idx]


def build_model(hidden_dim: int) -> MLPClassifier:
    return MLPClassifier(hidden_layer_sizes=(hidden_dim, hidden_dim // 8), activation="relu", solver="adam",
                         learning_rate_init=0.001, batch_size=32, shuffle=True, max_iter=NUM_EPOCHS,
                         random_state=SEED)


def train_pipeline(x_train: pd.DataFrame, y_train: pd.Series, hidden_dim: int) -> Pipeline:
    # TF-IDF учится на исходном train, upsampling только для модели
    tfidf = TfidfVectorizer(analyzer="char").fit(x_train["sequence"])
    x_up, y_up = upsample(tfidf.transform(x_train["sequence"]), y_train.to_numpy())
    return Pipeline([("tfidf", tfidf), ("model", build_model(hidden_dim).fit(x_up, y_up))])


def confusion_matrix_figure(y_true, y_pred):
    disp = ConfusionMatrixDisplay.from_predictions(y_true, y_pred, labels=CLASSES, xticks_rotation=45, colorbar=False)
    for label in disp.ax_.get_xticklabels():
        label.set(ha="right", rotation_mode="anchor")
    disp.figure_.set_size_inches(9, 8)
    disp.figure_.tight_layout()
    return disp.figure_


def champion_f1(client: MlflowClient) -> tuple[str | None, float | None]:
    try:
        mv = client.get_model_version_by_alias(MODEL_NAME, "champion")
    except MlflowException:
        return None, None
    return mv.version, client.get_run(mv.run_id).data.metrics.get("macro_f1")


def promote(client: MlflowClient, version: str, f1: float) -> tuple[str | None, float | None, bool]:
    # challenger всегда на новой версии, champion - только если гейт пропустил
    old_version, old_f1 = champion_f1(client)
    promoted = old_f1 is None or f1 > old_f1 + MIN_GAIN
    client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    if promoted:
        client.set_registered_model_alias(MODEL_NAME, "champion", version)
    return old_version, old_f1, promoted


def main() -> dict:
    df, dropped = clean(DATA_PATH)
    x_train, x_test, y_train, y_test = train_test_split(
        df[FEATURES], df[TARGET], test_size=0.2, stratify=df[TARGET], random_state=SEED)

    pipeline = train_pipeline(x_train, y_train, HIDDEN_DIM)
    y_pred = pipeline.predict(x_test["sequence"])
    f1 = float(f1_score(y_test, y_pred, average="macro"))

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run() as run:
        metadata = {"features": FEATURES, "classes": list(pipeline.classes_), "n_train": len(x_train),
                    "data_rows": len(df), "sklearn": sklearn.__version__}
        mlflow.log_params({"hidden_dim": HIDDEN_DIM, "epochs": NUM_EPOCHS, "model": "MLPClassifier", "seed": SEED,
                           "data": str(DATA_PATH), "data_md5": hashlib.md5(DATA_PATH.read_bytes()).hexdigest()})
        mlflow.log_metrics({"macro_f1": f1, "accuracy": float(accuracy_score(y_test, y_pred)), **dropped})
        mlflow.log_dict(metadata, "metadata.json")
        mlflow.log_figure(confusion_matrix_figure(y_test, y_pred), "confusion_matrix.png")
        info = mlflow.sklearn.log_model(pipeline, name="model", registered_model_name=MODEL_NAME,
                                        skops_trusted_types=SKOPS_TRUSTED)
        version = info.registered_model_version

    old_version, old_f1, promoted = promote(MlflowClient(), version, f1)
    result = {"run_id": run.info.run_id, "version": version, "macro_f1": round(f1, 4),
              "champion_before": old_version, "champion_f1_before": old_f1, "promoted": promoted}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
