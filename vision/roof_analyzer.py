"""
roof_analyzer.py — Dachtyp- und Ausrichtungsbestimmung aus Gebäudeumriss.

Analysiert Gebäude-Geometrien aus OSM-Daten und leitet heuristisch ab:
- Dachtyp (Satteldach, Walmdach, Flachdach, Pultdach)
- Dachausrichtung (Himmelsrichtung der Hauptdachfläche)
- Grundfläche und geschätzte Dachfläche
- Geschätzte Dachneigung
- Score (0-100) für PV-Eignung des Dachs
"""

import math
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
# Typdefinition für ein Gebäude
# ──────────────────────────────────────────────
BuildingDict = Dict[str, Any]
# Erwartet mindestens:
#   "id": str
#   "geometry": List[Tuple[float, float]]  — [(lon, lat), ...] Polygonring
#   "tags": Dict[str, str]                 — OSM-Tags

RoofResult = Dict[str, Any]
# Enthält:
#   building_id, roof_type, orientation_deg, orientation_cardinal,
#   ground_area_m2, roof_area_m2, pitch_deg, pitch_category,
#   aspect_ratio, confidence, score


# ──────────────────────────────────────────────
# Heuristische Konstanten
# ──────────────────────────────────────────────

# Typische Neigungswinkel pro Dachtyp (Grad)
ROOF_PITCH_ESTIMATES: Dict[str, Tuple[float, float]] = {
    "Satteldach": (30, 45),   # typisch 30-45°
    "Walmdach": (25, 40),
    "Pultdach": (10, 30),
    "Flachdach": (0, 10),
    "Mansarddach": (30, 60),
    "Sheddach": (15, 30),
    "Kreuzdach": (30, 45),
    "Zeltdach": (30, 50),
    "unbekannt": (20, 40),
}

# Flächenfaktor: Dachfläche ≈ Grundfläche × Faktor (abhängig vom Dachtyp)
ROOF_AREA_FACTOR: Dict[str, float] = {
    "Satteldach": 1.3,
    "Walmdach": 1.25,
    "Pultdach": 1.15,
    "Flachdach": 1.05,
    "Mansarddach": 1.4,
    "Sheddach": 1.2,
    "Kreuzdach": 1.35,
    "Zeltdach": 1.3,
    "unbekannt": 1.2,
}

# Himmelsrichtungen in Grad (Mitte)
CARDINAL_DIRECTIONS: List[Tuple[str, float, float]] = [
    ("Norden", 337.5, 22.5),
    ("Nordosten", 22.5, 67.5),
    ("Osten", 67.5, 112.5),
    ("Südosten", 112.5, 157.5),
    ("Süden", 157.5, 202.5),
    ("Südwesten", 202.5, 247.5),
    ("Westen", 247.5, 292.5),
    ("Nordwesten", 292.5, 337.5),
]

# Optimale Ausrichtungen für PV in Deutschland (nach Süden ausgerichtet)
OPTIMAL_ORIENTATIONS = ["Süden", "Südosten", "Südwesten", "Osten", "Westen"]
OPTIMAL_ORIENTATION_SCORE = {
    "Süden": 100,
    "Südosten": 90,
    "Südwesten": 90,
    "Osten": 70,
    "Westen": 70,
    "Nordosten": 30,
    "Nordwesten": 30,
    "Norden": 10,
}


# ──────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────

