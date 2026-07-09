"""
ml_app.py – Deo 3: ML detekcija slobodnih parking mjesta.

Pokretanje:
    uv run streamlit run ml_app.py
"""

import sys
import os
from pathlib import Path

# Root projekta na sys.path (za 'from db import ...')
sys.path.insert(0, str(Path(__file__).parent.parent))
# Deo3 folder na sys.path (za 'from ml_detect import ...')
sys.path.insert(0, str(Path(__file__).parent))

_rasterio_proj = Path(sys.executable).parent.parent / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _rasterio_proj.exists():
    os.environ["PROJ_LIB"]  = str(_rasterio_proj)
    os.environ["PROJ_DATA"] = str(_rasterio_proj)

import numpy as np
import cv2
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium

from psycopg2 import sql
from db import get_engine, get_connection
from ml_detect import detect_parking_availability

# ── Parking zone – koordinate stvarnih parking lokacija ──────────────────────
# Koordinate su centri parkinga (ne centri naselja)
ZONES = {
    "Liman 3 – Novi Sad":       {"lon": 19.8218, "lat": 45.2407, "capacity": 12},
    "Zeleni Venac – Beograd":   {"lon": 20.4552, "lat": 44.8172, "capacity": 15},
    "Slavija – Beograd":        {"lon": 20.4693, "lat": 44.8016, "capacity": 18},
    "Centar – Niš":             {"lon": 21.8953, "lat": 43.3212, "capacity": 10},
    "Petrovaradin – Novi Sad":  {"lon": 19.8634, "lat": 45.2516, "capacity": 8},
}

# ── Baza ──────────────────────────────────────────────────────────────────────

def init_ml_table():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(open(Path(__file__).parent / "schema_ml.sql").read())
        conn.commit()


def load_zone_spots(zone_id: int) -> pd.DataFrame:
    """Ucitava stvarne koordinate parking mjesta za zonu iz baze."""
    return pd.read_sql(
        """
        SELECT spot_id, spot_number, status,
               ST_X(location::geometry) AS lon,
               ST_Y(location::geometry) AS lat
        FROM parking_spot
        WHERE zone_id = %s AND location IS NOT NULL
        ORDER BY spot_id
        """,
        get_engine(),
        params=(zone_id,),
    )


def save_detections(rows: list[dict], zone_id: int | None = None) -> int:
    if not rows:
        return 0
    with get_connection() as conn:
        cur = conn.cursor()
        for d in rows:
            cur.execute(
                """
                INSERT INTO ml_detection
                    (image_source, detected_at, status, confidence, vehicle_class,
                     bbox_x1, bbox_y1, bbox_x2, bbox_y2, img_width, img_height,
                     location, zone_ref, notes, verified)
                VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s,
                        ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                        %s,%s,%s)
                """,
                (d["image_source"], d["detected_at"], d["status"],
                 d["confidence"], d["vehicle_class"],
                 d.get("bbox_x1"), d.get("bbox_y1"),
                 d.get("bbox_x2"), d.get("bbox_y2"),
                 d["img_width"], d["img_height"],
                 d["lon"], d["lat"],
                 zone_id, d["notes"], d["verified"]),
            )
        conn.commit()
    return len(rows)


def load_detections() -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT detection_id, image_source, detected_at, status, confidence,
               vehicle_class,
               ST_X(location::geometry) AS lon,
               ST_Y(location::geometry) AS lat,
               zone_ref, notes, verified
        FROM ml_detection ORDER BY detected_at DESC
        """,
        get_engine(),
    )


def get_zone_id(zone_name: str) -> int | None:
    """Pronalazi zone_id iz baze na osnovu najbliže GPS pozicije."""
    z = ZONES[zone_name]
    try:
        df = pd.read_sql(
            """
            SELECT pz.zone_id
            FROM parking_zone pz
            JOIN parking_spot ps ON ps.zone_id = pz.zone_id
            WHERE ps.location IS NOT NULL
            GROUP BY pz.zone_id
            ORDER BY ST_Distance(
                ST_SetSRID(ST_MakePoint(AVG(ST_X(ps.location::geometry)),
                                        AVG(ST_Y(ps.location::geometry))), 4326)::geography,
                ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
            )
            LIMIT 1
            """,
            get_engine(),
            params={"lon": z["lon"], "lat": z["lat"]},
        )
        return int(df.iloc[0]["zone_id"]) if not df.empty else None
    except Exception:
        return None


def update_detection(did: int, **kw):
    allowed = {"status", "notes", "verified", "vehicle_class"}
    fields  = {k: v for k, v in kw.items() if k in allowed}
    if not fields:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        set_clause = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields
        )
        cur.execute(
            sql.SQL("UPDATE ml_detection SET {} WHERE detection_id = %s").format(set_clause),
            list(fields.values()) + [did],
        )
        conn.commit()


def delete_detection(did: int):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM ml_detection WHERE detection_id = %s", (did,))
        conn.commit()


def load_db_spots() -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT ps.spot_id, ps.zone_id, ps.spot_number, ps.status,
               ST_X(ps.location::geometry) AS lon,
               ST_Y(ps.location::geometry) AS lat,
               pz.name AS zone_name
        FROM parking_spot ps
        JOIN parking_zone pz ON ps.zone_id = pz.zone_id
        WHERE ps.location IS NOT NULL
        """,
        get_engine(),
    )

