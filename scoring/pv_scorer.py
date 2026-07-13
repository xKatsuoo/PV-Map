"""
pv_scorer.py — PV-Potenzial-Bewertung pro Gebäude

Berechnet den PV-Score (0-100) für ein einzelnes Gebäude anhand gewichteter Faktoren:
- Dachfläche 25%
- Ausrichtung 25%
- Verschattung 20%
- Dachzustand 10%
- Gebäudetyp 10%
- Grundstück 10%

Zusätzlich: Balkonkraftwerk-Score, Verkaufschance, Priorität.
"""

from typing import Any, Optional


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────

def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Wert auf [low, high] begrenzen."""
    return max(low, min(high, value))


def _score_roof_area(area_m2: Optional[float]) -> float:
    """
    Bewertet die Dachfläche (0-100).
    < 20 m² → ungeeignet,  20-30 → schwach,  30-50 → mittel,
    50-80 → gut,  80-150 → ideal,  > 150 → sehr gut (aber abnehmend).
    """
    if area_m2 is None or area_m2 < 20:
        return 0.0
    if area_m2 < 30:
        return 20.0 + (area_m2 - 20) * 3.0           # 20..50
    if area_m2 < 50:
        return 50.0 + (area_m2 - 30) * 1.5           # 50..80
    if area_m2 < 80:
        return 80.0 + (area_m2 - 50) * 0.67          # 80..100
    if area_m2 <= 150:
        return 100.0
    # > 150 m²: leicht abfallend (riesige Dächer sind seltener optimal)
    return _clamp(100.0 - (area_m2 - 150) * 0.2, low=70.0)


def _score_orientation(orientation: Optional[str]) -> float:
    """
    Bewertet die Dachausrichtung.
    Süd(ost/west) → ideal,  Ost/West → gut,  Nord/Ost/Nord/West → mäßig,  Nord → schlecht.
    """
    if not orientation:
        return 50.0  # unbekannt → mittel
    o = orientation.strip().lower()

    # Haupt-Himmelsrichtungen und Kombinationen
    if o in ("s", "south", "sued", "süden"):
        return 100.0
    if o in ("so", "southeast", "suedost", "südost"):
        return 95.0
    if o in ("sw", "southwest", "suedwest", "südwest"):
        return 90.0
    if o in ("o", "e", "east", "osten"):
        return 75.0
    if o in ("w", "west", "westen"):
        return 70.0
    if o in ("no", "ne", "northeast", "nordost"):
        return 45.0
    if o in ("nw", "northwest", "nordwest"):
        return 40.0
    if o in ("n", "north", "norden"):
        return 15.0
    # Flachdach / ost-west / beidseitig
    if o in ("flat", "flach", "flachdach"):
        return 60.0
    if o in ("ow", "ost-west", "east-west", "ostwest"):
        return 80.0
    # alles andere (unbekannt)
    return 50.0


def _score_shading(shading: Optional[Any]) -> float:
    """
    Bewertet die Verschattung (0-100).
    Kann als Zahl (0-100 Prozent) oder als Text vorliegen.
    """
    if shading is None:
        return 70.0  # Annahme: leichte Verschattung
    if isinstance(shading, (int, float)):
        return _clamp(100.0 - float(shading))
    s = str(shading).strip().lower()
    mapping = {
        "keine": 100.0, "none": 100.0, "frei": 100.0, "free": 100.0,
        "gering": 80.0, "wenig": 80.0, "low": 80.0, "leicht": 80.0,
        "mittel": 55.0, "medium": 55.0, "moderate": 55.0,
        "stark": 25.0, "high": 25.0, "viel": 25.0,
        "voll": 0.0, "vollverschattet": 0.0, "total": 0.0, "full": 0.0,
    }
    return mapping.get(s, 50.0)


def _score_roof_condition(condition: Optional[str]) -> float:
    """
    Bewertet den Dachzustand (0-100).
    """
    if not condition:
        return 70.0  # unbekannt → eher gut (Annahme)
    c = condition.strip().lower()
    mapping = {
        "neuwertig": 100.0, "neubau": 100.0, "new": 100.0, "excellent": 100.0,
        "gut": 85.0, "good": 85.0,
        "mittel": 65.0, "ok": 65.0, "average": 65.0, "normal": 65.0,
        "sanierungsbedürftig": 35.0, "renovate": 35.0, "poor": 35.0,
        "schlecht": 15.0, "bad": 15.0, "durchlässig": 5.0,
    }
    return mapping.get(c, 60.0)


def _score_building_type(building_type: Optional[str]) -> float:
    """
    Bewertet den Gebäudetyp (0-100).
    EFH/ZFH → hohe Eignung,  MFH → mittel,  Gewerbe → mittel,
    denkmalgeschützt → gering.
    """
    if not building_type:
        return 60.0
    b = building_type.strip().lower()
    mapping = {
        "einfamilienhaus": 100.0, "efh": 100.0, "single-family": 100.0,
        "doppelhaushälfte": 100.0, "dhh": 100.0, "semi-detached": 100.0,
        "zweifamilienhaus": 95.0, "zfh": 95.0, "two-family": 95.0,
        "reihenhaus": 90.0, "rh": 90.0, "townhouse": 90.0, "row house": 90.0,
        "mehrfamilienhaus": 70.0, "mfh": 70.0, "apartment": 70.0, "multi-family": 70.0,
        "wohngebäude": 80.0, "residential": 80.0,
        "gewerbe": 60.0, "commercial": 60.0, "büro": 60.0, "office": 60.0,
        "landwirtschaft": 75.0, "agricultural": 75.0, "bauernhof": 75.0, "farm": 75.0,
        "denkmal": 15.0, "monument": 15.0, "heritage": 15.0, "denkmalgeschützt": 10.0,
    }
    return mapping.get(b, 60.0)


def _score_property(property_data: Optional[dict]) -> float:
    """
    Bewertet das Grundstück (0-100) anhand verfügbarer Daten:
    - Eigentümer (Eigentümer > Mieter)
    - Grundstücksgröße
    - Stromverbrauch (hoher Verbrauch = mehr Potential)
    """
    if not property_data:
        return 60.0

    score = 0.0
    count = 0

    # Eigentümer-Status
    owner = property_data.get("owner_status") or property_data.get("ownership")
    if owner:
        count += 1
        o = str(owner).strip().lower()
        if o in ("eigentümer", "owner", "homeowner", "eigentum", "besitzer"):
            score += 100.0
        elif o in ("mieter", "renter", "tenant", "miete"):
            score += 15.0
        else:
            score += 50.0

    # Grundstücksgröße
    lot_size = property_data.get("lot_size") or property_data.get("grundstuecksflaeche")
    if lot_size is not None:
        count += 1
        try:
            ls = float(lot_size)
            if ls < 200:
                score += 30.0
            elif ls < 400:
                score += 60.0
            elif ls < 800:
                score += 85.0
            else:
                score += 100.0
        except (ValueError, TypeError):
            pass

    # Stromverbrauch
    consumption = property_data.get("electricity_consumption") or property_data.get("stromverbrauch")
    if consumption is not None:
        count += 1
        try:
            c = float(consumption)
            if c < 1500:
                score += 25.0
            elif c < 3000:
                score += 55.0
            elif c < 5000:
                score += 80.0
            else:
                score += 100.0
        except (ValueError, TypeError):
            pass

    if count == 0:
        return 60.0
    return _clamp(score / count)


# ─── Hauptfunktionen ─────────────────────────────────────────────────────────

def calculate_pv_score(building: dict) -> float:
    """
    Berechnet den PV-Gesamtscore (0-100) für ein Gebäude.

    Erwartet ein dict mit Keys (alle optional):
        roof_area (float)                — Dachfläche in m²
        orientation (str)                — Ausrichtung (z. B. 'S', 'SO', 'O', 'Flach')
        shading (float|str)              — Verschattung
        roof_condition (str)             — Dachzustand
        building_type (str)              — Gebäudetyp
        property (dict)                  — Grundstücksdaten
    """
    weights = {
        "roof_area": 0.25,
        "orientation": 0.25,
        "shading": 0.20,
        "roof_condition": 0.10,
        "building_type": 0.10,
        "property": 0.10,
    }

    scores = {
        "roof_area": _score_roof_area(building.get("roof_area")),
        "orientation": _score_orientation(building.get("orientation")),
        "shading": _score_shading(building.get("shading")),
        "roof_condition": _score_roof_condition(building.get("roof_condition")),
        "building_type": _score_building_type(building.get("building_type")),
        "property": _score_property(building.get("property")),
    }

    total = sum(scores[k] * weights[k] for k in weights)
    return round(_clamp(total), 1)


def calculate_balcony_pv_score(building: dict) -> float:
    """
    Berechnet einen Balkonkraftwerk-Score (0-100).
    Unabhängig vom Dach — bewertet Eignung für Stecker-Solar.
    """
    score = 50.0  # Basis

    # Balkon vorhanden? (aus property oder extras)
    balcony = building.get("balcony") or building.get("property", {}).get("balcony")
    if balcony:
        s = str(balcony).strip().lower()
        if s in ("yes", "true", "ja", "1", "vorhanden", "groß", "large"):
            score += 30.0
        elif s in ("small", "klein"):
            score += 15.0
    else:
        score -= 10.0

    # Ausrichtung (Balkonkraftwerke profitieren auch von Ost/West)
    orientation = building.get("orientation", "")
    o = orientation.strip().lower() if orientation else ""
    if o in ("s", "south", "sued", "süden", "so", "südost", "sw", "südwest"):
        score += 20.0
    elif o in ("o", "e", "east", "osten", "w", "west", "westen"):
        score += 10.0
    elif o in ("n", "north", "norden"):
        score -= 20.0

    # Mieter/Eigentümer — Mieter sind Hauptzielgruppe für Balkonkraftwerke
    owner = building.get("property", {}).get("owner_status", "")
    if owner:
        o = str(owner).strip().lower()
        if o in ("mieter", "renter", "tenant"):
            score += 15.0

    return round(_clamp(score), 1)


def calculate_sales_chance(pv_score: float, balcony_score: float) -> float:
    """
    Berechnet eine Verkaufschance (0-100) aus PV-Score und Balkonkraftwerk-Score.
    """
    # PV-Score ist der primäre Treiber
    chance = pv_score * 0.7 + balcony_score * 0.3
    return round(_clamp(chance), 1)


def calculate_priority(pv_score: float, sales_chance: float) -> str:
    """
    Ordnet eine Prioritätsstufe zu.
    """
    combined = pv_score * 0.5 + sales_chance * 0.5
    if combined >= 85:
        return "sehr_hoch"
    elif combined >= 70:
        return "hoch"
    elif combined >= 50:
        return "mittel"
    elif combined >= 30:
        return "niedrig"
    else:
        return "sehr_niedrig"


def score_building(building: dict) -> dict:
    """
    Führt alle Berechnungen für ein Gebäude durch und gibt ein vollständiges
    Score-Dict zurück.
    """
    pv_score = calculate_pv_score(building)
    balcony_score = calculate_balcony_pv_score(building)
    sales_chance = calculate_sales_chance(pv_score, balcony_score)
    priority = calculate_priority(pv_score, sales_chance)

    return {
        "building_id": building.get("id", building.get("building_id", "unknown")),
        "address": building.get("address", building.get("adresse", "")),
        "pv_score": pv_score,
        "balcony_pv_score": balcony_score,
        "sales_chance": sales_chance,
        "priority": priority,
        "details": {
            "roof_area_score": _score_roof_area(building.get("roof_area")),
            "orientation_score": _score_orientation(building.get("orientation")),
            "shading_score": _score_shading(building.get("shading")),
            "roof_condition_score": _score_roof_condition(building.get("roof_condition")),
            "building_type_score": _score_building_type(building.get("building_type")),
            "property_score": _score_property(building.get("property")),
        },
    }


def score_buildings(buildings: list[dict]) -> list[dict]:
    """Bewertet eine Liste von Gebäuden."""
    return [score_building(b) for b in buildings]


# ─── CLI / Demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    # Liest JSON von stdin oder aus Datei
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    if isinstance(data, dict):
        result = score_building(data)
    else:
        result = score_buildings(data)

    print(json.dumps(result, ensure_ascii=False, indent=2))