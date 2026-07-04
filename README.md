# Deo 1 – Python SQL: Pametni sistem za upravljanje parking mestima

Relaciona (PostgreSQL/PostGIS) baza i Python skripte za projektni zadatak
"Pametni sistem za upravljanje parking mestima".

## Sema baze

7 tabela sa primarnim i stranim kljucevima (`schema.sql`):

- `parking_zone` – parking zone (kapacitet, cena po satu, grad)
- `parking_spot` – konkretna parking mesta unutar zone (FK -> `parking_zone`), sa geo-lokacijom (PostGIS `geography`) pripremljenom za Deo 2
- `driver` – vozaci
- `vehicle` – vozila (FK -> `driver`)
- `parking_session` – sesije parkiranja, dolazak/odlazak (FK -> `parking_spot`, `vehicle`)
- `payment` – placanja (FK -> `parking_session`)
- `sensor` – senzori zauzetosti po mestu (FK -> `parking_spot`)

## Pokretanje

```bash
cd parking
uv sync
uv run main.py
```

`main.py` redom: kreira semu (`create_schema.py`), unosi pocetne podatke
(`seed_data.py`, >= 5 redova po tabeli), ucitava sve tabele u pandas
DataFrame-ove (`dataframes.py`), demonstrira CRUD operacije (`crud.py`) i
izvrsava 8 upita sa JOIN-om i WHERE filterima (`queries.py`).

Pojedinacni delovi se mogu pokretati i zasebno, npr:

```bash
uv run create_schema.py
uv run seed_data.py
uv run crud.py
uv run queries.py
uv run dataframes.py
```

## Konfiguracija

Parametri konekcije se citaju iz `.env` (`DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`).