# ── Mapa ──────────────────────────────────────────────────────────────────────

def build_zone_map(zone_name: str, n_free: int, n_occupied: int, total: int,
                   center_lat: float, center_lon: float) -> folium.Map:
    """
    Prikazuje JEDAN marker za parking zonu sa informacijom o slobodnim mjestima.
    """
    m = folium.Map(location=[center_lat, center_lon], zoom_start=17,
                   tiles="CartoDB positron")

    pct_free = n_free / max(total, 1)
    if pct_free > 0.5:
        color = "green"
    elif pct_free > 0.2:
        color = "orange"
    else:
        color = "red"

    popup_html = f"""
    <div style="font-family:sans-serif;font-size:14px;min-width:180px">
        <b>{zone_name}</b><br>
        <hr style="margin:4px 0">
        🟢 Slobodnih: <b>{n_free}</b><br>
        🔴 Zauzetih:  <b>{n_occupied}</b><br>
        📍 Ukupno:    <b>{total}</b><br>
        📊 Popunjenost: <b>{n_occupied/max(total,1)*100:.0f}%</b>
    </div>"""

    folium.Marker(
        location=[center_lat, center_lon],
        popup=folium.Popup(popup_html, max_width=220),
        tooltip=f"{zone_name} – {n_free} slobodnih od {total}",
        icon=folium.Icon(color=color, icon="car", prefix="fa"),
    ).add_to(m)

    return m


def build_overview_map(df: pd.DataFrame) -> folium.Map:
    """
    Pregled svih zona na jednoj mapi – jedan marker po zoni.
    """
    m = folium.Map(location=[44.82, 20.46], zoom_start=7,
                   tiles="CartoDB positron")

    if df.empty:
        for zname, zinfo in ZONES.items():
            folium.Marker(
                [zinfo["lat"], zinfo["lon"]],
                tooltip=zname,
                popup=folium.Popup(f"<b>{zname}</b><br>Nema detekcija", max_width=180),
                icon=folium.Icon(color="gray", icon="car", prefix="fa"),
            ).add_to(m)
        return m

    # Grupiši po image_source + zone_ref – uzmi najnovije po zoni
    for zname, zinfo in ZONES.items():
        # Filtriraj detekcije za ovu zonu po koordinatnoj blizini
        nearby = df[
            (df["lon"].between(zinfo["lon"] - 0.01, zinfo["lon"] + 0.01)) &
            (df["lat"].between(zinfo["lat"] - 0.01, zinfo["lat"] + 0.01))
        ]
        if nearby.empty:
            folium.Marker(
                [zinfo["lat"], zinfo["lon"]],
                tooltip=f"{zname} – nema analize",
                icon=folium.Icon(color="gray", icon="car", prefix="fa"),
            ).add_to(m)
            continue

        n_free = int((nearby["status"] == "slobodno").sum())
        n_occ  = int((nearby["status"] == "zauzeto").sum())
        total  = n_free + n_occ
        pct    = n_occ / max(total, 1)
        color  = "green" if pct < 0.5 else ("orange" if pct < 0.8 else "red")

        popup_html = f"""
        <div style="font-family:sans-serif;font-size:14px;min-width:180px">
            <b>{zname}</b><br><hr style="margin:4px 0">
            🟢 Slobodnih: <b>{n_free}</b><br>
            🔴 Zauzetih: <b>{n_occ}</b><br>
            📊 Popunjenost: <b>{pct*100:.0f}%</b>
        </div>"""

        folium.Marker(
            [zinfo["lat"], zinfo["lon"]],
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"{zname}: {n_free} slobodnih",
            icon=folium.Icon(color=color, icon="car", prefix="fa"),
        ).add_to(m)

    return m

