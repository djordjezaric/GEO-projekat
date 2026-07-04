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

import contextily as ctx
import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from shapely.geometry import Point, box
from streamlit_folium import st_folium

from db import get_engine
from geo_download import CLIPPED_DIR, AOI_BBOX, main as download_data

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
    show_spots = st.sidebar.checkbox("Parking mjesta", value=True)

    col1, col2, col3 = st.sidebar.columns(3)
    with col1:
        free_color  = st.color_picker("Slobodna",   "#00C853", key="free_c")
    with col2:
        taken_color = st.color_picker("Zauzeta",    "#D50000", key="taken_c")
    with col3:
        other_color = st.color_picker("Ostalo",     "#FF6D00", key="other_c")

    return base_map, layer_cfg, show_zones, show_spots, free_color, taken_color, other_color


# ---------------------------------------------------------------------------
# Tab 1 — Interaktivna mapa
# ---------------------------------------------------------------------------

def _spot_color(status: str, free_color: str, taken_color: str, other_color: str) -> str:
    return {
        "slobodno":     free_color,
        "zauzeto":      taken_color,
    }.get(status, other_color)


def render_map(base_map, layer_cfg, show_zones, show_spots, free_color, taken_color, other_color):
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

    # Parking zona iz baze
    zones_gdf, spots_gdf = load_parking_data()

    if show_zones:
        fg_z = folium.FeatureGroup(name="Parking zone (baza)", show=True)
        for _, row in zones_gdf.iterrows():
            if row.geometry is None:
                continue
            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                icon=folium.Icon(color="blue", icon="home", prefix="fa"),
                tooltip=row["name"],
                popup=folium.Popup(
                    f"<b>{row['name']}</b><br>"
                    f"Grad: {row['city']}<br>"
                    f"Kapacitet: {row['total_capacity']}<br>"
                    f"Cijena/h: {row['hourly_rate']} din<br>"
                    f"Natkriveno: {'Da' if row['has_covered_spots'] else 'Ne'}",
                    max_width=220,
                ),
            ).add_to(fg_z)
        fg_z.add_to(m)

    if show_spots and not spots_gdf.empty:
        fg_s = folium.FeatureGroup(name="Parking mjesta (baza)", show=True)
        for _, row in spots_gdf.iterrows():
            c = _spot_color(row["status"], free_color, taken_color, other_color)
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=9,
                color=c,
                fill=True,
                fill_color=c,
                fill_opacity=0.85,
                tooltip=f"{row['spot_number']} — {row['status']}",
                popup=folium.Popup(
                    f"<b>Mjesta {row['spot_number']}</b><br>"
                    f"Zona: {row['zone_name']}<br>"
                    f"Grad: {row['city']}<br>"
                    f"Tip: {row['spot_type']}<br>"
                    f"Natkriveno: {'Da' if row['is_covered'] else 'Ne'}<br>"
                    f"Status: <b>{row['status']}</b>",
                    max_width=220,
                ),
            ).add_to(fg_s)
        fg_s.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=580, returned_objects=[])


# ---------------------------------------------------------------------------
# Tab 2 — Overlay Analize (6 tehnika)
# ---------------------------------------------------------------------------

def _basemap(ax, crs_str: str) -> None:
    try:
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, crs=crs_str)
    except Exception:
        pass  # Ako internet nije dostupan, plot ostaje bez podloge


