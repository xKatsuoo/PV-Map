"""
pv_detector.py — Erkennung bestehender PV-Anlagen (Heuristik/Platzhalter).

Erkennt bestehende Photovoltaik-Anlagen auf Dächern.

Aktuelle Version: Heuristik basierend auf OSM-Tags.
Zukünftige Version: Satellitenbildanalyse mit Computer Vision (YOLO/Segment Anything).
"""

from typing import Any, Dict, List, Optional

BuildingDict = Dict[str, Any]
PVResult = Dict[str, Any]


# ──────────────────────────────────────────────
# OSM-Tag-Mapping für PV-Erkennung
# ──────────────────────────────────────────────

PV_TAGS = {
    "generator:source": "solar",
    "generator:type": "photovoltaic",
    "power": "generator",
    "solar": "yes",
    "solar:modules": None,  # Anzahl Module
    "solar:panels": None,
}

# Geschätzte Modulleistung pro m² (Watt)
WATT_PER_SQM = 200  # Typischer Wert für Standardmodule (2024)


def _check_osm_pv_tags(tags: Dict[str, str]) -> Dict[str, Any]:
    """Prüft, ob OSM-Tags auf eine bestehende PV-Anlage hinweisen."""
    has_pv = False
    confidence = "high"
    details = []

    # Generator-Tags prüfen
    if tags.get("generator:source") == "solar":
        has_pv = True
        details.append("OSM-Tag: generator:source=solar")

    if tags.get("generator:type") == "photovoltaic":
        has_pv = True
        details.append("OSM-Tag: generator:type=photovoltaic")

    if tags.get("power") == "generator" and tags.get("generator:source") == "solar":
        has_pv = True
        details.append("OSM-Tag: power=generator + generator:source=solar")

    if tags.get("solar") == "yes":
        has_pv = True
        details.append("OSM-Tag: solar=yes")

    # Wenn nur solar:modules/solar:panels vorhanden, auch erkennen
    if tags.get("solar:modules") or tags.get("solar:panels"):
        has_pv = True
        details.append("OSM-Tag: solar:modules/solar:panels vorhanden")

    if not has_pv:
        return {
            "has_pv": False,
            "confidence": "high",  # OSM hat keine PV markiert
            "detection_method": "osm_tags",
            "details": "Keine PV-Anlage in OSM-Tags gefunden",
        }

    return {
        "has_pv": True,
        "confidence": confidence,
        "detection_method": "osm_tags",
        "details_detection": details,
    }


# ──────────────────────────────────────────────
# Öffentliche API
# ──────────────────────────────────────────────

def detect_pv(building: BuildingDict) -> PVResult:
    """Erkennt bestehende PV-Anlagen auf einem Gebäude.

    Args:
        building: Gebäude-Dict mit 'id', 'geometry', 'tags'.

    Returns:
        PVResult mit Erkennungsergebnissen und Score.
    """
    building_id = building.get("id", "unknown")
    geometry = building.get("geometry", [])
    tags = building.get("tags", {})

    # --- OSM-Tag-basierte Erkennung ---
    osm_check = _check_osm_pv_tags(tags)

    if osm_check["has_pv"]:
        # PV vorhanden → negativer Einfluss (kein Neukunden-Potenzial)
        # Aber: Erweiterung/Nachrüstung könnte möglich sein
        pv_capacity = 0  # Unbekannt ohne Satellitenbild
        module_count = 0

        # Versuche Modulanzahl aus Tags zu extrahieren
        try:
            module_count = int(tags.get("solar:modules", tags.get("solar:panels", "0")))
        except (ValueError, TypeError):
            pass

        pv_score = 0  # Kein Potenzial für Neuanlage
        pv_confidence = 0.9 if osm_check["confidence"] == "high" else 0.6

    else:
        # Keine PV gefunden → Potenzial für Neuinstallation
        pv_score = 100
        pv_confidence = 0.3  # Niedrige Konfidenz ohne Satellitenbild
        module_count = 0
        pv_capacity = 0

    return {
        "building_id": building_id,
        "existing_pv": osm_check["has_pv"],
        "pv_score": pv_score,
        "confidence": pv_confidence,
        "detection_method": osm_check["detection_method"],
        "module_count_estimated": module_count,
        "capacity_kw_estimated": round(pv_capacity / 1000, 2) if pv_capacity > 0 else 0.0,
        "details": osm_check.get("details", osm_check.get("details_detection", "")),
    }


def detect_multiple(buildings: List[BuildingDict]) -> List[PVResult]:
    """Erkennt PV-Anlagen auf mehreren Gebäuden."""
    return [detect_pv(b) for b in buildings]


# ──────────────────────────────────────────────
# Platzhalter: Zukünftige Satellite-Image-Erkennung
# ──────────────────────────────────────────────

def detect_pv_from_image(
    building: BuildingDict,
    image_path: str,
) -> PVResult:
    """Zukünftig: PV-Erkennung aus Satellitenbild.

    Args:
        building: Gebäude-Dict
        image_path: Pfad zum Satellitenbild

    Returns:
        PVResult

    Hinweis: Noch nicht implementiert — dient als Platzhalter für
    die Integration von YOLO/Segment-Anything-basierter Erkennung.
    """
    # TODO: Implementierung mit YOLOv8 oder Segment Anything
    # Voraussetzung: Satellitenbild-Chips pro Gebäude
    raise NotImplementedError(
        "Satellitenbild-basierte PV-Erkennung ist noch nicht implementiert. "
        "Verwenden Sie detect_pv() für die OSM-Heuristik."
    )


# ──────────────────────────────────────────────
# CLI-Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    test_no_pv: BuildingDict = {
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
        },
    }

    test_with_pv: BuildingDict = {
        "id": "test-002",
        "geometry": [
            (6.997, 49.236),
            (6.998, 49.236),
            (6.998, 49.237),
            (6.997, 49.237),
        ],
        "tags": {
            "building": "yes",
            "roof:shape": "gabled",
            "generator:source": "solar",
            "generator:type": "photovoltaic",
        },
    }

    import json
    print("=== Ohne PV ===")
    print(json.dumps(detect_pv(test_no_pv), indent=2, ensure_ascii=False))
    print("\n=== Mit PV ===")
    print(json.dumps(detect_pv(test_with_pv), indent=2, ensure_ascii=False))