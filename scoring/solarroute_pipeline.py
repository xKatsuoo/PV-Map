"""
solarroute_pipeline.py — Hauptpipeline SolarRoute

Integriert alle Module:
1. OSM-Daten einlesen (GIS-Spezialist)
2. Dachanalyse (Vision/ML)
3. PV-Scoring (Gebäude, Straßen, Gebiete)
4. Kostenberechnung
5. Web-App-kompatibles JSON ausgeben

Nutzt Module aus:
  - vision/     (ML/CV Engineer — Dachanalyse)
  - scoring/    (PV/Scoring Engineer — Bewertung)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from typing import Any, Optional

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("solarroute_pipeline")

# ─── Pfade ──────────────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.dirname(_SCRIPT_DIR) if _SCRIPT_DIR.endswith("scoring") else _SCRIPT_DIR
VISION_DIR = os.path.join(SHARED_DIR, "vision")
SCORING_DIR = os.path.join(SHARED_DIR, "scoring")
DATA_DIR = os.path.join(SHARED_DIR, "data")

# Module-Importpfad sicherstellen
for _d in (VISION_DIR, SCORING_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)


# ─── Modul-Imports ─────────────────────────────────────────────────────────

def _import_vision():
    """Importiert Vision-Module (mit Fallback auf Dummy)."""
    try:
        from vision_pipeline import analyze_building, analyze_buildings
        from roof_analyzer import analyze_roof
        from shadow_analyzer import analyze_shadow
        from pv_detector import detect_pv
        return analyze_building, analyze_buildings, analyze_roof, analyze_shadow, detect_pv
    except ImportError:
        logger.warning("Vision-Module nicht verfügbar — verwende Dummy")
        return None, None, None, None, None


def _import_scoring():
    """Importiert Scoring-Module."""
    try:
        from pv_scorer import score_buildings
        from street_ranker import rank_streets
        from area_ranker import rank_areas
        from cost_calculator import calculate_costs_bulk
        return score_buildings, rank_streets, rank_areas, calculate_costs_bulk
    except ImportError as e:
        logger.error(f"Scoring-Module nicht verfügbar: {e}")
        raise


# ─── Daten-Mapper ───────────────────────────────────────────────────────────

def _osm_to_vision_building(osm_building: dict) -> dict:
    """
    Wandelt ein OSM-Gebäude (Format aus osm_pipeline.py) in das von der
    Vision-Pipeline erwartete Format um.
    """
    building_id = osm_building.get("id", osm_building.get("osm_id", "unknown"))

    # Koordinaten: OSM hat "coordinates": {lat, lon} — Vision braucht Polygon
    coords = osm_building.get("coordinates", {})
    lat = coords.get("lat", 0.0) if isinstance(coords, dict) else 0.0
    lon = coords.get("lon", 0.0) if isinstance(coords, dict) else 0.0

    # Approximatives Quadrat um den Punkt (da OSM-Punkt statt Polygon)
    # Baut ein ~area_m2 großes Quadrat um den Gebäudepunkt
    area = osm_building.get("area_m2", 100)
    side = (area ** 0.5) / 2  # Hälfte der Seitenlänge in Meter
    # 1° lon ≈ 111320m * cos(lat), 1° ≈ 111320m
    dlat = side / 111320.0
    dlon = side / (111320.0 * abs(max(-80, min(80, lat))) or 111320.0)

    geometry = [
        (lon - dlon, lat - dlat),
        (lon + dlon, lat - dlat),
        (lon + dlon, lat + dlat),
        (lon - dlon, lat + dlat),
        (lon - dlon, lat - dlat),  # Ring schließen
    ]

    # Tags aus OSM-Daten
    tags = dict(osm_building.get("tags", {}))
    if not tags:
        # Fallback: aus address und building_class
        addr = osm_building.get("address", {})
        if isinstance(addr, dict):
            tags["addr:street"] = addr.get("street", "")
            tags["addr:housenumber"] = addr.get("housenumber", "")
            tags["addr:city"] = addr.get("city", "")
            tags["addr:postcode"] = addr.get("postcode", "")
        tags["building"] = osm_building.get("building_type_osm", "yes")

    return {
        "id": str(building_id),
        "geometry": geometry,
        "tags": tags,
        "_osm_source": osm_building,  # Original-Daten für später
    }


def _vision_to_scoring_building(
    osm_building: dict,
    vision_result: Optional[dict],
) -> dict:
    """
    Erzeugt aus OSM-Daten + Vision-Ergebnis ein Gebäude-Dict für die
    Scoring-Module.

    Fallback auf OSM-Felder, wenn Vision-Ergebnis fehlt.
    """
    # Grunddaten — unterstützt dict-address (OSM) und string-address (test_data)
    addr = osm_building.get("address", {})
    if isinstance(addr, dict):
        street = addr.get("street", "")
        hn = addr.get("housenumber", "")
        city = addr.get("city", osm_building.get("city", ""))
        full_addr = f"{street} {hn}".strip() or osm_building.get("full_address", str(addr))
    elif isinstance(addr, str):
        # String-Adresse: "Saarbrücker Straße 12, 66111 Saarbrücken"
        full_addr = addr
        parts = addr.split(",")
        street = parts[0].strip() if parts else ""
        city = osm_building.get("city", parts[-1].strip().split()[-1] if len(parts) > 1 else "")
        hn = ""
    else:
        street = ""
        hn = ""
        city = osm_building.get("city", "")
        full_addr = osm_building.get("full_address", "")
    # Fallback: city direkt aus dem Gebäude
    if not city:
        city = osm_building.get("city", osm_building.get("stadt", osm_building.get("ortsteil", "")))

    building_id = osm_building.get("id", str(osm_building.get("osm_id", "unknown")))

    # --- Direkte Felder aus der Quelle übernehmen (z. B. test_data) ---
    # Wenn roof_area, orientation usw. direkt gesetzt sind, haben sie
    # Vorrang — das sind bereits Scoring-kompatible Daten.
    direct_fields = {k: osm_building.get(k) for k in
                     ["roof_area", "orientation", "shading", "roof_condition", "building_type", "property"]}
    has_direct_data = any(v is not None for v in direct_fields.values())

    if has_direct_data:
        # Daten sind bereits Scoring-kompatibel — nur minimale Anreicherung
        result = {
            "id": building_id,
            "building_id": building_id,
            "address": full_addr,
            "adresse": full_addr,
            "street": street,
            "city": city,
            **direct_fields,
            "property": osm_building.get("property", {}),
            "coordinates": osm_building.get("coordinates", {}),
            "osm_tags": osm_building.get("tags", {}),
            "building_class": osm_building.get("building_class", ""),
            "estimated_floors": osm_building.get("estimated_floors"),
            "_vision_result": vision_result,
        }
        return result

    # --- OSM-Daten → Scoring-Format konvertieren ---
    # Gebäudetyp-Mapping
    bc = osm_building.get("building_class", "EFH")
    building_type_map = {
        "EFH": "Einfamilienhaus",
        "DHH": "Doppelhaushälfte",
        "RH": "Reihenhaus",
        "MFH": "Mehrfamilienhaus",
    }
    building_type = building_type_map.get(bc, bc)

    # Dachfläche: Vision oder OSM
    if vision_result:
        roof = vision_result.get("details", {}).get("roof_analysis", {})
        roof_area = roof.get("roof_area_m2")
        orientation = roof.get("orientation_cardinal", "")
        # Orientierung Deutsch
        orientation_map = {
            "Norden": "N", "Nordosten": "NO", "Osten": "O",
            "Südosten": "SO", "Süden": "S", "Südwesten": "SW",
            "Westen": "W", "Nordwesten": "NW",
        }
        orientation_short = orientation_map.get(orientation, orientation)
        shadow_score = vision_result.get("details", {}).get("shadow_analysis", {}).get("shadow_score", 70)
        roof_type = roof.get("roof_type", "unbekannt")
        pv_exists = vision_result.get("details", {}).get("pv_detection", {}).get("existing_pv", False)

        # Verschattung in Text umwandeln
        if shadow_score >= 85:
            shading = "keine"
        elif shadow_score >= 65:
            shading = "gering"
        elif shadow_score >= 40:
            shading = "mittel"
        else:
            shading = "stark"

        # Dachzustand aus Dachtyp + pv_exists
        roof_condition = "gut"
        if pv_exists:
            roof_condition = "gut"  # bestehende Anlage = Dach i.O.
        elif roof_type in ("unbekannt", "Flachdach"):
            roof_condition = "mittel"
    else:
        # Fallback: aus OSM-Daten
        roof_area = osm_building.get("area_m2")
        if roof_area and roof_area > 200:
            roof_area = roof_area * 0.6  # grobe Schätzung: Dachfläche < Grundfläche
        orientation_short = "S"  # Default: optimistisch
        shading = "gering"
        roof_condition = "gut"

    # Eigentümer-Wahrscheinlichkeit
    owner_prob = osm_building.get("owner_occupier_probability", 0.7)
    owner_status = "Eigentümer" if owner_prob >= 0.5 else "Mieter"

    return {
        "id": building_id,
        "building_id": building_id,
        "address": full_addr,
        "adresse": full_addr,
        "street": street,
        "city": city,
        "roof_area": roof_area,
        "orientation": orientation_short,
        "shading": shading,
        "roof_condition": roof_condition,
        "building_type": building_type,
        "property": {
            "owner_status": owner_status,
            "lot_size": osm_building.get("area_m2"),
            "electricity_consumption": None,  # unbekannt aus OSM
        },
        "coordinates": osm_building.get("coordinates", {}),
        "osm_tags": osm_building.get("tags", {}),
        "building_class": bc,
        "estimated_floors": osm_building.get("estimated_floors"),
        # Vision-Details durchreichen
        "_vision_result": vision_result,
    }


# ─── Fläche aus OSM extrahieren ─────────────────────────────────────────────

def extract_areas_from_buildings(osm_buildings: list[dict]) -> list[dict]:
    """
    Extrahiert Gebiete/Städte aus den OSM-Daten.
    """
    cities: dict[str, dict] = {}
    for b in osm_buildings:
        addr = b.get("address", {})
        if isinstance(addr, dict):
            city = addr.get("city", "")
        else:
            city = ""
        if not city:
            continue
        if city not in cities:
            cities[city] = {"name": city, "building_count": 0}
        cities[city]["building_count"] += 1

    # Standard-Daten fürs Saarland (können später angereichert werden)
    area_defaults = {
        "Sankt Ingbert": {"ownership_rate": 0.52, "density": 280, "purchasing_power": 104},
        "Saarbrücken": {"ownership_rate": 0.38, "density": 450, "purchasing_power": 98},
        "Homburg": {"ownership_rate": 0.55, "density": 220, "purchasing_power": 108},
        "St. Wendel": {"ownership_rate": 0.62, "density": 130, "purchasing_power": 96},
        "Saarlouis": {"ownership_rate": 0.48, "density": 350, "purchasing_power": 102},
        "Neunkirchen": {"ownership_rate": 0.42, "density": 380, "purchasing_power": 95},
    }

    areas = []
    for city_name, info in cities.items():
        defaults = area_defaults.get(city_name, {})
        areas.append({
            "name": city_name,
            "ownership_rate": defaults.get("ownership_rate", 0.5),
            "density": defaults.get("density", 250),
            "purchasing_power": defaults.get("purchasing_power", 100),
            "building_count": info["building_count"],
        })
    return areas


# ─── Haupt-Pipeline ─────────────────────────────────────────────────────────

def run_solarroute_pipeline(
    osm_buildings: list[dict],
    areas: Optional[list[dict]] = None,
    max_buildings: Optional[int] = None,
    enable_vision: bool = True,
    cost_params: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Führt die gesamte SolarRoute-Pipeline aus.

    Parameter
    ---------
    osm_buildings : list[dict]
        Gebäude im OSM-Format (aus osm_pipeline.py / st_ingbert_buildings.json).
    areas : list[dict], optional
        Gebietsdaten. Falls None, werden sie aus den OSM-Daten extrahiert.
    max_buildings : int, optional
        Begrenzung der Gebäudeanzahl (für Tests).
    enable_vision : bool
        Vision-Pipeline aktivieren (Standard: True).
    cost_params : dict, optional
        Parameter für den cost_calculator.

    Rückgabe
    --------
    dict – vollständige Pipeline-Ergebnisse
    """
    start_time = time.time()
    pipeline_version = "2.0.0"

    # Optional auf max reduzieren
    buildings = osm_buildings
    if max_buildings and len(buildings) > max_buildings:
        logger.info(f"Begrenze auf {max_buildings} Gebäude (von {len(buildings)})")
        buildings = buildings[:max_buildings]

    logger.info(f"Starte Pipeline mit {len(buildings)} Gebäuden")

    # ─── Module importieren ─────────────────────────────────────────────
    analyze_building_fn, analyze_buildings_fn, *_ = _import_vision() or (None,) * 5
    score_buildings_fn, rank_streets_fn, rank_areas_fn, calc_costs_fn = _import_scoring()

    # ─── Schritt 1: Vision / Dachanalyse ────────────────────────────────
    vision_results = []
    if enable_vision and analyze_buildings_fn:
        logger.info("Führe Vision-Dachanalyse durch...")
        # OSM → Vision-Format konvertieren
        vision_inputs = [_osm_to_vision_building(b) for b in buildings]
        try:
            vision_results = analyze_buildings_fn(vision_inputs)
            logger.info(f"Vision: {len(vision_results)} Gebäude analysiert")
        except Exception as e:
            logger.warning(f"Vision-Pipeline fehlgeschlagen: {e}")
            vision_results = []
    else:
        logger.info("Vision deaktiviert oder nicht verfügbar — nutze OSM-Daten direkt")

    # Vision-Ergebnisse nach building_id indexieren
    vision_by_id: dict[str, dict] = {}
    for vr in vision_results:
        vid = vr.get("building_id", "")
        if vid:
            vision_by_id[vid] = vr

    # ─── Schritt 2: OSM + Vision → Scoring-Format ──────────────────────
    logger.info("Wandle Daten in Scoring-Format um...")
    scoring_buildings = []
    for b in buildings:
        bid = str(b.get("id", ""))
        vision_result = vision_by_id.get(bid)
        sb = _vision_to_scoring_building(b, vision_result)
        scoring_buildings.append(sb)

    # ─── Schritt 3: PV-Scoring ──────────────────────────────────────────
    logger.info("Berechne PV-Scores...")
    scored_buildings = score_buildings_fn(scoring_buildings)

    # Merge Scoring-Ergebnisse zurück
    enriched_buildings = []
    for raw, scored in zip(scoring_buildings, scored_buildings):
        merged = {**raw, **scored}
        # Vision-Details nicht doppelt
        if "_vision_result" in merged and merged["_vision_result"]:
            merged["vision"] = merged.pop("_vision_result")
        else:
            merged.pop("_vision_result", None)
        enriched_buildings.append(merged)

    # ─── Schritt 4: Straßen-Ranking ─────────────────────────────────────
    logger.info("Berechne Straßen-Rankings...")
    street_rankings = rank_streets_fn(enriched_buildings)

    # ─── Schritt 5: Gebiets-Ranking ─────────────────────────────────────
    logger.info("Berechne Gebiets-Rankings...")
    if not areas:
        areas = extract_areas_from_buildings(buildings)
    area_rankings = rank_areas_fn(areas, enriched_buildings)

    # ─── Schritt 6: Kostenberechnung ────────────────────────────────────
    logger.info("Berechne Kosten und ROI...")
    cost_calculations = calc_costs_fn(enriched_buildings, cost_params)

    # ─── Ergebnisse ─────────────────────────────────────────────────────
    elapsed = round(time.time() - start_time, 3)

    # Web-App-kompatibles Format
    result = {
        "pipeline": {
            "name": "SolarRoute Pipeline",
            "version": pipeline_version,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "elapsed_seconds": elapsed,
            "buildings_processed": len(enriched_buildings),
            "streets_ranked": len(street_rankings),
            "areas_ranked": len(area_rankings),
        },
        "statistics": _compute_statistics(enriched_buildings, street_rankings, area_rankings),
        "street_rankings": street_rankings,
        "area_rankings": area_rankings,
        "cost_calculations": cost_calculations,
        "buildings": enriched_buildings,
    }

    return result


