"""
reset_spots.py – Briše sva parking mjesta i ponovo ih sije sa realističnim brojevima.

Kategorije:
  velika  zona: 60-70 mjesta
  srednja zona: 40-50 mjesta
  mala    zona: 18-25 mjesta

Popunjenost: nasumična po zoni (20-80% slobodnih).

Pokretanje: uv run python deo1/reset_spots.py
"""

import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_connection

random.seed(99)

# zone_id -> (velicina, base_lon, base_lat)
# velicina: "L" = velika (60-70), "M" = srednja (40-50), "S" = mala (18-25)
ZONE_CONFIG = {
    # Beograd
    1:  ("L", 20.4552, 44.8172),  # Zeleni Venac
    2:  ("L", 20.4693, 44.8016),  # Slavija
    6:  ("L", 20.4519, 44.8234),  # Kalemegdan
    7:  ("L", 20.4617, 44.8154),  # Terazije
    8:  ("M", 20.4767, 44.8069),  # Vukov Spomenik
    9:  ("L", 20.4151, 44.8088),  # Novi Beograd Blok 44
    10: ("M", 20.4098, 44.8404),  # Zemun Centar
    11: ("M", 20.4817, 44.7925),  # Autokomanda
    12: ("M", 20.4648, 44.8215),  # Dorcol
    13: ("L", 20.4511, 44.8034),  # Savski Venac
    14: ("M", 20.4834, 44.7734),  # Banjica
    15: ("M", 20.4939, 44.7661),  # Vozdovac
    # Novi Sad
    3:  ("M", 19.8218, 45.2407),  # Liman
    5:  ("S", 19.8634, 45.2516),  # Petrovaradin
    16: ("L", 19.8451, 45.2551),  # Centar Novi Sad
    17: ("M", 19.8317, 45.2502),  # Futoski Park
    18: ("M", 19.8482, 45.2672),  # Detelinara
    19: ("L", 19.8363, 45.2621),  # Sajam Novi Sad
    20: ("S", 19.8681, 45.2734),  # Novo Naselje
    # Nis
    4:  ("L", 21.8953, 43.3212),  # Centar
    21: ("M", 21.9123, 43.3178),  # Medijana
    22: ("M", 21.8912, 43.3289),  # Cair
    23: ("S", 21.9234, 43.3356),  # Pantelej
    24: ("S", 22.0123, 43.2978),  # Niska Banja
}

SIZE_RANGE = {
    "L": (60, 70),
    "M": (40, 50),
    "S": (18, 25),
}

SPOT_TYPES = (
    ["standard"] * 12 +
    ["elektro"]  * 3  +
    ["invalidski"]* 2 +
    ["moto"]      * 1
)

def spot_prefix(zone_id: int, name: str) -> str:
    clean = name.replace(" ", "").upper()
    return clean[:3]


def reset_spots():
    with get_connection() as conn:
        cur = conn.cursor()

        # Brisanje svih mjesta (CASCADE brise i sesije/senzore koji ovise o njima)
        cur.execute("DELETE FROM parking_spot")
        conn.commit()
        print("Sva parking mjesta obrisana.")

        cur.execute("SELECT zone_id, name FROM parking_zone ORDER BY zone_id")
        zones = cur.fetchall()

        totals = {"L": 0, "M": 0, "S": 0}

        for (zone_id, name) in zones:
            if zone_id not in ZONE_CONFIG:
                print(f"  SKIP zone_id={zone_id} ({name}) – nije u konfiguraciji")
                continue

            size, base_lon, base_lat = ZONE_CONFIG[zone_id]
            lo, hi   = SIZE_RANGE[size]
            n_spots  = random.randint(lo, hi)

            # Nasumicna popunjenost 20-80% slobodnih
            pct_free = random.uniform(0.20, 0.80)
            n_free   = round(n_spots * pct_free)
            statuses = (
                ["slobodno"] * n_free +
                ["zauzeto"]  * (n_spots - n_free)
            )
            random.shuffle(statuses)

            prefix = spot_prefix(zone_id, name)
            spread = 0.0008 if size == "L" else (0.0005 if size == "M" else 0.0003)

            for i, status in enumerate(statuses, 1):
                spot_number = f"{prefix}{i:03d}"
                spot_type   = random.choice(SPOT_TYPES)
                is_covered  = random.random() < 0.30
                lon = base_lon + random.uniform(-spread, spread)
                lat = base_lat + random.uniform(-spread, spread)

                cur.execute(
                    """
                    INSERT INTO parking_spot
                        (zone_id, spot_number, spot_type, is_covered, status, location)
                    VALUES (%s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    """,
                    (zone_id, spot_number, spot_type, is_covered, status, lon, lat),
                )

            conn.commit()
            totals[size] += n_spots
            tag = {"L": "velika", "M": "srednja", "S": "mala"}[size]
            print(f"  [{tag:>7}] {name:<25} {n_spots:>3} mjesta | slobodnih: {n_free:>2} ({pct_free*100:.0f}%)")

        # Finalni pregled
        print("\n=== Pregled po gradu ===")
        cur.execute("""
            SELECT z.city,
                   COUNT(DISTINCT z.zone_id)  AS zone_cnt,
                   COUNT(s.spot_id)           AS ukupno_mjesta,
                   SUM(CASE WHEN s.status='slobodno' THEN 1 ELSE 0 END) AS slobodna
            FROM parking_zone z
            LEFT JOIN parking_spot s ON s.zone_id = z.zone_id
            GROUP BY z.city ORDER BY z.city
        """)
        print(f"{'Grad':<12} {'Zone':>5} {'Mjesta':>8} {'Slobodna':>10}")
        print("-" * 38)
        for row in cur.fetchall():
            print(f"{row[0]:<12} {row[1]:>5} {row[2]:>8} {row[3]:>10}")

        print(f"\nVelike zone (L): {totals['L']} mjesta ukupno")
        print(f"Srednje zone (M): {totals['M']} mjesta ukupno")
        print(f"Male zone   (S): {totals['S']} mjesta ukupno")


if __name__ == "__main__":
    reset_spots()
    print("\nGotovo. Restartujte geo_app.py.")
