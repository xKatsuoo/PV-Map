"""
vision_pipeline.py — Hauptpipeline der Dachanalyse.

Orchestriert die gesamte Analyse:
1. roof_analyzer — Dachtyp, Ausrichtung, Fläche, Neigung
2. shadow_analyzer — Verschattungsanalyse
3. pv_detector — Erkennung bestehender PV-Anlagen

Ergebnis: Einheitliches Resultat pro Gebäude mit allen Scores.
"""

import json
import logging
from typing import Any, Dict, List, Optional

try:
    from . import roof_analyzer, shadow_analyzer, pv_detector
except ImportError:
    import roof_analyzer, shadow_analyzer, pv_detector  # type: ignore  # noqa: F811

# Logger
logger = logging.getLogger("vision_pipeline")

BuildingDict = Dict[str, Any]
PipelineResult = Dict[str, Any]


# ──────────────────────────────────────────────
# Konstanten
# ──────────────────────────────────────────────

# Gewichtung der Scores für den Gesamt-PV-Eignungsscore
WEIGHTS = {
    "roof_score": 0.35,        # Dachqualität (Typ, Ausrichtung, Fläche, Neigung)
    "shadow_score": 0.25,      # Verschattung
    "pv_score": 0.20,          # Besteht schon eine PV? (invertiert)
    "sunlight_score": 0.20,    # Sonnenstunden
}


def _get_roof_documentation(roof_result: Dict[str, Any]) -> str:
    """Erzeugt eine Textbeschreibung der Dacheigenschaften."""
    roof_type = roof_result["roof_type"]
    orientation = roof_result["orientation_cardinal"]
    pitch = roof_result["pitch_category"]
    area = roof_result["roof_area_m2"]

    docs = {
        "Satteldach": f"Satteldach zeigt nach {orientation}, {pitch} geneigt, ~{area:.0f}m² Dachfläche.",
        "Walmdach": f"Walmdach mit Hauptausrichtung {orientation}, {pitch} geneigt, ~{area:.0f}m².",
        "Pultdach": f"Pultdach mit Ausrichtung {orientation}, {pitch} geneigt, ~{area:.0f}m².",
        "Flachdach": f"Flachdach, ~{area:.0f}m² Fläche, Aufständerung für optimale Ausrichtung möglich.",
        "Mansarddach": f"Mansarddach, Ausrichtung {orientation}, ~{area:.0f}m².",
        "Zeltdach": f"Zeltdach, pyramidal, ~{area:.0f}m².",
        "Kreuzdach": f"Kreuzdach, komplexe Geometrie, ~{area:.0f}m².",
        "unbekannt": f"Dachtyp unbekannt, geschätzte Fläche ~{area:.0f}m².",
    }
    return docs.get(roof_type, f"Dach mit ~{area:.0f}m² Fläche.")


def _get_potential_assessment(roof_result: Dict[str, Any],
                               shadow_result: Dict[str, Any],
                               pv_result: Dict[str, Any]) -> Dict[str, Any]:
    """Erzeugt eine Bewertung des PV-Potenzials mit Handlungsempfehlung."""
    roof_score = roof_result["score"]
    shadow_score = shadow_result["shadow_score"]
    pv_exists = pv_result["existing_pv"]

    if pv_exists:
        potential = "kein_neukunde"
        recommendation = "Bereits PV-Anlage vorhanden. Eventuell Erweiterung oder Modernisierung prüfen."
    elif roof_score >= 70 and shadow_score >= 60:
        potential = "sehr_gut"
        recommendation = "Hervorragend für PV geeignet. Sofort kontaktieren."
    elif roof_score >= 50 and shadow_score >= 40:
        potential = "gut"
        recommendation = "Gut geeignet für PV. In die Route aufnehmen."
    elif roof_score >= 30 and shadow_score >= 25:
        potential = "mittel"
        recommendation = "Bedingt geeignet. Vor Ort prüfen."
    else:
        potential = "schlecht"
        recommendation = "Weniger geeignet. Nur bei Kapazitäten anfahren."

    return {
        "potential": potential,
        "recommendation": recommendation,
    }


# ──────────────────────────────────────────────
# Hauptpipeline
# ──────────────────────────────────────────────

