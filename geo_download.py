"""Preuzimanje i priprema SHP podataka za Srbiju (Geofabrik).

Pokretanje: uv run geo_download.py
Rezultat:   data/clipped/*.shp  (isjeceni slojevi na AOI Novi Sad + Beograd)
"""

import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import box

DATA_DIR = Path(__file__).parent / "data"
SHP_DIR = DATA_DIR / "shp"
CLIPPED_DIR = DATA_DIR / "clipped"

GEOFABRIK_URL = "https://download.geofabrik.de/europe/serbia-latest-free.shp.zip"

# Bounding box koji pokriva Novi Sad i Beograd (sa marginom)
AOI_BBOX = (19.70, 44.65, 20.65, 45.40)
AOI_CRS = "EPSG:4326"

LAYERS = [
    "gis_osm_roads_free_1",
    "gis_osm_buildings_a_free_1",
    "gis_osm_landuse_a_free_1",
    "gis_osm_pois_free_1",
    "gis_osm_water_a_free_1",
    "gis_osm_natural_a_free_1",
]


def download_serbia_shp() -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    zip_path = DATA_DIR / "serbia.zip"
    if zip_path.exists():
        print(f"ZIP vec postoji: {zip_path}")
        return zip_path

    print("Preuzimanje Serbia SHP podataka sa Geofabrik (~100 MB)...")
    r = requests.get(GEOFABRIK_URL, stream=True, timeout=600)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    done = 0
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total * 100:.1f}%  ({done // 1_048_576} MB)", end="", flush=True)
    print(f"\nPreuzeto: {zip_path}")
    return zip_path


def extract_shp(zip_path: Path) -> None:
    SHP_DIR.mkdir(parents=True, exist_ok=True)
    if any(SHP_DIR.glob("*.shp")):
        print(f"SHP fajlovi vec postoje u: {SHP_DIR}")
        return
    print("Ekstrakcija SHP fajlova...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(SHP_DIR)
    print("Ekstrakcija zavrsena.")


def clip_layers() -> None:
    CLIPPED_DIR.mkdir(parents=True, exist_ok=True)
    aoi = gpd.GeoDataFrame(geometry=[box(*AOI_BBOX)], crs=AOI_CRS)

    for layer in LAYERS:
        out_path = CLIPPED_DIR / f"{layer}.shp"
        if out_path.exists():
            print(f"  [skip] {layer}")
            continue

        # Geofabrik moze da stavi fajlove u poddirektorijum
        candidates = list(SHP_DIR.rglob(f"{layer}.shp"))
        if not candidates:
            print(f"  [warn] nije pronadjen: {layer}.shp")
            continue
        shp_path = candidates[0]

        print(f"  Isecanje: {layer} ...", end=" ", flush=True)
        gdf = gpd.read_file(shp_path)
        if gdf.crs is None:
            gdf = gdf.set_crs(AOI_CRS)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(AOI_CRS)

        clipped = gpd.clip(gdf, aoi)
        clipped.to_file(out_path)
        print(f"{len(clipped)} objekata sacuvano")


def main() -> None:
    print("=== Preuzimanje SHP podataka za Srbiju (Geofabrik) ===")
    zip_path = download_serbia_shp()
    extract_shp(zip_path)
    print("\nIsecanje slojeva na AOI (Novi Sad + Beograd)...")
    clip_layers()
    print(f"\nSvi podaci su spremni u: {CLIPPED_DIR}")
    print("Pokrenite: streamlit run geo_app.py")


if __name__ == "__main__":
    main()
