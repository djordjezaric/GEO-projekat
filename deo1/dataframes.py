"""Ucitavanje svih tabela u pandas DataFrame-ove."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from db import get_engine

TABLES = [
    "parking_zone",
    "parking_spot",
    "driver",
    "vehicle",
    "parking_session",
    "payment",
    "sensor",
]


def load_all_dataframes() -> dict[str, pd.DataFrame]:
    frames = {}
    engine = get_engine()
    for table in TABLES:
        frames[table] = pd.read_sql(f"SELECT * FROM {table};", engine)
    return frames


def main() -> None:
    frames = load_all_dataframes()
    for name, df in frames.items():
        print(f"\n=== {name} ({len(df)} redova) ===")
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
