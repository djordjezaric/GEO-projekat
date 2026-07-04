"""
ml_detect.py – YOLOv8 detekcija vozila radi odredjivanja slobodnih parking mjesta.
"""

import sys
import os
from pathlib import Path

_rasterio_proj = Path(sys.executable).parent.parent / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _rasterio_proj.exists():
    os.environ["PROJ_LIB"]  = str(_rasterio_proj)
    os.environ["PROJ_DATA"] = str(_rasterio_proj)

import numpy as np
import cv2
from ultralytics import YOLO
from datetime import datetime

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

_model: YOLO | None = None


def get_model() -> YOLO:
    global _model
    if _model is None:
        _model = YOLO(str(Path(__file__).parent / "yolov8n.pt"))
    return _model


def detect_parking_availability(
    image: np.ndarray,
    image_source: str,
    zone_lon: float,
    zone_lat: float,
    total_capacity: int,
    conf_threshold: float = 0.25,
) -> dict:
    """
    Detektuje vozila i racuna slobodna parking mjesta.

    Vraca dict:
        n_vehicles   – broj detektovanih vozila (zauzeta mjesta)
        n_free       – broj slobodnih mjesta
        total        – ukupan kapacitet zone
        detections   – lista dict-ova za svako zauzeto mjesto
        free_spots   – lista dict-ova za slobodna mjesta
        annotated    – slika sa oznakama (BGR numpy array)
    """
    model   = get_model()
    results = model(image, conf=conf_threshold, verbose=False)[0]

    # ── Filtriraj samo vozila ──────────────────────────────────────────────
    vehicle_boxes = [b for b in results.boxes if int(b.cls[0]) in VEHICLE_CLASSES]
    n_vehicles    = len(vehicle_boxes)
    n_free        = max(0, total_capacity - n_vehicles)
    now           = datetime.now()

    # ── GPS: rasporedjujemo tacke oko centroida zone (±0.0003° ≈ ±25 m) ──
    rng = np.random.default_rng(int(now.timestamp()) % 2**31)

    def jitter(n: int, spread: float = 0.0003) -> list[tuple[float, float]]:
        lons = zone_lon + rng.uniform(-spread, spread, n)
        lats = zone_lat + rng.uniform(-spread, spread, n)
        return list(zip(lons.tolist(), lats.tolist()))

    occ_coords  = jitter(n_vehicles)
    free_coords = jitter(n_free, spread=0.0004)

    detections = []
    for i, box in enumerate(vehicle_boxes):
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        conf   = float(box.conf[0])
        cls_id = int(box.cls[0])
        lon, lat = occ_coords[i]
        detections.append({
            "image_source":  image_source,
            "detected_at":   now,
            "status":        "zauzeto",
            "confidence":    round(conf, 4),
            "vehicle_class": VEHICLE_CLASSES[cls_id],
            "bbox_x1": x1, "bbox_y1": y1, "bbox_x2": x2, "bbox_y2": y2,
            "img_width":  image.shape[1],
            "img_height": image.shape[0],
            "lon": round(lon, 6),
            "lat": round(lat, 6),
            "notes":    "",
            "verified": False,
        })

    free_spots = []
    for i in range(n_free):
        lon, lat = free_coords[i]
        free_spots.append({
            "image_source":  image_source,
            "detected_at":   now,
            "status":        "slobodno",
            "confidence":    1.0,
            "vehicle_class": "none",
            "bbox_x1": None, "bbox_y1": None, "bbox_x2": None, "bbox_y2": None,
            "img_width":  image.shape[1],
            "img_height": image.shape[0],
            "lon": round(lon, 6),
            "lat": round(lat, 6),
            "notes":    "Slobodno mjesto – nije detektovano vozilo",
            "verified": False,
        })

    # ── Annotirana slika ───────────────────────────────────────────────────
    annotated = image.copy()
    color_map = {"car": (0, 200, 0), "truck": (0, 0, 220),
                 "bus": (220, 140, 0), "motorcycle": (200, 0, 200)}
    for d in detections:
        x1, y1, x2, y2 = d["bbox_x1"], d["bbox_y1"], d["bbox_x2"], d["bbox_y2"]
        color = color_map.get(d["vehicle_class"], (128, 128, 128))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{d['vehicle_class']} {d['confidence']:.0%}"
        cv2.putText(annotated, label, (x1, max(y1 - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # Overlay statistike na slici
    h, w = annotated.shape[:2]
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w, 52), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, annotated, 0.45, 0, annotated)
    cv2.putText(annotated,
                f"Zauzeto: {n_vehicles}  |  Slobodno: {n_free}  |  Ukupno: {total_capacity}",
                (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)

    return {
        "n_vehicles":  n_vehicles,
        "n_free":      n_free,
        "total":       total_capacity,
        "detections":  detections,
        "free_spots":  free_spots,
        "annotated":   annotated,
    }
