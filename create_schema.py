from pathlib import Path

from db import run_script

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def main() -> None:
    run_script(str(SCHEMA_PATH))
    print("Sema uspesno kreirana (7 tabela + PostGIS ekstenzija).")


if __name__ == "__main__":
    main()