def analyze_building(building: BuildingDict) -> PipelineResult:
    """Führt die vollständige Dachanalyse für ein Gebäude durch.

    Args:
        building: Gebäude-Dict mit 'id', 'geometry', 'tags'.

    Returns:
        PipelineResult mit allen Analyseergebnissen und Gesamtscore.
    """
    building_id = building.get("id", "unknown")

    # 1) Dachanalyse
    roof_result = roof_analyzer.analyze_roof(building)

    # 2) Verschattungsanalyse
    shadow_result = shadow_analyzer.analyze_shadow(building)

    # 3) PV-Erkennung
    pv_result = pv_detector.detect_pv(building)

    # 4) Gesamt-PV-Eignungsscore (0-100)
    roof_weighted = roof_result["score"] * WEIGHTS["roof_score"]
    shadow_weighted = shadow_result["shadow_score"] * WEIGHTS["shadow_score"]
    pv_weighted = pv_result["pv_score"] * WEIGHTS["pv_score"]
    sunlight_weighted = (shadow_result["effective_sunlight_hours"] / 8.0) * 100 * WEIGHTS["sunlight_score"]

    pv_suitability_score = round(
        roof_weighted + shadow_weighted + pv_weighted + sunlight_weighted
    )
    pv_suitability_score = max(0, min(100, pv_suitability_score))

    # 5) Dachbeschreibung
    roof_description = _get_roof_documentation(roof_result)

    # 6) Potenzialbewertung
    assessment = _get_potential_assessment(roof_result, shadow_result, pv_result)

    # 7) Verkaufsargumente generieren
    sales_points = []
    if roof_result["score"] >= 60:
        if roof_result["orientation_cardinal"] == "Süden":
            sales_points.append("Optimale Südausrichtung für maximale PV-Ausbeute")
        elif roof_result["orientation_cardinal"] in ("Südosten", "Südwesten"):
            sales_points.append("Sehr gute Ausrichtung mit nur minimalen Ertragsverlusten")

    if shadow_result["shadow_score"] >= 70:
        sales_points.append("Kaum Verschattung — ideale Bedingungen für PV")

    if roof_result["roof_area_m2"] >= 50:
        sales_points.append(f"Großzügige Dachfläche ({roof_result['roof_area_m2']:.0f}m²)")

    return {
        "building_id": building_id,
        "pv_suitability_score": pv_suitability_score,
        "potential": assessment["potential"],
        "recommendation": assessment["recommendation"],
        "roof_description": roof_description,
        "sales_points": sales_points,
        "details": {
            "roof_analysis": roof_result,
            "shadow_analysis": {
                "shadow_score": shadow_result["shadow_score"],
                "sunlight_hours": shadow_result["effective_sunlight_hours"],
                "building_height": shadow_result["building_height_m"],
            },
            "pv_detection": {
                "existing_pv": pv_result["existing_pv"],
                "confidence": pv_result["confidence"],
            },
            "scores_detail": {
                "roof_weighted": round(roof_weighted, 1),
                "shadow_weighted": round(shadow_weighted, 1),
                "pv_weighted": round(pv_weighted, 1),
                "sunlight_weighted": round(sunlight_weighted, 1),
            },
        },
    }


def analyze_buildings(buildings: List[BuildingDict]) -> List[PipelineResult]:
    """Analysiert mehrere Gebäude.

    Args:
        buildings: Liste von Gebäude-Dicts.

    Returns:
        Liste von PipelineResult, absteigend sortiert nach Score.
    """
    results = [analyze_building(b) for b in buildings]
    results.sort(key=lambda r: r["pv_suitability_score"], reverse=True)
    return results


def analyze_from_geojson(geojson_path: str) -> List[PipelineResult]:
    """Liest Gebäude aus einer GeoJSON-Datei und analysiert sie.

    Args:
        geojson_path: Pfad zur GeoJSON-Datei.

    Returns:
        Liste von PipelineResult.
    """
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    buildings = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})

        if geometry.get("type") != "Polygon":
            continue

        # Koordinaten extrahieren (erster Ring)
        coords = geometry.get("coordinates", [[]])[0]

        # GeoJSON ist [lon, lat], wir erwarten (lon, lat)-Tupel
        coord_tuples = [(c[0], c[1]) for c in coords if len(c) >= 2]

        building = {
            "id": props.get("id", props.get("@id", feature.get("id", "unknown"))),
            "geometry": coord_tuples,
            "tags": props,
        }
        buildings.append(building)

    return analyze_buildings(buildings)


def export_to_json(results: List[PipelineResult], output_path: str) -> None:
    """Exportiert Analyseergebnisse als JSON-Datei."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Ergebnisse exportiert nach: {output_path}")


# ──────────────────────────────────────────────
# CLI-Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test-Gebäude
    test_buildings = [
        {
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
        },
        {
            "id": "test-002",
            "geometry": [
                (6.997, 49.235),
                (6.998, 49.235),
                (6.998, 49.236),
                (6.997, 49.236),
            ],
            "tags": {
                "building": "yes",
                "roof:shape": "flat",
                "building:levels": "3",
                "generator:source": "solar",
            },
        },
        {
            "id": "test-003",
            "geometry": [
                (6.999, 49.237),
                (7.000, 49.237),
                (7.000, 49.238),
                (6.999, 49.238),
            ],
            "tags": {
                "building": "yes",
                "roof:shape": "gabled",
                "building:levels": "1",
                "nearby_trees": "yes",
                "tree_density": "high",
            },
        },
    ]

    print("=== SolarRoute Vision Pipeline Test ===\n")
    results = analyze_buildings(test_buildings)

    for r in results:
        print(f"Gebäude: {r['building_id']}")
        print(f"  Score: {r['pv_suitability_score']}/100")
        print(f"  Potenzial: {r['potential']}")
        print(f"  {'⚠️  PV vorhanden' if r['details']['pv_detection']['existing_pv'] else '✅ Keine PV vorhanden'}")
        print(f"  Dach: {r['roof_description']}")
        print(f"  Empfehlung: {r['recommendation']}")
        if r['sales_points']:
            for sp in r['sales_points']:
                print(f"    💡 {sp}")
        print()

    print(json.dumps(results, indent=2, ensure_ascii=False))