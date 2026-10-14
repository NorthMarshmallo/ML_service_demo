"""Данные AMR: чистка выгрузки и проверка очищенного слоя схемами pandera.

  MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.data

Нарушения: в прогоне MLflow тег valid=false и артефакт failure_cases.csv, код выхода 1.
Чистку отсюда же берёт train.py, поэтому validate и train видят один и тот же слой.
"""
import hashlib
import os
import sys
from pathlib import Path

import mlflow
import pandas as pd
import pandera.pandas as pa

DATA_PATH = Path(os.getenv("DATA_PATH", "datasets/dataset.csv"))
EXPERIMENT = os.getenv("MLFLOW_VALIDATE_EXPERIMENT", "amr_prediction_data")

FEATURES = ["sequence"]
TARGET = "antibiotic_class"
# классы, которые предсказывает модель: 7 самых частых в исходном датасете (90% записей)
CLASSES = ["aminoglycoside", "bacitracin", "beta_lactam", "chloramphenicol",
           "macrolide-lincosamide-streptogramin", "multidrug", "polymyxin"]
MIN_LENGTH = 20
MAX_LENGTH = 2000
STANDARD_AA = "RHKDESTNQCGPAILMFWYV"

# средний состав аминокислот очищенного слоя v2 (fbb751c6...), зафиксирован: эталон не должен
# сдвигаться вместе с испорченной выгрузкой
REF_COMPOSITION = {
    "R": 0.047, "H": 0.019, "K": 0.048, "D": 0.046, "E": 0.048, "S": 0.060, "T": 0.057,
    "N": 0.035, "Q": 0.036, "C": 0.008, "G": 0.076, "P": 0.042, "A": 0.099, "I": 0.072,
    "L": 0.111, "M": 0.027, "F": 0.050, "W": 0.017, "Y": 0.029, "V": 0.074,
}
# L1 до среднего состава у белков v2: медиана 0.28, максимум 0.70; у последовательности ДНК около 1.5
MAX_COMPOSITION_L1 = 1.0

# выгрузка целиком: в v2 после чистки 15 154 строки, медиана длины 285
MIN_ROWS = 12_000
MEDIAN_LENGTH = (200, 400)
# доли классов в v2; коридор - в 1.5 раза вниз и вверх от них
CLASS_SHARE = {"beta_lactam": 0.380, "bacitracin": 0.278, "multidrug": 0.084,
               "macrolide-lincosamide-streptogramin": 0.083, "aminoglycoside": 0.082,
               "polymyxin": 0.060, "chloramphenicol": 0.032}
SHARE_FACTOR = 1.5


def composition_l1(seq: str) -> float:
    return sum(abs(seq.count(aa) / len(seq) - share) for aa, share in REF_COMPOSITION.items())


ROWS = pa.DataFrameSchema(
    {
        "sequence": pa.Column(str, [
            pa.Check.str_matches(f"^[{STANDARD_AA}]+$"),
            pa.Check.str_length(MIN_LENGTH, MAX_LENGTH),
            pa.Check(lambda s: s.map(composition_l1) < MAX_COMPOSITION_L1, name="composition_l1"),
        ], unique=True),
        TARGET: pa.Column(str, pa.Check.isin(CLASSES)),
    },
    strict=True,
)


def share_check(cls: str, share: float) -> pa.Check:
    lo, hi = share / SHARE_FACTOR, share * SHARE_FACTOR
    return pa.Check(lambda df: lo <= (df[TARGET] == cls).mean() <= hi, name=f"share_{cls}_{lo:.3f}-{hi:.3f}")


EXPORT = pa.DataFrameSchema(checks=[
    pa.Check(lambda df: len(df) >= MIN_ROWS, name=f"rows_min_{MIN_ROWS}"),
    pa.Check(lambda df: MEDIAN_LENGTH[0] <= df["sequence"].str.len().median() <= MEDIAN_LENGTH[1],
             name=f"median_length_{MEDIAN_LENGTH[0]}-{MEDIAN_LENGTH[1]}"),
    *[share_check(cls, share) for cls, share in CLASS_SHARE.items()],
])


def clean(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path, sep=";")
    missing = set(FEATURES + [TARGET]) - set(df.columns)
    if missing:
        raise ValueError(f"в данных нет колонок: {sorted(missing)}")

    # сколько строк отброшено на каждом фильтре, пишется в MLflow
    dropped = {}
    n = len(df)
    df = df[df[TARGET].isin(CLASSES)]
    dropped["dropped_other_classes"] = n - len(df)
    n = len(df)
    # те же правила, что у входа сервиса: только стандартные аминокислоты и длина от 20
    df = df[df["sequence"].str.fullmatch(f"[{STANDARD_AA}]+") & (df["sequence"].str.len() >= MIN_LENGTH)]
    dropped["dropped_bad_sequence"] = n - len(df)
    n = len(df)
    # только полные дубли: одна последовательность с разными классами остаётся и ловится unique в ROWS
    df = df.drop_duplicates().reset_index(drop=True)
    dropped["dropped_duplicates"] = n - len(df)
    return df, dropped


def validate(df: pd.DataFrame) -> pd.DataFrame:
    failures = []
    for schema in (ROWS, EXPORT):
        try:
            schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as e:
            failures.append(e.failure_cases)
    return pd.concat(failures, ignore_index=True) if failures else pd.DataFrame()


def main() -> int:
    df, dropped = clean(DATA_PATH)
    failures = validate(df)
    valid = failures.empty

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name="validate"):
        mlflow.set_tag("valid", str(valid).lower())
        mlflow.log_params({"data": str(DATA_PATH), "data_md5": hashlib.md5(DATA_PATH.read_bytes()).hexdigest()})
        shares = {f"share_{cls}": float((df[TARGET] == cls).mean()) for cls in CLASSES}
        mlflow.log_metrics({"rows": len(df), "median_length": float(df["sequence"].str.len().median()),
                            "failures": len(failures), **dropped, **shares})
        if not valid:
            mlflow.log_text(failures.to_csv(index=False), "failure_cases.csv")

    print(f"{DATA_PATH}: {len(df)} строк после чистки, нарушений {len(failures)}, valid={str(valid).lower()}")
    if not valid:
        print(failures[["schema_context", "column", "check", "failure_case"]].head(20).to_string())
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
