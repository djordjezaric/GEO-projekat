"""Deo 1 - Python SQL: kompletna demonstracija.

Redosled: kreiranje seme -> unos podataka -> ucitavanje u DataFrame-ove ->
CRUD demo -> JOIN/WHERE upiti.
"""

from create_schema import main as create_schema
from crud import demo as crud_demo
from dataframes import load_all_dataframes
from queries import run_all_queries
from seed_data import main as seed_data


def main() -> None:
    print("### 1) Kreiranje seme ###")
    create_schema()

    print("\n### 2) Unos pocetnih podataka ###")
    seed_data()

    print("\n### 3) Ucitavanje tabela u pandas DataFrame-ove ###")
    frames = load_all_dataframes()
    for name, df in frames.items():
        print(f"{name}: {len(df)} redova, kolone: {list(df.columns)}")

    print("\n### 4) CRUD operacije ###")
    crud_demo()

    print("\n### 5) JOIN / WHERE upiti ###")
    run_all_queries()


if __name__ == "__main__":
    main()
