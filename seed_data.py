"""Rucno (hardkodovano) unosenje pocetnih podataka u sve tabele - najmanje 5 redova po tabeli."""

from db import get_connection

INSERT_ZONES = """
INSERT INTO parking_zone (name, address, city, total_capacity, hourly_rate, has_covered_spots) VALUES
    ('Zeleni Venac', 'Zeleni venac bb', 'Beograd', 120, 80.00, TRUE),
    ('Slavija', 'Bulevar kralja Aleksandra 1', 'Beograd', 80, 70.00, FALSE),
    ('Liman', 'Bulevar oslobodjenja 10', 'Novi Sad', 60, 60.00, TRUE),
    ('Centar', 'Bulevar Nemanjica 45', 'Nis', 50, 50.00, FALSE),
    ('Petrovaradin', 'Podgradje 3', 'Novi Sad', 40, 55.00, TRUE);
"""

INSERT_SPOTS = """
INSERT INTO parking_spot (zone_id, spot_number, spot_type, is_covered, status, location) VALUES
    (1, 'A1', 'standard',    TRUE,  'slobodno',     ST_SetSRID(ST_MakePoint(20.4556, 44.8186), 4326)::geography),
    (1, 'A2', 'elektro',     TRUE,  'slobodno',     ST_SetSRID(ST_MakePoint(20.4559, 44.8188), 4326)::geography),
    (1, 'A3', 'invalidski',  TRUE,  'zauzeto',      ST_SetSRID(ST_MakePoint(20.4562, 44.8190), 4326)::geography),
    (2, 'B1', 'standard',    FALSE, 'zauzeto',      ST_SetSRID(ST_MakePoint(20.4700, 44.8025), 4326)::geography),
    (2, 'B2', 'moto',        FALSE, 'slobodno',     ST_SetSRID(ST_MakePoint(20.4703, 44.8027), 4326)::geography),
    (3, 'C1', 'standard',    TRUE,  'slobodno',     ST_SetSRID(ST_MakePoint(19.8227, 45.2396), 4326)::geography),
    (3, 'C2', 'elektro',     TRUE,  'rezervisano',  ST_SetSRID(ST_MakePoint(19.8230, 45.2398), 4326)::geography),
    (4, 'D1', 'standard',    FALSE, 'slobodno',     ST_SetSRID(ST_MakePoint(21.8958, 43.3209), 4326)::geography),
    (5, 'E1', 'standard',    TRUE,  'van_upotrebe', ST_SetSRID(ST_MakePoint(19.8627, 45.2517), 4326)::geography),
    (5, 'E2', 'invalidski',  TRUE,  'slobodno',     ST_SetSRID(ST_MakePoint(19.8630, 45.2519), 4326)::geography);
"""

INSERT_DRIVERS = """
INSERT INTO driver (first_name, last_name, email, phone, license_number, registration_date) VALUES
    ('Marko',  'Markovic',  'marko.markovic@example.com',  '0641234567', 'SR1234567', '2023-01-15'),
    ('Ana',    'Anic',      'ana.anic@example.com',        '0651112233', 'SR2233445', '2023-03-22'),
    ('Petar',  'Petrovic',  'petar.petrovic@example.com',  '0611234567', 'SR3344556', '2024-02-10'),
    ('Jovana', 'Jovanovic', 'jovana.jovanovic@example.com','0621239876', 'SR4455667', '2024-05-01'),
    ('Nikola', 'Nikolic',   'nikola.nikolic@example.com',  '0631112222', 'SR5566778', '2025-01-19');
"""

INSERT_VEHICLES = """
INSERT INTO vehicle (driver_id, license_plate, make, model, color, vehicle_type) VALUES
    (1, 'BG123AB', 'Skoda',   'Octavia',  'bela',   'automobil'),
    (1, 'BG456CD', 'Renault', 'Clio',     'crvena', 'automobil'),
    (2, 'NS789EF', 'Yamaha',  'MT-07',    'crna',   'motocikl'),
    (3, 'BG321GH', 'Tesla',   'Model 3',  'plava',  'elektricno'),
    (4, 'NI654IJ', 'Fiat',    'Ducato',   'bela',   'kombi'),
    (5, 'NS987KL', 'VW',      'Golf',     'siva',   'automobil');
"""

INSERT_SESSIONS = """
INSERT INTO parking_session (spot_id, vehicle_id, check_in_time, check_out_time, status, total_amount) VALUES
    (1, 1, '2026-07-01 08:00', '2026-07-01 10:30', 'zavrsena', 200.00),
    (4, 3, '2026-07-02 09:15', NULL,                'aktivna',  NULL),
    (6, 4, '2026-07-02 11:00', '2026-07-02 13:00', 'zavrsena', 120.00),
    (2, 2, '2026-07-03 07:45', NULL,                'aktivna',  NULL),
    (8, 5, '2026-06-30 14:00', '2026-06-30 15:00', 'zavrsena', 50.00),
    (7, 6, '2026-07-01 16:00', '2026-07-01 18:00', 'otkazana', NULL);
"""

INSERT_PAYMENTS = """
INSERT INTO payment (session_id, amount, payment_method, payment_status, payment_time) VALUES
    (1, 200.00, 'kartica',    'placeno',     '2026-07-01 10:31'),
    (3, 120.00, 'aplikacija', 'placeno',     '2026-07-02 13:01'),
    (5, 50.00,  'gotovina',   'placeno',     '2026-06-30 15:02'),
    (6, 30.00,  'kartica',    'neuspesno',   '2026-07-01 16:05'),
    (4, 20.00,  'aplikacija', 'na_cekanju',  '2026-07-03 07:46'),
    (2, 15.00,  'kartica',    'na_cekanju',  '2026-07-02 09:16');
"""

INSERT_SENSORS = """
INSERT INTO sensor (spot_id, sensor_type, install_date, battery_level, last_status, last_reading_time) VALUES
    (1, 'ultrazvucni', '2025-06-01', 85, 'slobodno', '2026-07-03 08:00'),
    (2, 'kamera',      '2025-06-01', 60, 'zauzeto',  '2026-07-03 08:00'),
    (4, 'ultrazvucni', '2025-07-15', 40, 'zauzeto',  '2026-07-03 08:00'),
    (6, 'infracrveni', '2025-08-20', 90, 'slobodno', '2026-07-03 08:00'),
    (7, 'kamera',      '2024-11-05', 15, 'zauzeto',  '2026-07-03 08:00'),
    (9, 'ultrazvucni', '2024-09-10', 5,  'nepoznato','2026-07-03 08:00');
"""

STATEMENTS = [
    ("parking_zone", INSERT_ZONES),
    ("parking_spot", INSERT_SPOTS),
    ("driver", INSERT_DRIVERS),
    ("vehicle", INSERT_VEHICLES),
    ("parking_session", INSERT_SESSIONS),
    ("payment", INSERT_PAYMENTS),
    ("sensor", INSERT_SENSORS),
]


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table_name, statement in STATEMENTS:
                cur.execute(statement)
                print(f"Uneto {cur.rowcount} redova u tabelu '{table_name}'.")
        conn.commit()


if __name__ == "__main__":
    main()
