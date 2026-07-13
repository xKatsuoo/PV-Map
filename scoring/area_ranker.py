"""
area_ranker.py — Gebiets-Ranking mit Sternenbewertung (★☆☆☆☆ bis ★★★★★)

Analysiert Städte/Ortsteile anhand von:
- Eigentümerquote 25%
- Hausdichte 25%
- PV-Potenzial 25%
- Kaufkraft 25%

Jedes Gebiet erhält 1-5 Sterne.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from typing import Any, Optional


def _stars_from_score(score: float) -> str:
    """Wandelt einen Wert 0-100 in ★☆☆☆☆ bis ★★★★★ um."""
    if score >= 90:
        return "★★★★★"
    elif score >= 75:
        return "★★★★☆"
    elif score >= 55:
        return "★★★☆☆"
    elif score >= 35:
        return "★★☆☆☆"
    else:
        return "★☆☆☆☆"


def _score_ownership_rate(rate: Optional[float]) -> float:
    """
    Bewertet die Eigentümerquote (0-100).
    Höhere Eigentumsquote = mehr Entscheidungsfreiheit für PV.
    """
    if rate is None:
        return 60.0
    return min(100.0, rate * 100.0)  # rate als 0..1 oder Prozentangabe


def _score_density(density: Optional[float]) -> float:
    """
    Bewertet die Hausdichte (Gebäude pro km²).
    Mittlere Dichte = ideal (genug Häuser, aber auch Platz für PV).
    """
    if density is None:
        return 60.0
    d = float(density)
    if d < 50:
        return 30.0  # sehr dünn besiedelt
    elif d < 150:
        return 60.0
    elif d < 400:
        return 90.0  # ideal für Door-to-Door
    elif d < 800:
        return 80.0
    else:
        return 60.0  # zu dicht (viele MFH)


def _score_pv_potential(avg_pv_score: Optional[float]) -> float:
    """Bewertet das durchschnittliche PV-Potenzial der Gebäude."""
    if avg_pv_score is None:
        return 50.0
    return min(100.0, float(avg_pv_score))


def _score_purchasing_power(index: Optional[float]) -> float:
    """
    Bewertet die Kaufkraft (0-100).
    Höhere Kaufkraft = höhere Wahrscheinlichkeit für Investition.
    """
    if index is None:
        return 60.0
    i = float(index)
    # Typischerweise als Index (Deutschland=100)
    if i < 80:
        return 30.0
    elif i < 95:
        return 55.0
    elif i < 110:
        return 80.0
    elif i < 130:
        return 90.0
    else:
        return 100.0


def rank_areas(
    areas: list[dict],
    buildings: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Bewertet Gebiete/Städte/Ortsteile.

    Parameter
    ---------
    areas : list[dict]
        Liste von Gebiets-Dicts mit:
        - name (str) — Name der Stadt / des Ortsteils
        - ownership_rate (float, optional) — Eigentümerquote (0-1 oder 0-100)
        - density (float, optional) — Hausdichte pro km²
        - purchasing_power (float, optional) — Kaufkraftindex (DE=100)
        - buildings (list[dict], optional) — Gebäude im Gebiet
    buildings : list[dict], optional
        Falls areas keine Gebäude enthalten, können sie separat übergeben werden.
        Jedes Gebäude-Dict sollte 'city'/'stadt' und 'pv_score' enthalten.

    Rückgabe
    --------
    list[dict] — sortiert nach Gesamtscore, mit Sternen.
    """
    # Gebäude nach Gebiet gruppieren (falls separat übergeben)
    buildings_by_area: dict[str, list[dict]] = defaultdict(list)
    if buildings:
        for b in buildings:
            area_name = b.get("city") or b.get("stadt") or b.get("ortsteil") or ""
            if area_name:
                buildings_by_area[area_name].append(b)

    results = []
    for area in areas:
        name = area.get("name") or area.get("city") or area.get("stadt") or "Unbekannt"

        # Gebäude aus area oder aus separater Liste
        area_buildings = area.get("buildings", []) or buildings_by_area.get(name, [])

        # PV-Potenzial aus Gebäuden berechnen
        pv_scores = [
            b.get("pv_score", 50)
            for b in area_buildings
            if isinstance(b.get("pv_score"), (int, float))
        ]
        avg_pv_score = sum(pv_scores) / len(pv_scores) if pv_scores else None

        # Einzelfaktor-Scores
        ownership_score = _score_ownership_rate(area.get("ownership_rate"))
        density_score = _score_density(area.get("density"))
        pv_potential_score = _score_pv_potential(avg_pv_score)
        purchasing_score = _score_purchasing_power(area.get("purchasing_power"))

        # Gewichteter Gesamtscore (je 25%)
        total_score = (
            ownership_score * 0.25
            + density_score * 0.25
            + pv_potential_score * 0.25
            + purchasing_score * 0.25
        )

        results.append({
            "area_name": name,
            "total_score": round(total_score, 1),
            "stars": _stars_from_score(total_score),
            "details": {
                "ownership_rate_score": round(ownership_score, 1),
                "density_score": round(density_score, 1),
                "pv_potential_score": round(pv_potential_score, 1),
                "purchasing_power_score": round(purchasing_score, 1),
            },
            "building_count": len(area_buildings),
            "avg_building_pv_score": round(avg_pv_score, 1) if avg_pv_score else None,
        })

    results.sort(key=lambda r: r["total_score"], reverse=True)
    return results


# ─── CLI / Demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    areas = data if isinstance(data, list) else data.get("areas", [])
    buildings = data.get("buildings") if isinstance(data, dict) else None

    result = rank_areas(areas, buildings)
    print(json.dumps(result, ensure_ascii=False, indent=2))