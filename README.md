# Pametni sistem za upravljanje parking mestima

**Predmet:** Geografski informacioni sistemi  
**Zadatak 7:** Pametni sistem za upravljanje parking mestima  
**Tehnologije:** Python, PostgreSQL 16 + PostGIS 3.6, YOLOv8, Streamlit, GeoPandas, Folium

---

## Struktura projekta

```
GEO projekat/
├── db.py               # Konekcija na bazu (zajednicki za sve delove)
├── .env                # Kredencijali baze (nije na gitu)
├── pyproject.toml      # Zavisnosti projekta
│
├── deo1/               # Deo 1 – Python SQL
│   ├── schema.sql
│   ├── create_schema.py
│   ├── seed_data.py
│   ├── crud.py
│   ├── queries.py
│   ├── dataframes.py
│   └── main.py
│
├── deo2/               # Deo 2 – Python GEO
│   ├── geo_download.py
│   └── geo_app.py
│
└── deo3/               # Deo 3 – Python ML
    ├── schema_ml.sql
    ├── ml_detect.py
    ├── ml_app.py
    └── yolov8n.pt
```

---

## Pocetno podesavanje

### 1. Kreiranje `.env` fajla

Kreirati fajl `.env` u root folderu projekta:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=parking_db
DB_USER=postgres
DB_PASSWORD=postgres
```

### 2. Instalacija zavisnosti

```bash
uv sync
```

---

## Deo 1 – Python SQL (Relaciona baza podataka)

Kreira PostgreSQL/PostGIS semu sa 7 tabela, unosi pocetne podatke,
demonstrira CRUD operacije i izvrsava 8 JOIN upita.

### Baza podataka (7 tabela)

| Tabela | Opis |
|---|---|
| `parking_zone` | Parking zone (kapacitet, cena, grad) |
| `parking_spot` | Konkretna mesta unutar zone + GPS lokacija (PostGIS) |
| `driver` | Vozaci |
| `vehicle` | Vozila (FK → driver) |
| `parking_session` | Sesije parkiranja – dolazak/odlazak |
| `payment` | Placanja po sesiji |
| `sensor` | Senzori zauzetosti po mestu |

### Pokretanje

Sve odjednom (preporuceno):

```bash
uv run python deo1/main.py
```

Redosled koji `main.py` izvrsava:
1. Kreira semu (`create_schema.py` → `schema.sql`)
2. Unosi pocetne podatke u sve tabele (`seed_data.py`, min. 5 redova po tabeli)
3. Ucitava sve tabele u pandas DataFrame-ove (`dataframes.py`)
4. Demonstrira CRUD operacije – insert, update, delete (`crud.py`)
5. Izvrsava 8 JOIN/WHERE upita (`queries.py`)

Zasebno pokretanje pojedinih modula:

```bash
uv run python deo1/create_schema.py   # samo kreira semu
uv run python deo1/seed_data.py       # samo unosi podatke
uv run python deo1/crud.py            # samo CRUD demo
uv run python deo1/queries.py         # samo JOIN upiti
uv run python deo1/dataframes.py      # samo DataFrame prikaz
```

---

## Deo 2 – Python GEO (Geografske karte i prostorne analize)

Interaktivna Streamlit aplikacija sa SHP slojevima iz OpenStreetMap-a,
parking podacima iz PostGIS baze i 5 prostornih analiza.

### Priprema podataka (jednom)

Preuzimanje i sjecanje SHP podataka za Srbiju (~100 MB):

```bash
uv run python deo2/geo_download.py
```

Rezultat se cuva u `data/clipped/` (nije na gitu zbog velicine).

### Pokretanje aplikacije

```bash
uv run streamlit run deo2/geo_app.py
```

Aplikacija se otvara na: **http://localhost:8501**

### Sta aplikacija nudi

- Interaktivna Folium mapa sa ukljucivanjem/iskljucivanjem slojeva
- 6 SHP slojeva: putevi, zgrade, voda, zelenilo, saobracaj, nacin koriscenja
- Parking mjesta iz PostGIS baze (boja i velicina po statusu/tipu)
- Simbologija: promjena boje i velicine markera iz bocznog panela
- 5 prostornih analiza: buffer, isjecanje, sjoin, gustina, rastojanja
- Prikaz GeoDataFrame-ova sa SHP i DB podacima

---

## Deo 3 – Python ML (Detekcija vozila pomocu YOLOv8)

Streamlit aplikacija koja koristi YOLOv8 za detekciju vozila na parking
fotografijama i izracunavanje slobodnih mesta. Rezultati se cuvaju u
PostGIS tabeli `ml_detection`.

### Pokretanje aplikacije

```bash
uv run streamlit run deo3/ml_app.py
```

Aplikacija se otvara na: **http://localhost:8501**

### Napomena o slikama

YOLOv8 je treniran na COCO datasetu (ulicne fotografije).
Aplikacija radi sa slikama snimljenim sa:
- Ulice ili trotoara
- Prozora zgrade (blago poviseno)
- CCTV / parking kamere

**Satelitske i drone slike (odozgo) nisu podrzane** – model nije treniran
na takvim perspektivama.

### Sta aplikacija nudi

| Tab | Sadrzaj |
|---|---|
| Detekcija | Upload slike → YOLOv8 broji vozila → slobodna = kapacitet − vozila → Folium mapa zone |
| Uredivanje atributa | Izmjena statusa, klase vozila, napomene; brisanje zapisa |
| Pregled podataka | Tabela svih detekcija sa filterima, statistike, overview mapa zona |
| Prostorne analize | Buffer, DBSCAN klasterovanje, ML vs DB poredjenje, sjoin_nearest, grafikon gustine |

### Nova PostGIS tabela

`ml_detection` se automatski kreira pri prvom pokretanju aplikacije.
Sadrzi: lokaciju (GEOGRAPHY), status, klasu vozila, pouzdanost, bbox koordinate,
vezu sa parking zonom.

---

## Konfiguracija baze

Sve konekcione parametre citaju iz `.env` fajla:

| Varijabla | Podrazumevana vrijednost |
|---|---|
| `DB_HOST` | localhost |
| `DB_PORT` | 5432 |
| `DB_NAME` | parking_db |
| `DB_USER` | postgres |
| `DB_PASSWORD` | postgres |
