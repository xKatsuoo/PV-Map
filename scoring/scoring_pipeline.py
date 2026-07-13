"""
scoring_pipeline.py — Hauptpipeline für SolarRoute-Scoring

Führt alle Module zusammen:
1. pv_scorer — PV-Potenzial pro Gebäude
2. street_ranker — Straßen-Ranking
3. area_ranker — Gebiets-Ranking
4. cost_calculator — Kosten und Angebote

Akzeptiert rohe Gebäudedaten und gibt vollständige Scoring-Ergebnisse aus.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Optional

from pv_scorer import score_buildings
from street_ranker import rank_streets
from area_ranker import rank_areas
from cost_calculator import calculate_costs_bulk


def run_pipeline(
    raw_buildings: list[dict],
    areas: Optional[list[dict]] = None,
    cost_params: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Führt die gesamte Scoring-Pipeline aus.

    Parameter
    ---------
    raw_buildings : list[dict]
        Liste roher Gebäude-Daten (vor dem Scoring).
        Jedes Dict sollte enthalten:
        - id / building_id (optional)
        - address / adresse
        - roof_area (float)
        - orientation (str)
        - shading (float|str)
        - roof_condition (str)
        - building_type (str)
        - property (dict)
        - city / stadt (optional, für Area-Ranking)
    areas : list[dict], optional
        Gebietsdaten für das Area-Ranking.
        Falls nicht angegeben, werden Gebiete aus den Gebäuden extrahiert.
    cost_params : dict, optional
        Parameter für den cost_calculator.

    Rückgabe
    --------
    dict mit:
        - pipeline_info: Metadaten zur Ausführung
        - buildings: Liste bewerteter Gebäude
        - street_rankings: Straßen-Rankings
        - area_rankings: Gebiets-Rankings
        - cost_calculations: Kostenberechnungen
    """
    start_time = time.time()
    pipeline_version = "1.0.0"

    # ─── Schritt 1: Gebäude-Scoring ──────────────────────────────────────
    scored_buildings = score_buildings(raw_buildings)

    # ─── Schritt 2: Straßen-Ranking ──────────────────────────────────────
    # Kombiniere Rohdaten mit Scores
    enriched_buildings = []
    for raw, scored in zip(raw_buildings, scored_buildings):
        enriched = {**raw, **scored}
        enriched_buildings.append(enriched)

    street_rankings = rank_streets(enriched_buildings)

    # ─── Schritt 3: Gebiets-Ranking ──────────────────────────────────────
    if not areas:
        # Extrahiere Gebiete aus Gebäuden
        area_names: set[str] = set()
        for b in enriched_buildings:
            city = b.get("city") or b.get("stadt") or b.get("ortsteil") or ""
            if city:
                area_names.add(city)
        areas = [{"name": name} for name in sorted(area_names)]

    area_rankings = rank_areas(areas, enriched_buildings)

    # ─── Schritt 4: Kostenberechnung ─────────────────────────────────────
    cost_calculations = calculate_costs_bulk(enriched_buildings, cost_params)

    # ─── Ergebnisse ──────────────────────────────────────────────────────
    elapsed = round(time.time() - start_time, 3)

    return {
        "pipeline_info": {
            "version": pipeline_version,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "buildings_processed": len(raw_buildings),
            "streets_ranked": len(street_rankings),
            "areas_ranked": len(area_rankings),
            "elapsed_seconds": elapsed,
        },
        "buildings": enriched_buildings,
        "street_rankings": street_rankings,
        "area_rankings": area_rankings,
        "cost_calculations": cost_calculations,
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _parse_cli():
    """Einfacher CLI-Parser für die Pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="SolarRoute — Scoring-Pipeline für PV-Vertrieb"
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Pfad zur Eingabe-JSON-Datei (sonst stdin)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Pfad zur Ausgabe-JSON-Datei (sonst stdout)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Schöne JSON-Ausgabe (Standard: True)",
    )
    parser.add_argument(
        "--params",
        help="Pfad zu JSON mit cost_params",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_cli()

    # Eingabe lesen
    if args.input:
        with open(args.input, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = json.load(sys.stdin)

    # Eingabe kann ein Dict mit 'buildings' sein oder direkt eine Liste
    if isinstance(raw, dict):
        raw_buildings = raw.get("buildings", [])
        areas = raw.get("areas")
    else:
        raw_buildings = raw
        areas = None

    cost_params = None
    if args.params:
        with open(args.params, encoding="utf-8") as f:
            cost_params = json.load(f)

    # Pipeline ausführen
    result = run_pipeline(raw_buildings, areas, cost_params)

    # Ausgabe
    output = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Pipeline-Ergebnis nach {args.output} geschrieben.")
    else:
        print(output)