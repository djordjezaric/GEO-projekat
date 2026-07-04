"""Generisko CRUD sa psycopg2 - radi za bilo koju tabelu iz seme."""

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from db import get_connection


def read_all(table: str, order_by: str | None = None) -> list[dict]:
    query = sql.SQL("SELECT * FROM {table}").format(table=sql.Identifier(table))
    if order_by:
        query += sql.SQL(" ORDER BY {col}").format(col=sql.Identifier(order_by))
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]


def insert_row(table: str, pk_column: str, data: dict) -> int:
    columns = list(data.keys())
    query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING {pk}").format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        vals=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
        pk=sql.Identifier(pk_column),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, list(data.values()))
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


def update_row(table: str, pk_column: str, pk_value, data: dict) -> int:
    columns = list(data.keys())
    set_clause = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder()) for col in columns
    )
    query = sql.SQL("UPDATE {table} SET {set_clause} WHERE {pk} = {ph}").format(
        table=sql.Identifier(table),
        set_clause=set_clause,
        pk=sql.Identifier(pk_column),
        ph=sql.Placeholder(),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, [*data.values(), pk_value])
            affected = cur.rowcount
        conn.commit()
    return affected


def delete_row(table: str, pk_column: str, pk_value) -> int:
    query = sql.SQL("DELETE FROM {table} WHERE {pk} = {ph}").format(
        table=sql.Identifier(table),
        pk=sql.Identifier(pk_column),
        ph=sql.Placeholder(),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, [pk_value])
            affected = cur.rowcount
        conn.commit()
    return affected


def demo() -> None:
    print("\n--- CRUD demo: driver ---")
    print("Pre unosa:", len(read_all("driver")), "vozaca")

    new_id = insert_row(
        "driver",
        "driver_id",
        {
            "first_name": "Milica",
            "last_name": "Ilic",
            "email": "milica.ilic@example.com",
            "phone": "0661239999",
            "license_number": "SR9988776",
        },
    )
    print(f"Ubacen novi vozac, driver_id = {new_id}")

    update_row("driver", "driver_id", new_id, {"phone": "0669998888"})
    print("Azuriran telefon novog vozaca.")
    updated = [d for d in read_all("driver") if d["driver_id"] == new_id][0]
    print("Stanje posle azuriranja:", updated)

    delete_row("driver", "driver_id", new_id)
    print(f"Obrisan vozac driver_id = {new_id}.")
    print("Posle brisanja:", len(read_all("driver")), "vozaca")

    print("\n--- CRUD demo: parking_spot (azuriranje statusa) ---")
    spots = read_all("parking_spot", order_by="spot_id")
    target = spots[1]
    print("Pre:", target["spot_number"], "->", target["status"])
    update_row("parking_spot", "spot_id", target["spot_id"], {"status": "zauzeto"})
    refreshed = [s for s in read_all("parking_spot") if s["spot_id"] == target["spot_id"]][0]
    print("Posle:", refreshed["spot_number"], "->", refreshed["status"])
    update_row("parking_spot", "spot_id", target["spot_id"], {"status": target["status"]})
    print("Status vracen na pocetnu vrednost.")


if __name__ == "__main__":
    demo()
