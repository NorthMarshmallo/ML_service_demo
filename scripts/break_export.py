"""Испорченная выгрузка для проверки шага validate: источник переименовал класс multidrug в multi-drug.

  uv run python scripts/break_export.py

Перезаписывает datasets/dataset.csv, ни одной ошибки при этом не возникает: файл читается, колонки и типы
те же, строк столько же. Чистка молча отбросит строки незнакомого класса, ловит это только доля класса
в схеме выгрузки (share_multidrug).
Вернуть как было: git checkout -- datasets/dataset.csv.dvc && uv run dvc checkout
"""
from pathlib import Path

import pandas as pd

PATH = Path("datasets/dataset.csv")
df = pd.read_csv(PATH, sep=";")
df["antibiotic_class"] = df["antibiotic_class"].replace("multidrug", "multi-drug")
df.to_csv(PATH, sep=";", index=False)
print(f"{PATH}: multidrug -> multi-drug в {(df['antibiotic_class'] == 'multi-drug').sum()} строках из {len(df)}")
