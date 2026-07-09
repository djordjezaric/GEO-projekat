"""
add_zones.py – Dodaje realisticne parking zone za Beograd (12), Novi Sad (7) i Nis (5).
Svaka zona dobija 10-15 mjesta sa realnom raspodjelom slobodnih/zauzetih.

Pokretanje: uv run python deo1/add_zones.py
"""

import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_connection

random.seed(42)

# Nove zone koje dodajemo (postojece su vec u bazi)
NEW_ZONES = [
    # --- Beograd (10 novih, vec ima Zeleni Venac i Slavija) ---
    ("Kalemegdan",          "Cara Dusana 3",               "Beograd", 90,  85.00, False, 20.4519, 44.8234),
    ("Terazije",            "Terazije 12",                 "Beograd", 110, 90.00, True,  20.4617, 44.8154),
    ("Vukov Spomenik",      "Bulevar kralja Aleksandra 86","Beograd", 75,  75.00, False, 20.4767, 44.8069),
    ("Novi Beograd Blok 44","Jurija Gagarina 14",          "Beograd", 200, 65.00, True,  20.4151, 44.8088),
    ("Zemun Centar",        "Glavna 28",                   "Beograd", 60,  70.00, False, 20.4098, 44.8404),
    ("Autokomanda",         "Vojvode Stepe 60",            "Beograd", 80,  70.00, False, 20.4817, 44.7925),
    ("Dorcol",              "Cara Dusana 45",              "Beograd", 55,  80.00, False, 20.4648, 44.8215),
    ("Savski Venac",        "Nemanjina 22",                "Beograd", 95,  85.00, True,  20.4511, 44.8034),
    ("Banjica",             "Paunova 4",                   "Beograd", 70,  60.00, False, 20.4834, 44.7734),
    ("Vozdovac",            "Krusevacka 10",               "Beograd", 65,  60.00, False, 20.4939, 44.7661),

    # --- Novi Sad (5 novih, vec ima Liman i Petrovaradin) ---
    ("Centar Novi Sad",     "Bulevar Mihajla Pupina 3",    "Novi Sad", 100, 70.00, True,  19.8451, 45.2551),
    ("Futoski Park",        "Futoski put 44",              "Novi Sad", 80,  55.00, False, 19.8317, 45.2502),
    ("Detelinara",          "Sajmiste 15",                 "Novi Sad", 60,  50.00, False, 19.8482, 45.2672),
    ("Sajam Novi Sad",      "Hajduk Veljkova 11",          "Novi Sad", 150, 60.00, True,  19.8363, 45.2621),
    ("Novo Naselje",        "Jovana Ducica 18",            "Novi Sad", 70,  50.00, False, 19.8681, 45.2734),

    # --- Nis (4 nove, vec ima Centar) ---
    ("Medijana",            "Bulevar Nemanjica 100",       "Nis",  65,  45.00, False, 21.9123, 43.3178),
    ("Cair",                "Vojvode Tankosica 5",         "Nis",  50,  40.00, False, 21.8912, 43.3289),
    ("Pantelej",            "Aleksandra Medvedeva 22",     "Nis",  45,  40.00, False, 21.9234, 43.3356),
    ("Niska Banja",         "Bulevar Nemanjica 220",       "Nis",  35,  35.00, False, 22.0123, 43.2978),
]

SPOT_TYPES  = ["standard"] * 6 + ["elektro"] * 2 + ["invalidski"] * 1 + ["moto"] * 1
STATUS_POOL = ["slobodno"] * 6 + ["zauzeto"] * 4 + ["rezervisano"] * 1

def add_zones():
    with get_connection() as conn:
        cur = conn.cursor()

        # Provjeri koje zone vec postoje
        cur.execute("SELECT name FROM parking_zone")
        existing = {r[0] for r in cur.fetchall()}

        zone_ids = {}
        added_zones = 0
        for (name, address, city, capacity, rate, covered, lon, lat) in NEW_ZONES:
            if name in existing:
                print(f"Preskacemo '{name}' (vec postoji).")
                cur.execute("SELECT zone_id FROM parking_zone WHERE name = %s", (name,))
                zone_ids[name] = cur.fetchone()[0]
                continue

            cur.execute(
                """
                INSERT INTO parking_zone
                    (name, address, city, total_capacity, hourly_rate, has_covered_spots)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING zone_id
                """,
                (name, address, city, capacity, rate, covered),
            )
            zid = cur.fetchone()[0]
            zone_ids[name] = zid
            added_zones += 1

        conn.commit()
        print(f"\nDodato {added_zones} novih zona.\n")

        # Dodaj mjesta za svaku zonu
        for (name, _, city, capacity, _, _, base_lon, base_lat) in NEW_ZONES:
            zid = zone_ids.get(name)
            if zid is None:
                continue

            # Provjeri koliko mjesta vec ima
            cur.execute(
                "SELECT COUNT(*) FROM parking_spot WHERE zone_id = %s", (zid,)
            )
            existing_count = cur.fetchone()[0]
            if existing_count >= 10:
                print(f"'{name}': vec ima {existing_count} mjesta, preskacemo.")
                continue

            # Odredi prefix od prvog slova grada + zadnja 2 slova zone
            prefix = (city[0] + name.replace(" ", "")[:2]).upper()
            n_spots = random.randint(10, 15)

            for i in range(1, n_spots + 1):
                spot_number = f"{prefix}{i:02d}"
                spot_type   = random.choice(SPOT_TYPES)
                is_covered  = random.random() < 0.35
                status      = random.choice(STATUS_POOL)
                lon = base_lon + random.uniform(-0.0003, 0.0003)
                lat = base_lat + random.uniform(-0.0003, 0.0003)

                cur.execute(
                    """
                    INSERT INTO parking_spot
                        (zone_id, spot_number, spot_type, is_covered, status, location)
                    VALUES (%s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    ON CONFLICT (zone_id, spot_number) DO NOTHING
                    """,
                    (zid, spot_number, spot_type, is_covered, status, lon, lat),
                )

            conn.commit()

            cur.execute(
                """SELECT status, COUNT(*) FROM parking_spot
                   WHERE zone_id = %s GROUP BY status""",
                (zid,),
            )
            stats    = dict(cur.fetchall())
            slobodna = stats.get("slobodno", 0)
            zauzeta  = stats.get("zauzeto",  0)
            print(f"  [{city}] {name}: {n_spots} mjesta | slobodnih: {slobodna} | zauzetih: {zauzeta}")

        # Finalni pregled po gradu
        print("\n=== Finalni pregled po gradu ===")
        cur.execute(
            """
            SELECT z.city, COUNT(DISTINCT z.zone_id) AS zone_count,
                   COUNT(s.spot_id) AS spots,
                   SUM(CASE WHEN s.status='slobodno' THEN 1 ELSE 0 END) AS slobodna
            FROM parking_zone z
            LEFT JOIN parking_spot s ON s.zone_id = z.zone_id
            GROUP BY z.city ORDER BY z.city
            """
        )
        print(f"{'Grad':<12} {'Zone':>6} {'Mjesta':>8} {'Slobodna':>10}")
        print("-" * 40)
        for row in cur.fetchall():
            print(f"{row[0]:<12} {row[1]:>6} {row[2]:>8} {row[3]:>10}")


if __name__ == "__main__":
    add_zones()
    print("\nGotovo. Restartujte geo_app.py.")