# ── Glavna aplikacija ──────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Pametni parking – ML detekcija",
        page_icon="🅿️", layout="wide",
    )
    st.title("🅿️ Pametni parking – detekcija slobodnih mjesta (Deo 3)")

    try:
        init_ml_table()
    except Exception as e:
        st.error(f"Greška pri kreiranju ML tabele: {e}")
        st.stop()

    tab_detect, tab_edit, tab_df = st.tabs([
        "📷 Detekcija", "✏️ Uredivanje atributa",
        "📊 Pregled podataka",
    ])

    # ── TAB 1: Detekcija ──────────────────────────────────────────────────────
    with tab_detect:
        st.header("Detekcija slobodnih parking mjesta pomoću YOLOv8")
        st.warning(
            "⚠️ **Tip slike:** YOLOv8 je treniran na COCO datasetu (ulične fotografije). "
            "Radi na slikama snimljenim sa ulice, sa parking garaže (s boka) ili CCTV kamerom. "
            "**Ptičja/satelitska perspektiva (odozgo) nije podržana** – model nikad nije vidio "
            "automobile iz te perspektive tokom treninga."
        )

        col_left, col_right = st.columns([1, 1])
        with col_left:
            zone_name = st.selectbox("Parking zona", list(ZONES.keys()))
            zone_info = ZONES[zone_name]

            capacity = st.number_input(
                "Ukupan kapacitet zone (mjesta)",
                min_value=1, max_value=500,
                value=zone_info["capacity"],
            )
            conf_thr = st.slider("Min. pouzdanost detekcije", 0.10, 0.90, 0.25, 0.05)
            upload   = st.file_uploader("Fotografija parkinga",
                                        type=["jpg", "jpeg", "png"])

        with col_right:
            if upload:
                st.image(upload, caption="Originalna slika", use_container_width=True)

        if upload and st.button("▶ Analiziraj slobodna mjesta", type="primary"):
            upload.seek(0)
            file_bytes = np.frombuffer(upload.read(), np.uint8)
            img_bgr    = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

            with st.spinner("YOLOv8 analizira parking..."):
                result = detect_parking_availability(
                    image          = img_bgr,
                    image_source   = upload.name,
                    zone_lon       = zone_info["lon"],
                    zone_lat       = zone_info["lat"],
                    total_capacity = int(capacity),
                    conf_threshold = conf_thr,
                )

            n_veh  = result["n_vehicles"]
            n_free = result["n_free"]
            total  = result["total"]

            # Statistike
            c1, c2, c3 = st.columns(3)
            c1.metric("Zauzeta mjesta",  n_veh,
                      help="Broj detektovanih vozila na slici")
            c2.metric("Slobodna mjesta", n_free,
                      help="Kapacitet zone − detektovana vozila")
            c3.metric("Popunjenost",     f"{n_veh/max(total,1)*100:.0f}%")

            # Anotirana slika – ograničena visina da ne zauzima cijeli ekran
            ann_rgb = cv2.cvtColor(result["annotated"], cv2.COLOR_BGR2RGB)
            st.image(ann_rgb,
                     caption=f"Detektovano vozila: {n_veh} | Slobodnih mjesta: {n_free}",
                     width=620)

            # GPS: koristi stvarne koordinate DB parking mjesta za zonu
            zone_id  = get_zone_id(zone_name)
            all_rows = result["detections"] + result["free_spots"]

            if zone_id is not None:
                db_zone_spots = load_zone_spots(zone_id)
                if not db_zone_spots.empty:
                    spots_list = db_zone_spots.to_dict("records")
                    # Rasporedi detekcije na stvarna mjesta iz baze
                    for i, row in enumerate(all_rows):
                        if i < len(spots_list):
                            row["lon"] = spots_list[i]["lon"]
                            row["lat"] = spots_list[i]["lat"]

            n = save_detections(all_rows, zone_id=zone_id)
            st.success(
                f"Sačuvano {n} zapisa u bazu "
                f"({n_veh} zauzetih + {n_free} slobodnih)."
            )

            # Mapa – jedan marker za zonu sa rezultatom analize
            fmap = build_zone_map(
                zone_name   = zone_name,
                n_free      = n_free,
                n_occupied  = n_veh,
                total       = total,
                center_lat  = zone_info["lat"],
                center_lon  = zone_info["lon"],
            )
            st.subheader("Lokacija parking zone")
            st_folium(fmap, width=700, height=420, returned_objects=[])

    # ── TAB 2: Uredivanje atributa ────────────────────────────────────────────
    with tab_edit:
        st.header("Uredivanje atributa detekcija")
        df_edit = load_detections()

        if df_edit.empty:
            st.info("Nema detekcija. Pokrenite detekciju.")
        else:
            sel_id = st.selectbox(
                "Odaberite detekciju",
                df_edit["detection_id"].tolist(),
                format_func=lambda i: (
                    f"ID {i} – "
                    + str(df_edit.loc[df_edit.detection_id == i, "status"].values[0])
                    + " | "
                    + str(df_edit.loc[df_edit.detection_id == i, "vehicle_class"].values[0])
                ),
            )
            row = df_edit[df_edit.detection_id == sel_id].iloc[0]

            col_a, col_b = st.columns(2)
            with col_a:
                new_status = st.selectbox(
                    "Status",
                    ["zauzeto", "slobodno", "nepoznato"],
                    index=["zauzeto", "slobodno", "nepoznato"].index(row["status"]),
                )
                new_class = st.selectbox(
                    "Klasa vozila",
                    ["car", "truck", "bus", "motorcycle", "none"],
                    index=["car", "truck", "bus", "motorcycle", "none"].index(
                        row["vehicle_class"]
                        if row["vehicle_class"] in ["car","truck","bus","motorcycle","none"]
                        else "car"
                    ),
                )
            with col_b:
                new_notes    = st.text_area("Napomena", value=row["notes"] or "")
                new_verified = st.checkbox("Verifikovano", value=bool(row["verified"]))

            col_s, col_d = st.columns(2)
            with col_s:
                if st.button("💾 Sačuvaj", type="primary"):
                    update_detection(sel_id, status=new_status,
                                     vehicle_class=new_class,
                                     notes=new_notes, verified=new_verified)
                    st.success("Ažurirano.")
                    st.rerun()
            with col_d:
                if st.button("🗑️ Obriši", type="secondary"):
                    delete_detection(sel_id)
                    st.warning("Obrisano.")
                    st.rerun()

            # Mini mapa odabrane detekcije
            if pd.notna(row["lat"]) and pd.notna(row["lon"]):
                mini = folium.Map([row["lat"], row["lon"]], zoom_start=17,
                                  tiles="CartoDB positron")
                col = "green" if row["status"] == "slobodno" else "red"
                folium.Marker(
                    [row["lat"], row["lon"]],
                    popup=f"ID {sel_id}: {row['status']}",
                    icon=folium.Icon(color=col),
                ).add_to(mini)
                st_folium(mini, width=600, height=320, returned_objects=[])

    # ── TAB 3: DataFrame ───────────────────────────────────────────────────────
    with tab_df:
        st.header("Pregled svih detekcija")
        df_all = load_detections()

        if df_all.empty:
            st.info("Nema detekcija.")
        else:
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                status_f = st.multiselect("Status",
                    ["slobodno", "zauzeto", "nepoznato"],
                    default=["slobodno", "zauzeto", "nepoznato"])
            with col_f2:
                verified_f = st.checkbox("Samo verifikovane", False)

            mask = df_all["status"].isin(status_f)
            if verified_f:
                mask &= df_all["verified"] == True
            df_v = df_all[mask]

            st.write(f"Prikazano **{len(df_v)}** od **{len(df_all)}** zapisa")
            st.dataframe(df_v.rename(columns={
                "detection_id": "ID", "image_source": "Izvor",
                "detected_at": "Vreme", "status": "Status",
                "confidence": "Pouzdanost", "vehicle_class": "Vozilo",
                "lon": "Lon", "lat": "Lat",
                "notes": "Napomena", "verified": "Verifikovano",
            }), use_container_width=True, height=380)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Ukupno", len(df_all))
            c2.metric("Slobodna", int((df_all["status"] == "slobodno").sum()))
            c3.metric("Zauzeta",  int((df_all["status"] == "zauzeto").sum()))
            c4.metric("Verifikovana", int(df_all["verified"].sum()))

            fmap = build_overview_map(df_v)
            st.subheader("Pregled zona na mapi")
            st_folium(fmap, width=800, height=470, returned_objects=[])

if __name__ == "__main__":
    main()