def _compute_statistics(
    buildings: list[dict],
    street_rankings: list[dict],
    area_rankings: list[dict],
) -> dict[str, Any]:
    """Berechnet zusammenfassende Statistiken."""
    pv_scores = [b.get("pv_score", 0) or 0 for b in buildings if b.get("pv_score") is not None]
    sales_chances = [b.get("sales_chance", 0) or 0 for b in buildings if b.get("sales_chance") is not None]

    stats = {
        "total_buildings": len(buildings),
        "total_streets": len(street_rankings),
        "total_areas": len(area_rankings),
        "pv_score": {
            "avg": round(sum(pv_scores) / len(pv_scores), 1) if pv_scores else 0,
            "min": round(min(pv_scores), 1) if pv_scores else 0,
            "max": round(max(pv_scores), 1) if pv_scores else 0,
        },
        "priority_distribution": {},
        "street_grades": {},
    }

    # Prioritätsverteilung
    for b in buildings:
        p = b.get("priority", "unbekannt")
        stats["priority_distribution"][p] = stats["priority_distribution"].get(p, 0) + 1

    # Straßennoten-Verteilung
    for s in street_rankings:
        g = s.get("grade", "N/A")
        stats["street_grades"][g] = stats["street_grades"].get(g, 0) + 1

    return stats


