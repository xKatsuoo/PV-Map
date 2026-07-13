"""
shadow_analyzer.py — Verschattungsanalyse (Heuristik basierend auf Umgebung).

Analysiert potenzielle Verschattungsquellen für ein Gebäude anhand von:
- OSM-Tags der Umgebung (Bäume, Gebäudehöhen, Wälder)
- Gebäudeform/-höhe (Eigenverschattung bei komplexen Dächern)
- Nähe zu höheren Strukturen

Gibt einen Verschattungs-Score (0-100) aus:
  - 0 = stark verschattet (schlecht für PV)
  - 100 = keine Verschattung (optimal für PV)
"""

import math
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import roof_analyzer
except ImportError:
    import roof_analyzer  # noqa: F811 — direct execution fallback


BuildingDict = Dict[str, Any]
ShadowResult = Dict[str, Any]


# ──────────────────────────────────────────────
# Konstanten
# ──────────────────────────────────────────────

# Annahme: Standard-Gebäudehöhe pro Stockwerk (Meter)
DEFAULT_FLOOR_HEIGHT = 3.0

# Schattenwurf-Winkel der Sonne zur Wintersonnenwende (Mittag) in Deutschland (ca. 15°)
# Für konservative PV-Verschattungsanalyse
SUN_ELEVATION_WINTER_MIN = 15.0  # Grad

# Pufferabstände für Verschattungsquellen (Meter)
TREE_SHADOW_BUFFER = 15.0        # Bäume werfen bis zu 15m Schatten
TALL_BUILDING_SHADOW_BUFFER = 25.0  # Höhere Gebäude werfen weiter Schatten
WATER_BODY_BUFFER = 0.0          # Keine direkte Verschattung


# ──────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────

def _estimate_building_height(building: BuildingDict) -> float:
    """Schätzt die Gebäudehöhe aus OSM-Tags."""
    tags = building.get("tags", {})

    # Direkte Höhenangabe
    height_str = tags.get("height", "")
    if height_str:
        try:
            return float(height_str.replace(" m", "").replace("m", "").strip())
        except (ValueError, AttributeError):
            pass

    # Stockwerke
    levels_str = tags.get("building:levels", "")
    if levels_str:
        try:
            levels = int(levels_str)
            return levels * DEFAULT_FLOOR_HEIGHT
        except (ValueError, AttributeError):
            pass

    # Default: 2-geschossiges Einfamilienhaus
    return 2 * DEFAULT_FLOOR_HEIGHT  # 6m


def _get_nearby_features(building: BuildingDict) -> Dict[str, Any]:
    """Extrahiert Informationen über nahegelegene Verschattungsquellen aus OSM-Tags.
    
    In der initialen Heuristik-Version nutzen wir die Tags des Gebäudes selbst
    sowie Informationen aus dem Kontext (der später von der GIS-Pipeline kommt).
    """
    tags = building.get("tags", {})
    
    features = {
        "nearby_trees": tags.get("nearby_trees", "no") == "yes",
        "nearby_forest": tags.get("nearby_forest", "no") == "yes",
        "nearby_tall_buildings": tags.get("nearby_tall_buildings", "no") == "yes",
        "nearby_water": tags.get("nearby_water", "no") == "yes",
        "tree_density": tags.get("tree_density", "low"),  # low, medium, high
        "urban_density": tags.get("urban_density", "low"),  # low, medium, high
    }
    return features


def _calculate_sunlight_hours(orientation_cardinal: str, roof_type: str) -> float:
    """Schätzt die täglichen Sonnenstunden basierend auf Dachausrichtung und -typ.
    
    Vereinfachtes Modell für Deutschland (Saarland, ~49°N).
    """
    # Basis-Sonnenstunden (volle Südlage, optimal)
    base_hours = {
        "Süden": 6.5,
        "Südosten": 6.0,
        "Südwesten": 6.0,
        "Osten": 5.0,
        "Westen": 5.0,
        "Nordosten": 3.0,
        "Nordwesten": 3.0,
        "Norden": 2.0,
        "unbekannt": 4.0,
    }

    hours = base_hours.get(orientation_cardinal, 4.0)

    # Flachdächer bekommen etwas mehr (Rundumsicht)
    if roof_type == "Flachdach":
        hours = max(hours, 5.0)

    return hours


