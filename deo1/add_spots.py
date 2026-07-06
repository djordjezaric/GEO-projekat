"""
add_spots.py – Dodaje realistican broj parking mjesta po zoni.
Svaka zona dobija 12-15 mjesta sa realnom raspodjelom slobodnih/zauzetih.

Pokretanje: uv run python deo1/add_spots.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import random
from db import get_connection

random.seed(7)

# (zone_id, prefix, base_lon, base_lat, n_spots)
ZONE_CONFIG = [
    (1, "A",  20.4552, 44.8172, 14),
    (2, "B",  20.4693, 44.8016, 13),
    (3, "C",  19.8218, 45.2407, 12),
    (4, "D",  21.8953, 43.3212, 11),
    (5, "E",  19.8634, 45.2516, 10),
]

SPOT_TYPES   = ["standard", "standard", "standard", "elektro", "invalidski", "moto"]
STATUS_POOL  = (
    ["slobodno"] * 7 +   # ~50%
    ["zauzeto"]  * 5 +   # ~35%
    ["rezervisano"] * 1 + # ~7%
    ["van_upotrebe"] * 1  # ~7%
)


def add_spots():
    with get_connection() as conn:
        cur = conn.cursor()

        for zone_id, prefix, base_lon, base_lat, n_total in ZONE_CONFIG:
            # Koliko vec ima mjesta u ovoj zoni
            cur.execute(
                "SELECT MAX(spot_number) FROM parking_spot WHERE zone_id = %s",
                (zone_id,)
            )
            existing_max = cur.fetchone()[0]
            # Izvuci broj iz koda (npr. "A3" -> 3)
            if existing_max:
                try:
                    start = int(existing_max[len(prefix):]) + 1
                except ValueError:
                    start = 10
            else:
                start = 1

            n_to_add = n_total - (start - 1)
            if n_to_add <= 0:
                print(f"Zona {zone_id}: vec ima dovoljno mjesta, preskacemo.")
                continue

            added = 0
            for i in range(start, start + n_to_add):
                spot_number  = f"{prefix}{i}"
                spot_type    = random.choice(SPOT_TYPES)
                is_covered   = random.random() < 0.4
                status       = random.choice(STATUS_POOL)
                # Blagi GPS offset (±0.0002° ≈ ±18 m)
                lon = base_lon + random.uniform(-0.0002, 0.0002)
                lat = base_lat + random.uniform(-0.0002, 0.0002)

                cur.execute(
                    """
                    INSERT INTO parking_spot
                        (zone_id, spot_number, spot_type, is_covered, status, location)
                    VALUES (%s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    ON CONFLICT (zone_id, spot_number) DO NOTHING
                    """,
                    (zone_id, spot_number, spot_type, is_covered, status, lon, lat),
                )
                added += 1

            conn.commit()
            cur.execute(
                "SELECT status, COUNT(*) FROM parking_spot WHERE zone_id = %s GROUP BY status",
                (zone_id,)
            )
            stats = dict(cur.fetchall())
            slobodna = stats.get("slobodno", 0)
            print(f"Zona {zone_id}: dodato {added} mjesta | slobodnih: {slobodna}")


if __name__ == "__main__":
    add_spots()
    print("\nGotovo. Osvjezite geo_app.py (F5 u browseru).")