def _haversine_distance(
    p1: Tuple[float, float], p2: Tuple[float, float]
) -> float:
    """Abstand in Metern zwischen zwei (lon, lat)-Punkten."""
    R = 6371000  # Erdradius in Metern
    lon1, lat1 = map(math.radians, p1)
    lon2, lat2 = map(math.radians, p2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _polygon_area(coords: List[Tuple[float, float]]) -> float:
    """Berechnet die Grundfläche eines Polygons in Quadratmetern (Shoelace-Formel
       auf Mercator-projizierten Koordinaten)."""
    if len(coords) < 3:
        return 0.0

    # Näherung: lokale Projektion (lon/lat → Meter an Mittelpunkt)
    center_lat = sum(lat for _, lat in coords) / len(coords)
    center_lon = sum(lon for lon, _ in coords) / len(coords)

    # Projektionsfaktoren
    cos_lat = math.cos(math.radians(center_lat))
    m_per_deg_lon = 111320 * cos_lat
    m_per_deg_lat = 111320  # ~111.32 km/Grad

    # In Meter-Koordinaten umrechnen
    m_coords = [
        ((lon - center_lon) * m_per_deg_lon, (lat - center_lat) * m_per_deg_lat)
        for lon, lat in coords
    ]

    # Shoelace-Formel
    area_double = 0.0
    n = len(m_coords)
    for i in range(n):
        x1, y1 = m_coords[i]
        x2, y2 = m_coords[(i + 1) % n]
        area_double += x1 * y2 - x2 * y1

    return abs(area_double) / 2.0


def _longest_edge_direction(coords: List[Tuple[float, float]]) -> float:
    """Ermittelt die Ausrichtung (Azimut in Grad) der längsten Gebäudekante.
       0° = Norden, 90° = Osten, 180° = Süden, 270° = Westen.
       Bei Sattel-/Pultdächern verläuft der First parallel zur Längsseite,
       also ist die Dachfläche orthogonal dazu ausgerichtet.
    """
    if len(coords) < 2:
        return 0.0

    max_len = 0.0
    best_azimuth = 0.0

    n = len(coords)
    for i in range(n):
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        dist = _haversine_distance(p1, p2)

        if dist > max_len:
            max_len = dist
            # Azimut der Kante berechnen (von p1 nach p2)
            lon1, lat1 = p1
            lon2, lat2 = p2
            dlon = math.radians(lon2 - lon1)
            y = math.sin(dlon) * math.cos(math.radians(lat2))
            x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
                 - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon))
            azimuth = math.degrees(math.atan2(y, x))
            best_azimuth = (azimuth + 360) % 360

    # Die Dachfläche eines geneigten Dachs ist orthogonal zur Firstrichtung
    # Firstrichtung = longest edge → Dachfläche zeigt 90° versetzt
    roof_aspect = (best_azimuth + 90) % 360
    return roof_aspect


def _azimuth_to_cardinal(azimuth: float) -> str:
    """Wandelt Azimut in Himmelsrichtung um."""
    for name, start, end in CARDINAL_DIRECTIONS:
        if start <= end:
            if start <= azimuth <= end:
                return name
        else:  # über 360°-Sprung (Norden)
            if azimuth >= start or azimuth <= end:
                return name
    return "unbekannt"


# ──────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────

