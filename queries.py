"""8 upita koji spajaju (JOIN) dve ili vise tabela i filtriraju podatke (WHERE)."""

import pandas as pd

from db import get_engine

QUERIES = {
    "1. Aktivne sesije parkiranja (vozac, vozilo, zona, mesto)": """
        SELECT s.session_id, d.first_name || ' ' || d.last_name AS vozac,
               v.license_plate, z.name AS zona, sp.spot_number, s.check_in_time
        FROM parking_session s
        JOIN vehicle v ON v.vehicle_id = s.vehicle_id
        JOIN driver d ON d.driver_id = v.driver_id
        JOIN parking_spot sp ON sp.spot_id = s.spot_id
        JOIN parking_zone z ON z.zone_id = sp.zone_id
        WHERE s.status = 'aktivna';
    """,
    "2. Broj slobodnih mesta po zoni u Beogradu": """
        SELECT z.name AS zona, z.city, COUNT(sp.spot_id) AS slobodna_mesta
        FROM parking_zone z
        JOIN parking_spot sp ON sp.zone_id = z.zone_id
        WHERE sp.status = 'slobodno' AND z.city = 'Beograd'
        GROUP BY z.name, z.city;
    """,
    "3. Ukupan naplaceni prihod po zoni": """
        SELECT z.name AS zona, SUM(p.amount) AS prihod
        FROM payment p
        JOIN parking_session s ON s.session_id = p.session_id
        JOIN parking_spot sp ON sp.spot_id = s.spot_id
        JOIN parking_zone z ON z.zone_id = sp.zone_id
        WHERE p.payment_status = 'placeno'
        GROUP BY z.name
        ORDER BY prihod DESC;
    """,
    "4. Vozaci sa zavrsenim sesijama iznad 100 din": """
        SELECT DISTINCT d.first_name, d.last_name, s.session_id, s.total_amount
        FROM parking_session s
        JOIN vehicle v ON v.vehicle_id = s.vehicle_id
        JOIN driver d ON d.driver_id = v.driver_id
        WHERE s.status = 'zavrsena' AND s.total_amount > 100;
    """,
    "5. Senzori sa niskim nivoom baterije (potrebno odrzavanje)": """
        SELECT sn.sensor_id, sp.spot_number, z.name AS zona, sn.battery_level
        FROM sensor sn
        JOIN parking_spot sp ON sp.spot_id = sn.spot_id
        JOIN parking_zone z ON z.zone_id = sp.zone_id
        WHERE sn.battery_level < 20;
    """,
    "6. Elektricna vozila i njihove sesije": """
        SELECT v.license_plate, v.model, sp.spot_number, s.status, s.check_in_time
        FROM vehicle v
        JOIN parking_session s ON s.vehicle_id = v.vehicle_id
        JOIN parking_spot sp ON sp.spot_id = s.spot_id
        WHERE v.vehicle_type = 'elektricno';
    """,
    "7. Prosecno trajanje parkiranja po zoni (zavrsene sesije)": """
        SELECT z.name AS zona,
               ROUND(AVG(EXTRACT(EPOCH FROM (s.check_out_time - s.check_in_time)) / 3600)::numeric, 2)
                   AS prosecno_trajanje_h
        FROM parking_session s
        JOIN parking_spot sp ON sp.spot_id = s.spot_id
        JOIN parking_zone z ON z.zone_id = sp.zone_id
        WHERE s.status = 'zavrsena' AND s.check_out_time IS NOT NULL
        GROUP BY z.name;
    """,
    "8. Neuspesna ili placanja na cekanju sa podacima o vozacu": """
        SELECT p.payment_id, p.payment_status, p.amount, d.first_name, d.last_name, v.license_plate
        FROM payment p
        JOIN parking_session s ON s.session_id = p.session_id
        JOIN vehicle v ON v.vehicle_id = s.vehicle_id
        JOIN driver d ON d.driver_id = v.driver_id
        WHERE p.payment_status IN ('na_cekanju', 'neuspesno');
    """,
}


def run_all_queries() -> None:
    engine = get_engine()
    for title, sql_text in QUERIES.items():
        print(f"\n=== {title} ===")
        df = pd.read_sql(sql_text, engine)
        print(df.to_string(index=False) if not df.empty else "(nema rezultata)")


if __name__ == "__main__":
    run_all_queries()