# ──────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────

def analyze_shadow(building: BuildingDict) -> ShadowResult:
    """Führt die Verschattungsanalyse für ein Gebäude durch.

    Args:
        building: Gebäude-Dict mit 'id', 'geometry', 'tags'.

    Returns:
        ShadowResult mit Verschattungsanalyse und Score.
    """
    building_id = building.get("id", "unknown")
    geometry = building.get("geometry", [])
    tags = building.get("tags", {})

    # Gebäudehöhe
    building_height = _estimate_building_height(building)

    # Umgebungsinformationen
    features = _get_nearby_features(building)

    # Ausrichtung aus der Dachanalyse
    roof_result = roof_analyzer.analyze_roof(building)
    orientation = roof_result["orientation_cardinal"]
    roof_type = roof_result["roof_type"]

    # --- Verschattungs-Score (0-100, 100 = kein Schatten) ---

    # 1) Umgebungs-Verschattung (max 50 Punkte)
    env_penalty = 0

    if features["nearby_trees"]:
        env_penalty += 15
    if features["nearby_forest"]:
        env_penalty += 25
    if features["nearby_tall_buildings"]:
        env_penalty += 20

    # Baumdichte
    if features["tree_density"] == "high":
        env_penalty += 10
    elif features["tree_density"] == "medium":
        env_penalty += 5

    # Städtische Dichte (mehr Schatten durch Nachbargebäude)
    if features["urban_density"] == "high":
        env_penalty += 15
    elif features["urban_density"] == "medium":
        env_penalty += 8

    env_penalty = min(env_penalty, 50)
    env_score = 50 - env_penalty

    # 2) Ausrichtungs-Schatten (max 30 Punkte)
    orient_shadow = {
        "Süden": 30,
        "Südosten": 28,
        "Südwesten": 28,
        "Osten": 24,
        "Westen": 24,
        "Nordosten": 15,
        "Nordwesten": 15,
        "Norden": 10,
        "unbekannt": 20,
    }
    orient_score = orient_shadow.get(orientation, 20)

    # 3) Dachtyp-Schatten (max 20 Punkte)
    # Flachdächer: weniger Eigenverschattung
    # Komplexe Dächer (Gauben, Kreuzdächer): mehr Eigenverschattung
    roof_shadow_score = {
        "Flachdach": 20,
        "Pultdach": 18,
        "Satteldach": 16,
        "Walmdach": 16,
        "Zeltdach": 14,
        "Mansarddach": 12,
        "Kreuzdach": 10,
        "unbekannt": 14,
    }
    roof_score = roof_shadow_score.get(roof_type, 14)

    # Gesamtscore
    shadow_score = env_score + orient_score + roof_score
    shadow_score = max(0, min(100, shadow_score))

    # Sonnenstunden-Schätzung
    sunlight_hours = _calculate_sunlight_hours(orientation, roof_type)

    # Abzüge durch Verschattung
    shadow_factor = 1.0 - (100 - shadow_score) / 200  # 1.0 = kein Abzug, 0.5 = max Abzug
    effective_sunlight = sunlight_hours * shadow_factor

    return {
        "building_id": building_id,
        "shadow_score": shadow_score,
        "sunlight_hours_estimate": round(sunlight_hours, 1),
        "effective_sunlight_hours": round(effective_sunlight, 1),
        "building_height_m": round(building_height, 1),
        "environment_penalty": env_penalty,
        "nearby_features": features,
        "details": {
            "env_score": env_score,
            "orientation_shadow_score": orient_score,
            "roof_type_shadow_score": roof_score,
            "shadow_factor": round(shadow_factor, 3),
        },
    }


def analyze_multiple(buildings: List[BuildingDict]) -> List[ShadowResult]:
    """Analysiert mehrere Gebäude."""
    return [analyze_shadow(b) for b in buildings]


# ──────────────────────────────────────────────
# CLI-Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    test_building: BuildingDict = {
        "id": "test-001",
        "geometry": [
            (6.997, 49.236),
            (6.998, 49.236),
            (6.998, 49.237),
            (6.997, 49.237),
        ],
        "tags": {
            "building": "yes",
            "roof:shape": "gabled",
            "building:levels": "2",
        },
    }

    result = analyze_shadow(test_building)
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))