"""
street_ranker.py — Straßen-Ranking mit Bewertung A+ bis D

Gruppiert Gebäude nach Straßen, berechnet Kennzahlen und bewertet jede Straße.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any


def _grade_street(avg_score: float, suitable_pct: float) -> str:
    """
    Berechnet die Straßenbewertung A+ bis D.
    """
    # Kombinierter Index: Gewichtung 60% avg_score, 40% suitable_pct
    index = avg_score * 0.6 + suitable_pct * 0.4

    if index >= 85:
        return "A+"
    elif index >= 70:
        return "A"
    elif index >= 55:
        return "B"
    elif index >= 40:
        return "C"
    else:
        return "D"


def _extract_street_name(building: dict) -> str:
    """Extrahiert den Straßennamen aus verschiedenen Adressformaten."""
    addr = building.get("address") or building.get("adresse") or {}
    if isinstance(addr, str):
        # "Musterstraße 12, 66111 Saarbrücken"
        return addr.split(",")[0].strip().rstrip("0123456789 /-").strip()
    if isinstance(addr, dict):
        return addr.get("street", addr.get("straße", addr.get("strasse", "")))
    return ""


def rank_streets(
    buildings: list[dict],
    min_buildings: int = 2,
) -> list[dict]:
    """
    Gruppiert bewertete Gebäude nach Straßen und berechnet Straßen-Rankings.

    Parameter
    ---------
    buildings : list[dict]
        Liste von Gebäude-Dicts. Jedes Dict muss enthalten:
        - 'address' oder 'adresse' (String oder Dict mit 'street')
        - 'pv_score' (float, 0-100) — vom pv_scorer berechnet
        - optional: 'sales_chance', 'priority', 'building_id'
    min_buildings : int
        Mindestanzahl Gebäude pro Straße für ein Rating (Standard: 2)

    Rückgabe
    --------
    list[dict] — sortiert nach avg_score absteigend, mit:
        street_name, avg_score, suitable_count, total_count, top_buildings,
        sales_probability, grade
    """
    streets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "scores": [],
        "sales_chances": [],
        "buildings": [],
    })

    for b in buildings:
        street = _extract_street_name(b)
        if not street or street == "":
            continue

        score = b.get("pv_score")
        if score is None or not isinstance(score, (int, float)):
            continue

        streets[street]["scores"].append(score)
        streets[street]["sales_chances"].append(b.get("sales_chance", 0) or 0)
        streets[street]["buildings"].append({
            "building_id": b.get("building_id", b.get("id", "unknown")),
            "address": b.get("address", b.get("adresse", "")),
            "pv_score": score,
            "sales_chance": b.get("sales_chance", 0),
            "priority": b.get("priority", "unbekannt"),
        })

    results = []
    for street_name, data in streets.items():
        scores = data["scores"]
        chances = data["sales_chances"]
        total = len(scores)

        avg_score = sum(scores) / total if total > 0 else 0.0
        avg_sales_chance = sum(chances) / total if total > 0 else 0.0

        # Anzahl Gebäude mit Score > 70 (geeignet für PV)
        suitable_count = sum(1 for s in scores if s >= 70)
        suitable_pct = (suitable_count / total * 100.0) if total > 0 else 0.0

        # Top-5 Gebäude
        sorted_buildings = sorted(
            data["buildings"], key=lambda x: x["pv_score"], reverse=True
        )
        top_buildings = sorted_buildings[:5]

        # Verkaufswahrscheinlichkeit
        sales_probability = round(avg_sales_chance, 1)

        # Bewertung
        grade = _grade_street(avg_score, suitable_pct)

        # Nur bewerten, wenn genug Gebäude
        if total < min_buildings:
            grade = "N/A"

        results.append({
            "street_name": street_name,
            "avg_score": round(avg_score, 1),
            "avg_sales_chance": round(avg_sales_chance, 1),
            "total_buildings": total,
            "suitable_buildings": suitable_count,
            "suitable_percentage": round(suitable_pct, 1),
            "top_buildings": top_buildings,
            "sales_probability": sales_probability,
            "grade": grade,
        })

    # Sortieren nach avg_score absteigend
    results.sort(key=lambda r: r["avg_score"], reverse=True)
    return results


# ─── CLI / Demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Liest JSON von stdin oder aus Datei
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    result = rank_streets(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))