def analyze_roof(building: BuildingDict) -> RoofResult:
    """Führt die Dachanalyse für ein Gebäude durch.

    Args:
        building: Gebäude-Dict mit 'id', 'geometry' und 'tags'.

    Returns:
        RoofResult mit analysierten Dach-Eigenschaften und Score.
    """
    building_id = building.get("id", "unknown")
    geometry = building.get("geometry", [])
    tags = building.get("tags", {})

    # --- Grundfläche ---
    ground_area = _polygon_area(geometry)

    # --- Dachtyp aus OSM-Tags oder Heuristik ---
    osm_roof_shape = tags.get("roof:shape", "").lower()
    if osm_roof_shape:
        # Mappe OSM roof:shape auf unsere Kategorien
        shape_map = {
            "gabled": "Satteldach",
            "gable": "Satteldach",
            "hipped": "Walmdach",
            "half-hipped": "Krüppelwalmdach",
            "flat": "Flachdach",
            "skillion": "Pultdach",
            "lean-to": "Pultdach",
            "shed": "Pultdach",
            "gambrel": "Mansarddach",
            "mansard": "Mansarddach",
            "dome": "Flachdach",
            "pyramidal": "Zeltdach",
            "tented": "Zeltdach",
            "cross": "Kreuzdach",
            "complex": "unbekannt",
        }
        roof_type = shape_map.get(osm_roof_shape, "unbekannt")
    else:
        # Heuristik basierend auf Gebäudeaspektverhältnis
        if len(geometry) >= 4:
            # Vereinfachte Erkennung: Aspektverhältnis
            coords_2d = [(lon, lat) for lon, lat in geometry]
            # Bounding Box
            min_lon = min(c[0] for c in coords_2d)
            max_lon = max(c[0] for c in coords_2d)
            min_lat = min(c[1] for c in coords_2d)
            max_lat = max(c[1] for c in coords_2d)
            width = _haversine_distance((min_lon, (min_lat + max_lat) / 2),
                                         (max_lon, (min_lat + max_lat) / 2))
            height = _haversine_distance(((min_lon + max_lon) / 2, min_lat),
                                          ((min_lon + max_lon) / 2, max_lat))
            aspect = max(width, height) / max(min(width, height), 0.01)

            # Ländliche/ältere Gebäude → eher Satteldach
            # Städtische/neue → eher Flachdach oder Pultdach
            if aspect > 1.8:
                roof_type = "Satteldach"
            elif aspect < 1.2:
                # Fast quadratisch → Walmdach oder Zeltdach
                roof_type = "Walmdach"
            else:
                roof_type = "Satteldach"
        else:
            roof_type = "unbekannt"

    # --- Ausrichtung ---
    orientation_deg = _longest_edge_direction(geometry)
    orientation_cardinal = _azimuth_to_cardinal(orientation_deg)

    # --- Dachfläche ---
    area_factor = ROOF_AREA_FACTOR.get(roof_type, 1.2)
    roof_area = ground_area * area_factor

    # --- Dachneigung ---
    pitch_range = ROOF_PITCH_ESTIMATES.get(roof_type, (10, 40))
    # Mittelwert der Spanne als Schätzung
    pitch_deg = (pitch_range[0] + pitch_range[1]) / 2

    if pitch_deg <= 10:
        pitch_category = "flach"
    elif pitch_deg <= 25:
        pitch_category = "gering"
    elif pitch_deg <= 40:
        pitch_category = "mittel"
    else:
        pitch_category = "steil"

    # --- Qualitäts-Score (0-100) ---
    # 1) Ausrichtung (max 40 Punkte)
    orient_score = OPTIMAL_ORIENTATION_SCORE.get(orientation_cardinal, 10)

    # 2) Dachfläche (max 25 Punkte)
    if roof_area >= 80:
        area_score = 25
    elif roof_area >= 50:
        area_score = 20
    elif roof_area >= 30:
        area_score = 15
    elif roof_area >= 15:
        area_score = 10
    else:
        area_score = 5

    # 3) Dachneigung (max 20 Punkte) — optimal für PV: 20-45°
    if 20 <= pitch_deg <= 45:
        pitch_score = 20
    elif 10 <= pitch_deg < 20:
        pitch_score = 15
    elif 45 < pitch_deg <= 60:
        pitch_score = 12
    else:
        pitch_score = 5  # Flachdach auch okay mit Aufständerung

    # 4) Dachtyp (max 15 Punkte)
    roof_type_score = {
        "Satteldach": 15,
        "Pultdach": 14,
        "Walmdach": 12,
        "Flachdach": 10,
        "Zeltdach": 10,
        "Mansarddach": 8,
        "Kreuzdach": 7,
        "unbekannt": 5,
    }.get(roof_type, 5)

    score = orient_score + area_score + pitch_score + roof_type_score
    score = max(0, min(100, score))

    # --- Confidence (wie sicher ist die Heuristik?) ---
    if osm_roof_shape:
        confidence = 85 if osm_roof_shape in shape_map else 60
    else:
        confidence = 70  # Heuristik ohne OSM-Tag

    return {
        "building_id": building_id,
        "roof_type": roof_type,
        "orientation_deg": round(orientation_deg, 1),
        "orientation_cardinal": orientation_cardinal,
        "ground_area_m2": round(ground_area, 1),
        "roof_area_m2": round(roof_area, 1),
        "pitch_deg": round(pitch_deg, 1),
        "pitch_category": pitch_category,
        "aspect_ratio": round(roof_area / max(ground_area, 0.01), 2) if ground_area > 0 else 1.0,
        "confidence": confidence,
        "score": score,
        "details": {
            "area_score": area_score,
            "orientation_score": orient_score,
            "pitch_score": pitch_score,
            "roof_type_score": roof_type_score,
        },
    }


def analyze_multiple(buildings: List[BuildingDict]) -> List[RoofResult]:
    """Analysiert mehrere Gebäude."""
    return [analyze_roof(b) for b in buildings]


# ──────────────────────────────────────────────
# CLI-Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # Test mit einem Beispielgebäude
    test_building: BuildingDict = {
        "id": "test-001",
        "geometry": [
            (6.997, 49.236),  # Südwest
            (6.998, 49.236),  # Südost
            (6.998, 49.237),  # Nordost
            (6.997, 49.237),  # Nordwest
        ],
        "tags": {
            "building": "yes",
            "roof:shape": "gabled",
        },
    }

    result = analyze_roof(test_building)
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))