# ─── Daten-Lese-Funktionen ──────────────────────────────────────────────────

def load_osm_data(path: str) -> list[dict]:
    """Lädt OSM-Gebäudedaten (JSON-Liste)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get("buildings", data.get("features", []))
    return []


def load_test_data() -> dict:
    """Lädt die test_data.json aus dem scoring/-Verzeichnis."""
    path = os.path.join(SCORING_DIR, "test_data.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="SolarRoute — Hauptpipeline für PV-Vertriebssteuerung",
    )
    parser.add_argument("input", nargs="?", help="Pfad zur OSM-Gebäude-JSON")
    parser.add_argument("-o", "--output", help="Ausgabedatei (sonst stdout)")
    parser.add_argument("--max", type=int, default=None, help="Max Gebäude")
    parser.add_argument("--no-vision", action="store_true", help="Vision deaktivieren")
    parser.add_argument("--test", action="store_true", help="Testmodus (test_data.json)")
    parser.add_argument("--pretty", action="store_true", default=True, help="Schöne Ausgabe")

    args = parser.parse_args()

    # Daten laden
    if args.test:
        logger.info("Testmodus — verwende test_data.json")
        data = load_test_data()
        osm_buildings = data.get("buildings", data)
        areas = data.get("areas")
    elif args.input:
        logger.info(f"Lade OSM-Daten von {args.input}")
        osm_buildings = load_osm_data(args.input)
        areas = None
    else:
        # Default: St. Ingbert
        default_path = os.path.join(DATA_DIR, "st_ingbert_buildings.json")
        if os.path.exists(default_path):
            logger.info(f"Lade Standard-Daten von {default_path}")
            osm_buildings = load_osm_data(default_path)
            areas = None
        else:
            logger.error("Keine Eingabedaten. Nutze --test oder gib eine Datei an.")
            sys.exit(1)

    # Pipeline ausführen
    result = run_solarroute_pipeline(
        osm_buildings,
        areas=areas,
        max_buildings=args.max,
        enable_vision=not args.no_vision,
    )

    # Ausgabe
    output = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        logger.info(f"Ergebnis nach {args.output} geschrieben")
    else:
        print(output)


if __name__ == "__main__":
    main()