def render_overlay():
    st.header("⬡ Overlay Tehnike")
    st.info(
        "6 prostornih overlay operacija nad parking podacima. "
        "Rasterska podloga: OpenStreetMap tiles via **contextily**."
    )

    zones_gdf, spots_gdf = load_parking_data()
    if spots_gdf.empty:
        st.warning("Nema parking mjesta u bazi.")
        return

    roads_gdf   = load_shp_layer("Putevi")
    landuse_gdf = load_shp_layer("Namena zemljista")

    spots_3857  = spots_gdf.to_crs("EPSG:3857")
    CRS_STR     = "EPSG:3857"

    # --- 1. Buffer ---
    st.subheader("1. Buffer — zona uticaja 400 m oko parking mjesta")
    buf400 = spots_3857.copy()
    buf400["geometry"] = spots_3857.buffer(400)
    buf_union = buf400.dissolve()

    fig, ax = plt.subplots(figsize=(11, 6))
    buf400.plot(ax=ax, alpha=0.25, color="#1565C0", label="Buffer 400 m")
    spots_3857.plot(ax=ax, color="#D50000", markersize=12, zorder=5, label="Parking mjesta")
    _basemap(ax, CRS_STR)
    ax.set_title("Buffer 400 m oko parking mjesta (PostGIS + GeoPandas)")
    ax.legend(); ax.set_axis_off()
    st.pyplot(fig); plt.close()
    st.caption(f"Ukupno {len(buf400)} buffer zona; area union = {buf_union.geometry.area.iloc[0]/1e6:.4f} km²")

    # --- 2. Clip — putevi isjeceni na buffer zonu ---
    st.subheader("2. Clip — putevi unutar 400 m od parking mjesta")
    if not roads_gdf.empty:
        try:
            roads_3857 = roads_gdf.to_crs(CRS_STR)
            major = roads_3857[roads_3857["fclass"].isin(MAJOR_ROAD_CLASSES)] if "fclass" in roads_3857.columns else roads_3857
            clipped_roads = gpd.clip(major, buf_union)
            fig, ax = plt.subplots(figsize=(11, 6))
            buf_union.plot(ax=ax, alpha=0.2, color="#1565C0", label="Buffer zona")
            clipped_roads.plot(ax=ax, color="#B71C1C", linewidth=1.2, label=f"Putevi u zoni ({len(clipped_roads)})")
            spots_3857.plot(ax=ax, color="#F9A825", markersize=12, zorder=5)
            _basemap(ax, CRS_STR)
            ax.set_title("Clip: Putevi (main roads) isjeceni na parking buffer zonu")
            ax.legend(); ax.set_axis_off()
            st.pyplot(fig); plt.close()
            st.caption(f"Isjeceno {len(clipped_roads)} segmenata puta.")
        except Exception as e:
            st.warning(f"Clip greška: {e}")
    else:
        st.info("Nema SHP podataka o putevima. Pokrenite geo_download.py.")

    # --- 3. Intersection (overlay) — presjek buffer zone i namjene zemljista ---
    st.subheader("3. Intersection — presjek buffer zone sa namjenom zemljista")
    if not landuse_gdf.empty:
        try:
            landuse_3857 = landuse_gdf.to_crs(CRS_STR)
            intersection = gpd.overlay(
                buf_union[["geometry"]], landuse_3857[["fclass", "geometry"]], how="intersection"
            )
            fig, ax = plt.subplots(figsize=(11, 6))
            intersection.plot(
                ax=ax, column="fclass", legend=True, alpha=0.6,
                legend_kwds={"loc": "upper right", "fontsize": 7},
            )
            spots_3857.plot(ax=ax, color="black", markersize=10, zorder=5)
            _basemap(ax, CRS_STR)
            ax.set_title("Intersection: Namjena zemljista unutar 400 m od parking mjesta")
            ax.set_axis_off()
            st.pyplot(fig); plt.close()

            if "fclass" in intersection.columns:
                counts = intersection["fclass"].value_counts().reset_index()
                counts.columns = ["Namjena", "Broj podrucja"]
                st.dataframe(counts)
        except Exception as e:
            st.warning(f"Intersection greška: {e}")
    else:
        st.info("Nema SHP podataka o namjeni zemljista. Pokrenite geo_download.py.")

    # --- 4. Union (dissolve) — spajanje buffer zona po gradu ---
    st.subheader("4. Union / Dissolve — parking pokrivanje po gradu")
    try:
        buf_city = spots_3857.copy()
        buf_city["geometry"] = spots_3857.buffer(300)
        city_col = spots_gdf["city"].values
        buf_city["city"] = city_col
        city_union = buf_city.dissolve(by="city").reset_index()

        fig, ax = plt.subplots(figsize=(11, 6))
        city_union.plot(ax=ax, column="city", legend=True, alpha=0.45, cmap="Set2")
        spots_3857.plot(ax=ax, color="black", markersize=10, zorder=5, label="Parking mjesta")
        _basemap(ax, CRS_STR)
        ax.set_title("Dissolve (Union): Parking buffer zone po gradu")
        ax.legend(); ax.set_axis_off()
        st.pyplot(fig); plt.close()

        area_df = city_union[["city", "geometry"]].copy()
        area_df["povrsina_km2"] = area_df.geometry.area / 1e6
        st.dataframe(area_df[["city", "povrsina_km2"]].rename(columns={"city": "Grad", "povrsina_km2": "Pokrivenost (km²)"}))
    except Exception as e:
        st.warning(f"Union greška: {e}")

    # --- 5. Difference — AOI minus parking buffer ---
    st.subheader("5. Difference — oblast bez parking pokrivenosti (500 m)")
    try:
        aoi_gdf = gpd.GeoDataFrame(geometry=[box(*AOI_BBOX)], crs="EPSG:4326").to_crs(CRS_STR)
        buf500   = spots_3857.copy()
        buf500["geometry"] = spots_3857.buffer(500)
        buf500_union = buf500.dissolve()
        diff = gpd.overlay(aoi_gdf[["geometry"]], buf500_union[["geometry"]], how="difference")

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        buf500_union.plot(ax=axes[0], alpha=0.5, color="#1565C0", label="Parking buffer 500 m")
        spots_3857.plot(ax=axes[0], color="red", markersize=12, zorder=5)
        _basemap(axes[0], CRS_STR)
        axes[0].set_title("Parking buffer zona (500 m)"); axes[0].set_axis_off()

        diff.plot(ax=axes[1], alpha=0.5, color="#757575", label="Bez parkinga")
        buf500_union.plot(ax=axes[1], alpha=0.3, color="#1565C0")
        _basemap(axes[1], CRS_STR)
        axes[1].set_title("Difference: Oblast AOI bez parking pokrivenosti")
        axes[1].set_axis_off()

        plt.tight_layout()
        st.pyplot(fig); plt.close()

        total_area  = aoi_gdf.geometry.area.sum()
        park_area   = buf500_union.geometry.area.sum()
        diff_area   = diff.geometry.area.sum()
        st.caption(
            f"AOI: {total_area/1e6:.1f} km² | "
            f"Parking pokrivenost: {park_area/1e6:.4f} km² ({park_area/total_area*100:.2f}%) | "
            f"Bez parkinga: {diff_area/1e6:.1f} km²"
        )
    except Exception as e:
        st.warning(f"Difference greška: {e}")

    # --- 6. Symmetric Difference — NS vs BG ---
    st.subheader("6. Symmetric Difference — parking zone Novi Sad vs Beograd")
    try:
        cities_present = spots_gdf["city"].unique()
        ns = spots_3857[spots_gdf["city"].values == "Novi Sad"]
        bg = spots_3857[spots_gdf["city"].values == "Beograd"]

        if ns.empty or bg.empty:
            st.info("Nema podataka za oba grada (trebaju Novi Sad i Beograd).")
        else:
            ns_buf = ns.copy(); ns_buf["geometry"] = ns.buffer(600)
            bg_buf = bg.copy(); bg_buf["geometry"] = bg.buffer(600)
            ns_union = ns_buf.dissolve()[["geometry"]]
            bg_union = bg_buf.dissolve()[["geometry"]]

            sym_diff = gpd.overlay(ns_union, bg_union, how="symmetric_difference")
            union_all = gpd.overlay(ns_union, bg_union, how="union")

            fig, ax = plt.subplots(figsize=(11, 6))
            union_all.plot(ax=ax, alpha=0.15, color="purple")
            ns_union.plot(ax=ax, alpha=0.4, color="blue", label="Novi Sad buffer")
            bg_union.plot(ax=ax, alpha=0.4, color="red",  label="Beograd buffer")
            sym_diff.plot(ax=ax, alpha=0.6, color="purple", label="Sym. Diff (ekskluzivno)")
            spots_3857.plot(ax=ax, color="black", markersize=10, zorder=5)
            _basemap(ax, CRS_STR)
            ax.set_title("Symmetric Difference: parking zone Novi Sad XOR Beograd")
            ax.legend(); ax.set_axis_off()
            st.pyplot(fig); plt.close()
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

                pois_3857    = pois_gdf.to_crs(CRS_STR)
                within_3857  = pois_within.to_crs(CRS_STR)
                fig, ax = plt.subplots(figsize=(11, 6))
                buf_union_3857.plot(ax=ax, alpha=0.2, color="#1565C0")
                pois_3857.plot(ax=ax, color="gray", markersize=2, alpha=0.4, label="Svi POI")
                within_3857.plot(ax=ax, color="red", markersize=8, zorder=5, label=f"Within ({len(within_3857)})")
                spots_3857.plot(ax=ax, color="#00C853", markersize=10, zorder=6, label="Parking")
                _basemap(ax, CRS_STR)
                ax.set_title("Within: POI unutar 400 m od parking mjesta")
                ax.legend(); ax.set_axis_off()
                st.pyplot(fig); plt.close()
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
            roads_3857 = roads_gdf.to_crs(CRS_STR)
            roads_int_3857 = roads_int.to_crs(CRS_STR)
            st.success(f"Pronađeno {len(roads_int)} segmenata puta koji se sijeku sa parking buffer zonom.")

            fig, ax = plt.subplots(figsize=(11, 6))
            buf_union_3857.plot(ax=ax, alpha=0.2, color="#1565C0")
            roads_3857.plot(ax=ax, color="lightgray", linewidth=0.4, alpha=0.5, label="Ostali putevi")
            roads_int_3857.plot(ax=ax, color="#D50000", linewidth=1.5, label=f"Sijeku parking ({len(roads_int_3857)})")
            spots_3857.plot(ax=ax, color="#00C853", markersize=10, zorder=5)
            _basemap(ax, CRS_STR)
            ax.set_title("Intersects: Putevi koji sijeku parking buffer zonu (400 m)")
            ax.legend(); ax.set_axis_off()
            st.pyplot(fig); plt.close()
        except Exception as e:
            st.warning(f"Intersects greška: {e}")

    # --- 3. Overlaps — zgrade u preklapanju sa parking buffer ---
    st.subheader("3. Overlaps / Intersects — zgrade u parking buffer zoni")
    if not buildings_gdf.empty:
        try:
            mask = buildings_gdf.intersects(buf_geom_4326)
            bld_in_zone = buildings_gdf[mask]
            bld_3857    = buildings_gdf.to_crs(CRS_STR)
            bld_in_3857 = bld_in_zone.to_crs(CRS_STR)
            st.success(f"Pronađeno {len(bld_in_zone)} zgrada koje se sijeku / preklapaju sa parking buffer zonom.")

            fig, ax = plt.subplots(figsize=(11, 6))
            buf_union_3857.plot(ax=ax, alpha=0.15, color="#1565C0")
            bld_3857.plot(ax=ax, color="lightgray", alpha=0.3, label="Sve zgrade")
            bld_in_3857.plot(ax=ax, color="#BF360C", alpha=0.6, label=f"U parking zoni ({len(bld_in_3857)})")
            spots_3857.plot(ax=ax, color="#00C853", markersize=10, zorder=5)
            _basemap(ax, CRS_STR)
            ax.set_title("Overlaps/Intersects: Zgrade u parking buffer zoni (400 m)")
            ax.legend(); ax.set_axis_off()
            st.pyplot(fig); plt.close()
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

        # Vizualizacija
        ns_buf_3857 = (
            gpd.GeoDataFrame(geometry=[ns_center_3857.buffer(2000)], crs="EPSG:3857")
        )
        fig, ax = plt.subplots(figsize=(10, 6))
        ns_buf_3857.plot(ax=ax, alpha=0.15, color="blue", label="2 km od centra NS")
        spots_3857.plot(ax=ax, color="gray", markersize=8, alpha=0.5, label="Sva mjesta")
        free_within_3857 = free_within.to_crs("EPSG:3857")
        if not free_within_3857.empty:
            free_within_3857.plot(ax=ax, color="#00C853", markersize=14, zorder=5, label=f"Slobodna u radijusu ({len(free_within_3857)})")
        _basemap(ax, "EPSG:3857")
        ax.set_title("Distance query: Slobodna parking mjesta unutar 2 km od centra Novog Sada")
        ax.legend(); ax.set_axis_off()
        st.pyplot(fig); plt.close()
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
    base_map, layer_cfg, show_zones, show_spots, free_color, taken_color, other_color = build_sidebar()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(
        ["🗺️ Mapa", "⬡ Overlay Analize", "🔍 Prostorni Upiti", "📊 DataFrames"]
    )

    with tab1:
        render_map(base_map, layer_cfg, show_zones, show_spots, free_color, taken_color, other_color)

    with tab2:
        render_overlay()

    with tab3:
        render_spatial_queries()

    with tab4:
        render_dataframes()


if __name__ == "__main__":
    main()
