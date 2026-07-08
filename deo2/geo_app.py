"""Deo 2 – Python GEO: Streamlit GIS aplikacija za upravljanje parking mestima.

Pokretanje: streamlit run geo_app.py
Zahtjevi:   geo_download.py mora biti pokrenut bar jednom (preuzima SHP podatke).
"""

import os
import sys
import warnings
from pathlib import Path

# Dodaj root projekta na sys.path da bi 'from db import ...' radio iz podfolder
sys.path.insert(0, str(Path(__file__).parent.parent))

# Fix PROJ konflikt: rasterio dolazi sa novijom proj.db (v6) nego pyproj (v4).
_rasterio_proj = Path(sys.executable).parent.parent / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _rasterio_proj.exists():
    os.environ["PROJ_LIB"]  = str(_rasterio_proj)
    os.environ["PROJ_DATA"] = str(_rasterio_proj)

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from shapely.geometry import Point, box
from streamlit_folium import st_folium

from db import get_engine
from geo_download import CLIPPED_DIR, main as download_data

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Konfiguracija
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Parking GIS",
    layout="wide",
    page_icon="🅿️",
    initial_sidebar_state="expanded",
)

LAYER_FILES = {
    "Putevi": "gis_osm_roads_free_1",
    "Zgrade": "gis_osm_buildings_a_free_1",
    "Namena zemljista": "gis_osm_landuse_a_free_1",
    "Tacke interesa (POI)": "gis_osm_pois_free_1",
    "Vodene povrsine": "gis_osm_water_a_free_1",
    "Prirodna podrucja": "gis_osm_natural_a_free_1",
}

LAYER_DEFAULTS = {
    "Putevi":               (True,  "#777777"),
    "Zgrade":               (False, "#FFA07A"),
    "Namena zemljista":     (False, "#90EE90"),
    "Tacke interesa (POI)": (False, "#FF4500"),
    "Vodene povrsine":      (False, "#4169E1"),
    "Prirodna podrucja":    (False, "#228B22"),
}

TILE_OPTIONS = {
    "OpenStreetMap":        "OpenStreetMap",
    "CartoDB Positron":     "CartoDB positron",
    "CartoDB Dark Matter":  "CartoDB dark_matter",
    "Stamen Toner":         "Stamen Toner",
}

# Klase puteva koji se prikazuju u folium mapi (performanse)
MAJOR_ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
}

CITY_CENTERS = {
    "Beograd":  (20.456, 44.820),
    "Novi Sad": (19.840, 45.255),
    "Nis":      (21.895, 43.320),
}


# ---------------------------------------------------------------------------
# Ucitavanje podataka (cache)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_shp_layer(layer_key: str) -> gpd.GeoDataFrame:
    filename = LAYER_FILES[layer_key]
    path = CLIPPED_DIR / f"{filename}.shp"
    if not path.exists():
        return gpd.GeoDataFrame()
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


@st.cache_data(show_spinner=False)
def load_parking_data() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Ucitava parking zones i spots iz PostGIS baze i vraca kao GeoDataFrame."""
    engine = get_engine()

    # Parking spots — imaju PostGIS geography kolonu
    spots_sql = """
        SELECT s.spot_id, s.zone_id, s.spot_number, s.spot_type,
               s.is_covered, s.status, s.created_at,
               z.name  AS zone_name,
               z.city  AS city,
               z.hourly_rate,
               ST_AsText(s.location::geometry) AS wkt
        FROM parking_spot s
        JOIN parking_zone z ON z.zone_id = s.zone_id
        WHERE s.location IS NOT NULL;
    """
    spots_df = pd.read_sql(spots_sql, engine)
    from shapely import wkt as _wkt
    spots_df["geometry"] = spots_df["wkt"].apply(_wkt.loads)
    spots_gdf = gpd.GeoDataFrame(spots_df.drop(columns=["wkt"]), crs="EPSG:4326")

    # Parking zones — centroid iz prosijeka lokacija mjesta u zoni
    zones_sql = """
        SELECT z.zone_id, z.name, z.city, z.total_capacity, z.hourly_rate,
               z.has_covered_spots,
               ST_AsText(ST_Centroid(ST_Collect(s.location::geometry))) AS centroid_wkt
        FROM parking_zone z
        LEFT JOIN parking_spot s ON s.zone_id = z.zone_id AND s.location IS NOT NULL
        GROUP BY z.zone_id, z.name, z.city, z.total_capacity, z.hourly_rate, z.has_covered_spots;
    """
    zones_df = pd.read_sql(zones_sql, engine)

    def parse_centroid(wkt_val):
        if wkt_val is None:
            return None
        from shapely import wkt as _wkt2
        try:
            return _wkt2.loads(wkt_val)
        except Exception:
            return None

    zones_df["geometry"] = zones_df["centroid_wkt"].apply(parse_centroid)
    # Fallback na centar grada ako nema tacke
    for idx, row in zones_df.iterrows():
        if row["geometry"] is None:
            lon, lat = CITY_CENTERS.get(row["city"], (20.46, 44.82))
            zones_df.at[idx, "geometry"] = Point(lon, lat)
    zones_gdf = gpd.GeoDataFrame(
        zones_df.drop(columns=["centroid_wkt"]), crs="EPSG:4326"
    )
    return zones_gdf, spots_gdf


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def build_sidebar():
    st.sidebar.title("🅿️ Kontrole")
    st.sidebar.markdown("---")

    st.sidebar.subheader("Rasterska podloga")
    base_map = st.sidebar.selectbox(
        "Tip podloge", list(TILE_OPTIONS.keys()), label_visibility="collapsed"
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("SHP slojevi (Geofabrik)")

    layer_cfg = {}
    for name, (default_show, default_color) in LAYER_DEFAULTS.items():
        col1, col2 = st.sidebar.columns([4, 1])
        with col1:
            show = st.checkbox(name, value=default_show, key=f"shp_{name}")
        with col2:
            color = st.color_picker(
                "b", default_color, key=f"col_{name}", label_visibility="collapsed"
            )
        layer_cfg[name] = {"show": show, "color": color}

    st.sidebar.markdown("---")
    st.sidebar.subheader("Parking (iz baze)")
    show_zones = st.sidebar.checkbox("Parking zone", value=True)

    return base_map, layer_cfg, show_zones


# ---------------------------------------------------------------------------
# Tab 1 — Interaktivna mapa
# ---------------------------------------------------------------------------

def render_map(base_map, layer_cfg, show_zones):
    m = folium.Map(location=[45.00, 20.20], zoom_start=9, control_scale=True)

    # Rasterska podloga
    tile_id = TILE_OPTIONS[base_map]
    if tile_id != "OpenStreetMap":
        folium.TileLayer(tile_id, name=base_map).add_to(m)

    # SHP slojevi
    for name, cfg in layer_cfg.items():
        if not cfg["show"]:
            continue
        gdf = load_shp_layer(name)
        if gdf.empty:
            continue

        color = cfg["color"]

        # Za puteve — samo glavne klase zbog performansi
        if name == "Putevi" and "fclass" in gdf.columns:
            gdf = gdf[gdf["fclass"].isin(MAJOR_ROAD_CLASSES)]

        # Ogranici broj objekata koji se salju u Folium
        if len(gdf) > 3000:
            gdf = gdf.sample(3000, random_state=42)

        geom_type = gdf.geometry.geom_type.iloc[0] if not gdf.empty else "Point"

        if "Point" in geom_type:
            style_fn = lambda f, c=color: {"color": c, "radius": 3, "fillColor": c, "fillOpacity": 0.7}
        elif "Line" in geom_type:
            style_fn = lambda f, c=color: {"color": c, "weight": 1.2, "opacity": 0.65}
        else:
            style_fn = lambda f, c=color: {
                "fillColor": c, "color": c, "weight": 0.5,
                "fillOpacity": 0.35, "opacity": 0.7,
            }

        tooltip_fields = [c for c in ["name", "fclass"] if c in gdf.columns]

        fg = folium.FeatureGroup(name=name, show=True)
        folium.GeoJson(
            gdf.__geo_interface__,
            style_function=style_fn,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=[f"{f.capitalize()}:" for f in tooltip_fields],
            ) if tooltip_fields else None,
        ).add_to(fg)
        fg.add_to(m)

    # Parking zone iz baze – jedan marker po zoni
    zones_gdf, spots_gdf = load_parking_data()

    if show_zones:
        # Izracunaj slobodna/zauzeta po zoni
        zone_stats = {}
        if not spots_gdf.empty:
            for zid, grp in spots_gdf.groupby("zone_id"):
                zone_stats[zid] = {
                    "slobodno": int((grp["status"] == "slobodno").sum()),
                    "ukupno":   len(grp),
                }

        fg_z = folium.FeatureGroup(name="Parking zone (baza)", show=True)
        for _, row in zones_gdf.iterrows():
            if row.geometry is None:
                continue
            stats    = zone_stats.get(row["zone_id"], {})
            slobodno = stats.get("slobodno", "?")
            ukupno   = stats.get("ukupno",   row["total_capacity"])

            # Boja markera po popunjenosti
            if isinstance(slobodno, int) and isinstance(ukupno, int) and ukupno > 0:
                pct_free = slobodno / ukupno
                marker_color = "green" if pct_free > 0.5 else ("orange" if pct_free > 0.2 else "red")
            else:
                marker_color = "blue"

            popup_html = (
                f"<div style='font-family:sans-serif;font-size:15px;min-width:160px;text-align:center'>"
                f"<b style='font-size:22px'>{slobodno}</b> / {ukupno}<br>"
                f"<span style='color:#555'>slobodnih mjesta</span><br>"
                f"<hr style='margin:6px 0'>"
                f"💰 {row['hourly_rate']} din/h &nbsp;|&nbsp; "
                f"🏠 {'Natkriveno' if row['has_covered_spots'] else 'Otvoreno'}"
                f"</div>"
            )

            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                icon=folium.Icon(color=marker_color, icon="car", prefix="fa"),
                tooltip=f"{slobodno} slobodnih / {ukupno} ukupno",
                popup=folium.Popup(popup_html, max_width=200),
            ).add_to(fg_z)
        fg_z.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=580, returned_objects=[])


# ---------------------------------------------------------------------------
# Tab 2 — Overlay Analize (6 tehnika)
# ---------------------------------------------------------------------------


def _folium_overlay_map(layers, map_key, height=500):
    """Helper: prikazuje interaktivnu Folium mapu sa više GeoDataFrame slojeva."""
    sw = ne = None
    for gdf, *_ in layers:
        if gdf is None or gdf.empty:
            continue
        g4 = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
        b = g4.total_bounds
        if sw is None:
            sw = [b[1], b[0]]
            ne = [b[3], b[2]]
        else:
            sw = [min(sw[0], b[1]), min(sw[1], b[0])]
            ne = [max(ne[0], b[3]), max(ne[1], b[2])]

    m = folium.Map(tiles="CartoDB positron", control_scale=True)

    for gdf, fill, stroke, opacity, name in layers:
        if gdf is None or gdf.empty:
            continue
        g4 = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
        if len(g4) > 2000:
            g4 = g4.sample(2000, random_state=42)
        g4 = g4[["geometry"]]  # odbaci ne-serijalizabilne kolone (Timestamp, itd.)
        valid = g4.geometry.dropna()
        if valid.empty:
            continue
        gt = valid.geom_type.iloc[0]

        if "Point" in gt:
            folium.GeoJson(
                g4.__geo_interface__, name=name,
                marker=folium.CircleMarker(
                    radius=6, color=stroke, fill=True,
                    fill_color=fill, fill_opacity=opacity, weight=1,
                ),
            ).add_to(m)
        elif "Line" in gt:
            folium.GeoJson(
                g4.__geo_interface__, name=name,
                style_function=lambda f, _s=stroke, _o=opacity: {
                    "color": _s, "weight": 2.5, "opacity": _o,
                },
            ).add_to(m)
        else:
            folium.GeoJson(
                g4.__geo_interface__, name=name,
                style_function=lambda f, _f=fill, _s=stroke, _o=opacity: {
                    "fillColor": _f, "color": _s, "weight": 1.5, "fillOpacity": _o,
                },
            ).add_to(m)

    if sw and ne:
        m.fit_bounds([sw, ne])
    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=height, returned_objects=[], key=map_key)


def render_overlay():
    st.header("⬡ Overlay Tehnike")
    st.info("6 prostornih overlay operacija nad parking podacima. Sve mape su interaktivne — možeš zumirati i pomjerati.")

    zones_gdf, spots_gdf = load_parking_data()
    if spots_gdf.empty:
        st.warning("Nema parking mjesta u bazi.")
        return

    roads_gdf   = load_shp_layer("Putevi")
    landuse_gdf = load_shp_layer("Namena zemljista")

    spots_3857 = spots_gdf.to_crs("EPSG:3857")
    CRS_3857   = "EPSG:3857"

    buf400 = spots_3857.copy()
    buf400["geometry"] = spots_3857.buffer(400)
    buf_union = buf400.dissolve()

    # --- 1. Buffer ---
    st.subheader("1. Buffer — zona uticaja 400 m oko parking mjesta")
    _folium_overlay_map([
        (buf400,     "#1565C0", "#1565C0", 0.25, "Buffer 400 m"),
        (spots_3857, "#D50000", "#D50000", 0.9,  "Parking mjesta"),
    ], "buf1")
    st.caption(f"Ukupno {len(buf400)} buffer zona; ukupna površina uniona = {buf_union.geometry.area.iloc[0]/1e6:.4f} km²")

    # --- 2. Clip ---
    st.subheader("2. Clip — putevi unutar 400 m od parking mjesta")
    if not roads_gdf.empty:
        try:
            roads_3857    = roads_gdf.to_crs(CRS_3857)
            major         = roads_3857[roads_3857["fclass"].isin(MAJOR_ROAD_CLASSES)] if "fclass" in roads_3857.columns else roads_3857
            clipped_roads = gpd.clip(major, buf_union)
            _folium_overlay_map([
                (buf_union,     "#1565C0", "#1565C0", 0.2,  "Buffer zona"),
                (clipped_roads, "#B71C1C", "#B71C1C", 0.85, f"Putevi u zoni ({len(clipped_roads)})"),
                (spots_3857,    "#F9A825", "#F9A825", 0.9,  "Parking"),
            ], "clip2")
            st.caption(f"Isječeno {len(clipped_roads)} segmenata puta unutar 400 m od parking mjesta.")
        except Exception as e:
            st.warning(f"Clip greška: {e}")
    else:
        st.info("Nema SHP podataka o putevima. Pokrenite geo_download.py.")

    # --- 3. Intersection ---
    st.subheader("3. Intersection — presjek buffer zone sa namjenom zemljista")
    if not landuse_gdf.empty:
        try:
            landuse_3857 = landuse_gdf.to_crs(CRS_3857)
            intersection = gpd.overlay(
                buf_union[["geometry"]], landuse_3857[["fclass", "geometry"]], how="intersection"
            )
            palette      = ["#E53935", "#43A047", "#1E88E5", "#FB8C00", "#8E24AA", "#00ACC1", "#F4511E", "#6D4C41"]
            fclasses     = list(intersection["fclass"].unique()) if "fclass" in intersection.columns else []
            fclass_color = {fc: palette[i % len(palette)] for i, fc in enumerate(fclasses)}

            m = folium.Map(tiles="CartoDB positron", control_scale=True)
            buf4326 = buf_union[["geometry"]].to_crs("EPSG:4326")
            folium.GeoJson(
                buf4326.__geo_interface__, name="Buffer zona",
                style_function=lambda f: {"fillColor": "#1565C0", "color": "#1565C0", "weight": 1, "fillOpacity": 0.1}
            ).add_to(m)
            if "fclass" in intersection.columns:
                inter4326 = intersection.to_crs("EPSG:4326")
                for fc in fclasses:
                    sub = inter4326[inter4326["fclass"] == fc]
                    c   = fclass_color[fc]
                    folium.GeoJson(
                        sub.__geo_interface__, name=fc,
                        style_function=lambda f, _c=c: {"fillColor": _c, "color": _c, "weight": 1, "fillOpacity": 0.55}
                    ).add_to(m)
            folium.GeoJson(
                spots_gdf[["geometry"]].__geo_interface__, name="Parking mjesta",
                marker=folium.CircleMarker(radius=5, color="black", fill=True, fill_color="black", fill_opacity=0.9, weight=1)
            ).add_to(m)
            b = buf4326.total_bounds
            m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
            folium.LayerControl(collapsed=False).add_to(m)
            st_folium(m, use_container_width=True, height=500, returned_objects=[], key="inter3")
            if "fclass" in intersection.columns:
                counts = intersection["fclass"].value_counts().reset_index()
                counts.columns = ["Namjena", "Broj područja"]
                st.dataframe(counts)
        except Exception as e:
            st.warning(f"Intersection greška: {e}")
    else:
        st.info("Nema SHP podataka o namjeni zemljista. Pokrenite geo_download.py.")

    # --- 4. Union/Dissolve ---
    st.subheader("4. Union / Dissolve — parking pokrivanje po gradu")
    try:
        buf_city = spots_3857.copy()
        buf_city["geometry"] = spots_3857.buffer(800)
        buf_city["city"]     = spots_gdf["city"].values
        city_union = buf_city.dissolve(by="city").reset_index()

        city_colors = {"Beograd": "#1565C0", "Novi Sad": "#2E7D32", "Nis": "#B71C1C"}
        m = folium.Map(tiles="CartoDB positron", control_scale=True)
        city4326 = city_union.to_crs("EPSG:4326")
        for _, row in city4326.iterrows():
            city  = row["city"]
            c     = city_colors.get(city, "#555555")
            r_gdf = gpd.GeoDataFrame([row], crs="EPSG:4326")[["geometry"]]
            folium.GeoJson(
                r_gdf.__geo_interface__, name=city,
                style_function=lambda f, _c=c: {"fillColor": _c, "color": _c, "weight": 1.5, "fillOpacity": 0.45}
            ).add_to(m)
        folium.GeoJson(
            spots_gdf[["geometry"]].__geo_interface__, name="Parking mjesta",
            marker=folium.CircleMarker(radius=5, color="black", fill=True, fill_color="black", fill_opacity=0.9, weight=1)
        ).add_to(m)
        b = city4326.total_bounds
        m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, use_container_width=True, height=500, returned_objects=[], key="union4")

        area_df = city_union[["city", "geometry"]].copy()
        area_df["povrsina_km2"] = area_df.geometry.area / 1e6
        st.dataframe(area_df[["city", "povrsina_km2"]].rename(columns={"city": "Grad", "povrsina_km2": "Pokrivenost (km²)"}))
    except Exception as e:
        st.warning(f"Union greška: {e}")

    # --- 5. Difference ---
    st.subheader("5. Difference — Beograd: oblasti bez parking pokrivenosti (500 m)")
    try:
        BG_BBOX      = (20.25, 44.70, 20.65, 44.95)
        aoi_gdf      = gpd.GeoDataFrame(geometry=[box(*BG_BBOX)], crs="EPSG:4326").to_crs(CRS_3857)
        bg_spots     = spots_3857[spots_gdf["city"].values == "Beograd"]
        buf500       = bg_spots.copy()
        buf500["geometry"] = bg_spots.buffer(500)
        buf500_union = buf500[["geometry"]].dissolve()
        diff         = gpd.overlay(aoi_gdf[["geometry"]], buf500_union[["geometry"]], how="difference")
        _folium_overlay_map([
            (diff,         "#757575", "#555555", 0.5,  "Bez parkinga"),
            (buf500_union, "#1565C0", "#1565C0", 0.35, "Parking buffer 500 m"),
            (bg_spots,     "#D50000", "#D50000", 0.9,  "Parking mjesta (BG)"),
        ], "diff5")
        total_area = aoi_gdf.geometry.area.sum()
        park_area  = buf500_union.geometry.area.sum()
        diff_area  = diff.geometry.area.sum()
        st.caption(
            f"AOI Beograd: {total_area/1e6:.1f} km² | "
            f"Parking pokrivenost: {park_area/1e6:.4f} km² ({park_area/total_area*100:.2f}%) | "
            f"Bez parkinga: {diff_area/1e6:.1f} km²"
        )
    except Exception as e:
        st.warning(f"Difference greška: {e}")

    # --- 6. Symmetric Difference ---
    st.subheader("6. Symmetric Difference — dvije susjedne zone u Beogradu")
    try:
        bg_spots = spots_gdf[spots_gdf["city"] == "Beograd"]
        if bg_spots["zone_name"].nunique() < 2:
            st.info("Nedovoljno zona u Beogradu za prikaz.")
        else:
            zone_names = bg_spots["zone_name"].unique()[:2]
            za_name, zb_name = zone_names[0], zone_names[1]

            za = bg_spots[bg_spots["zone_name"] == za_name].to_crs("EPSG:3857")
            zb = bg_spots[bg_spots["zone_name"] == zb_name].to_crs("EPSG:3857")

            buf_a = za.copy(); buf_a["geometry"] = za.buffer(1500)
            buf_b = zb.copy(); buf_b["geometry"] = zb.buffer(1500)

            union_a  = buf_a[["geometry"]].dissolve()
            union_b  = buf_b[["geometry"]].dissolve()
            sym_diff = gpd.overlay(union_a, union_b, how="symmetric_difference")
            inter_ab = gpd.overlay(union_a, union_b, how="intersection")

            _folium_overlay_map([
                (union_a,                    "#1565C0", "#1565C0", 0.25, f"{za_name} buffer"),
                (union_b,                    "#B71C1C", "#B71C1C", 0.25, f"{zb_name} buffer"),
                (inter_ab,                   "#F9A825", "#F9A825", 0.6,  "Presjek (isključen)"),
                (sym_diff,                   "#7B1FA2", "#7B1FA2", 0.5,  "Sym. Diff (ekskluzivno)"),
                (pd.concat([za, zb]),        "black",   "black",   0.9,  "Parking mjesta"),
            ], "symdiff6")

            st.caption(
                f"Plavo = isključivo {za_name} | "
                f"Crveno = isključivo {zb_name} | "
                f"Žuto = presjek (ovaj dio je ISKLJUČEN iz sym. diff) | "
                f"Ljubičasto = sym. diff rezultat"
            )
    except Exception as e:
        st.warning(f"Symmetric difference greška: {e}")


# ---------------------------------------------------------------------------
# Tab 3 — Prostorni Upiti (5 primjera)
# ---------------------------------------------------------------------------

def render_spatial_queries():
    st.header("🔍 Prostorni Upiti")

    zones_gdf, spots_gdf = load_parking_data()
    if spots_gdf.empty:
        st.warning("Nema parking mjesta u bazi.")
        return

    roads_gdf   = load_shp_layer("Putevi")
    pois_gdf    = load_shp_layer("Tacke interesa (POI)")
    buildings_gdf = load_shp_layer("Zgrade")
    CRS_STR     = "EPSG:3857"

    spots_3857  = spots_gdf.to_crs(CRS_STR)
    buf400_3857 = spots_3857.copy()
    buf400_3857["geometry"] = spots_3857.buffer(400)
    buf_union_3857 = buf400_3857.dissolve()
    buf_union_4326 = buf_union_3857.to_crs("EPSG:4326")
    buf_geom_4326  = buf_union_4326.geometry.iloc[0]

    # --- 1. Within ---
    st.subheader("1. Within — tacke interesa unutar 400 m od parking mjesta")
    if not pois_gdf.empty:
        try:
            mask = pois_gdf.within(buf_geom_4326)
            pois_within = pois_gdf[mask]
            st.success(f"Pronađeno {len(pois_within)} POI unutar 400 m od parking mjesta.")

            if not pois_within.empty:
                show_cols = [c for c in ["name", "fclass"] if c in pois_within.columns]
                st.dataframe(pois_within[show_cols].head(30))
        except Exception as e:
            st.warning(f"Within greška: {e}")
    else:
        st.info("POI podaci nisu dostupni. Pokrenite geo_download.py.")

    # --- 2. Intersects ---
    st.subheader("2. Intersects — putevi koji sijeku parking buffer zonu")
    if not roads_gdf.empty:
        try:
            mask = roads_gdf.intersects(buf_geom_4326)
            roads_int = roads_gdf[mask]
            st.success(f"Pronađeno {len(roads_int)} segmenata puta koji se sijeku sa parking buffer zonom.")
        except Exception as e:
            st.warning(f"Intersects greška: {e}")

    # --- 3. Overlaps — zgrade u preklapanju sa parking buffer ---
    st.subheader("3. Overlaps / Intersects — zgrade u parking buffer zoni")
    if not buildings_gdf.empty:
        try:
            mask = buildings_gdf.intersects(buf_geom_4326)
            bld_in_zone = buildings_gdf[mask]
            st.success(f"Pronađeno {len(bld_in_zone)} zgrada koje se sijeku / preklapaju sa parking buffer zonom.")
        except Exception as e:
            st.warning(f"Overlaps greška: {e}")
    else:
        st.info("Podaci o zgradama nisu dostupni. Pokrenite geo_download.py.")

    # --- 4. Spatial Join (sjoin_nearest) ---
    st.subheader("4. Spatial Join (sjoin_nearest) — parking mjesta + najbliži put")
    if not roads_gdf.empty:
        try:
            roads_sample = roads_gdf.copy()
            if "fclass" in roads_sample.columns:
                roads_sample = roads_sample[roads_sample["fclass"].isin(MAJOR_ROAD_CLASSES)]

            road_cols = [c for c in ["name", "fclass"] if c in roads_sample.columns] + ["geometry"]
            rename_map = {"name": "naziv_puta"} if "name" in roads_sample.columns else {}

            joined = gpd.sjoin_nearest(
                spots_gdf[["spot_number", "zone_name", "city", "status", "geometry"]],
                roads_sample[road_cols].rename(columns=rename_map),
                how="left",
                distance_col="dist_stepen",
            )
            # Priblizna distanca u metrima (1 stepen ≈ 111 km)
            joined["dist_m"] = (joined["dist_stepen"] * 111_000).round(1)

            disp_cols = [c for c in ["spot_number", "zone_name", "city", "status", "naziv_puta", "fclass", "dist_m"] if c in joined.columns]
            st.dataframe(joined[disp_cols])
            st.caption("Svako parking mjesta spojeno sa najbliZim glavnim putem iz OSM/Geofabrik sloja.")
        except Exception as e:
            st.warning(f"Sjoin nearest greška: {e}")

    # --- 5. Prostorni upit po udaljenosti — slobodna mjesta unutar 2 km od centra NS ---
    st.subheader("5. Distance query — slobodna mjesta unutar 2 km od centra Novog Sada")
    try:
        ns_lon, ns_lat = CITY_CENTERS["Novi Sad"]
        ns_center_3857 = (
            gpd.GeoDataFrame(geometry=[Point(ns_lon, ns_lat)], crs="EPSG:4326")
            .to_crs("EPSG:3857")
            .geometry.iloc[0]
        )
        dists = spots_3857.geometry.distance(ns_center_3857)
        free_within = spots_gdf[(dists <= 2000) & (spots_gdf["status"] == "slobodno")]

        st.success(f"Pronađeno {len(free_within)} slobodnih parking mjesta unutar 2 km od centra Novog Sada.")
        disp = free_within[["spot_number", "zone_name", "spot_type", "is_covered", "status"]].copy()
        st.dataframe(disp)
    except Exception as e:
        st.warning(f"Distance query greška: {e}")


# ---------------------------------------------------------------------------
# Tab 4 — DataFrames
# ---------------------------------------------------------------------------

def render_dataframes():
    st.header("📊 DataFrames iz SHP fajlova i PostGIS baze")

    # --- Baza (Deo 1) ---
    st.subheader("Podaci iz PostGIS baze (Deo 1)")
    zones_gdf, spots_gdf = load_parking_data()

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Parking zone** ({len(zones_gdf)} redova)")
        st.dataframe(zones_gdf.drop(columns=["geometry"], errors="ignore"))
    with col2:
        st.write(f"**Parking mjesta** ({len(spots_gdf)} redova)")
        st.dataframe(spots_gdf.drop(columns=["geometry"], errors="ignore"))

    # --- SHP slojevi ---
    st.markdown("---")
    st.subheader("SHP slojevi (Geofabrik Serbia → isjeceni na AOI)")

    for layer_name in LAYER_FILES:
        gdf = load_shp_layer(layer_name)
        if gdf.empty:
            st.warning(f"{layer_name}: nema podataka (pokrenite geo_download.py)")
            continue
        with st.expander(f"**{layer_name}** — {len(gdf)} objekata | CRS: {gdf.crs}"):
            display = gdf.drop(columns=["geometry"], errors="ignore").head(50)
            st.dataframe(display)
            st.caption(f"Kolone: {list(gdf.columns)}")

    # --- Join SHP + baza ---
    st.markdown("---")
    st.subheader("Join: Parking mjesta (baza) ⟕ Putevi (Geofabrik) — sjoin_nearest")
    roads_gdf = load_shp_layer("Putevi")
    if not roads_gdf.empty and not spots_gdf.empty:
        try:
            major_roads = roads_gdf.copy()
            if "fclass" in major_roads.columns:
                major_roads = major_roads[major_roads["fclass"].isin(MAJOR_ROAD_CLASSES)]
            road_cols = [c for c in ["name", "fclass"] if c in major_roads.columns] + ["geometry"]
            rename_map = {"name": "naziv_puta"} if "name" in major_roads.columns else {}

            joined = gpd.sjoin_nearest(
                spots_gdf[["spot_number", "zone_name", "city", "spot_type", "status", "geometry"]],
                major_roads[road_cols].rename(columns=rename_map),
                how="left",
                distance_col="dist_stepen",
            )
            joined["dist_m"] = (joined["dist_stepen"] * 111_000).round(1)
            disp_cols = [c for c in ["spot_number", "zone_name", "city", "spot_type", "status", "naziv_puta", "fclass", "dist_m"] if c in joined.columns]
            st.dataframe(joined[disp_cols])
            st.success(
                f"Join uspjesan: {len(joined)} parking mjesta spojena sa "
                f"Geofabrik podacima o putevima (sjoin_nearest)."
            )
        except Exception as e:
            st.warning(f"Join greška: {e}")
    else:
        st.info("Nema SHP podataka. Pokrenite geo_download.py.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.title("🅿️ Pametni sistem za upravljanje parking mestima")
    st.caption("Deo 2 — Python GEO | Geofabrik SHP + PostGIS baza + Streamlit + Folium + GeoPandas")

    # Provjeri da li SHP podaci postoje
    data_ready = CLIPPED_DIR.exists() and any(CLIPPED_DIR.glob("*.shp"))
    if not data_ready:
        st.error("⚠️ SHP podaci nisu pronađeni.")
        st.markdown(
            "Pokrenite u terminalu:\n"
            "```\nuv run geo_download.py\n```\n"
            "Preuzimanje traje ~2–5 min (~100 MB)."
        )
        if st.button("🌐 Preuzmi SHP podatke odmah"):
            with st.spinner("Preuzimanje Serbia SHP sa Geofabrik (~100 MB)..."):
                try:
                    download_data()
                    st.success("Podaci preuzeti! Osvjezite stranicu (F5).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Greška pri preuzimanju: {e}")
        return

    # Sidebar
    base_map, layer_cfg, show_zones = build_sidebar()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🗺️ Mapa", "⬡ Overlay Analize", "🔍 Prostorni Upiti", "📊 DataFrames"]
    )

    with tab1:
        render_map(base_map, layer_cfg, show_zones)

    with tab2:
        render_overlay()

    with tab3:
        render_spatial_queries()

    with tab4:
        render_dataframes()


if __name__ == "__main__":
    main()
