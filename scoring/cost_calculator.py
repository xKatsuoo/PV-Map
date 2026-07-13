"""
cost_calculator.py — Kosten- und Angebotsrechner für PV-Anlagen

Berechnet:
- Durchschnittsanlagenpreis
- kWp-Leistung
- ROI (Return on Investment)
- Amortisationszeit
- Jährliche Einsparung
- Individuelles Angebot pro Gebäude
"""

from __future__ import annotations

import json
import sys
from typing import Optional


# ─── Standard-Parameter (anpassbar) ─────────────────────────────────────────

DEFAULT_PARAMS = {
    # Kosten pro kWp in EUR (abhängig von Anlagengröße)
    "cost_per_kwp_small": 1600.0,      # < 5 kWp
    "cost_per_kwp_medium": 1400.0,     # 5-10 kWp
    "cost_per_kwp_large": 1200.0,      # > 10 kWp
    # Strompreis in EUR/kWh
    "electricity_price": 0.30,
    # Jährliche Strompreissteigerung
    "price_increase_pct": 3.0,
    # Einspeisevergütung in EUR/kWh
    "feed_in_tariff": 0.08,
    # Eigenverbrauchsanteil (0-1)
    "self_consumption_rate": 0.60,
    # Wartungskosten pro Jahr in % der Investition
    "maintenance_pct": 1.0,
    # Speicherkosten (optional) EUR/kWh
    "battery_cost_per_kwh": 800.0,
    # Standard-Speichergröße in kWh (50% der kWp)
    "battery_kwh_per_kwp": 0.5,
    # Jährliche Degradation der Module in %
    "degradation_pct": 0.5,
    # Betrachtungszeitraum in Jahren
    "lifetime_years": 25,
}


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────

def _estimate_kwp(roof_area_m2: Optional[float], pv_score: float) -> float:
    """
    Schätzt die installierbare kWp-Leistung basierend auf Dachfläche und Score.
    Faustregel: ~1 kWp pro 6-8 m² Dachfläche (moderne Module).
    """
    if roof_area_m2 is None or roof_area_m2 <= 0:
        # Schätzung basierend auf Score
        return max(2.0, pv_score / 100.0 * 10.0)

    # Nutzbare Dachfläche (ca. 70% der Gesamtfläche nach Abzug von Verschattung etc.)
    usable = roof_area_m2 * 0.7
    # Moderne Module: ~1 kWp pro 6 m²
    kwp = usable / 6.0
    return round(max(1.0, kwp), 2)


def _get_cost_per_kwp(kwp: float, params: dict) -> float:
    """Staffelpreis basierend auf Anlagengröße."""
    if kwp < 5:
        return params["cost_per_kwp_small"]
    elif kwp <= 10:
        return params["cost_per_kwp_medium"]
    else:
        return params["cost_per_kwp_large"]


def _calculate_annual_yield(kwp: float, roof_area_m2: Optional[float], pv_score: float) -> float:
    """
    Berechnet den jährlichen Ertrag in kWh.
    Deutschland-Durchschnitt: ~950 kWh/kWp pro Jahr.
    Anpassung an Score und Standort (Saarland: ~1000 kWh/kWp).
    """
    base_yield_per_kwp = 1000.0  # Saarland
    # Score-basierte Anpassung
    efficiency_factor = pv_score / 100.0
    # Korrektur: selbst bei niedrigem Score gibt es etwas Ertrag
    efficiency_factor = max(0.3, efficiency_factor)

    annual_kwh = kwp * base_yield_per_kwp * efficiency_factor
    return round(annual_kwh, 0)


# ─── Hauptfunktionen ─────────────────────────────────────────────────────────

def calculate_costs(
    building: dict,
    params: Optional[dict] = None,
) -> dict:
    """
    Berechnet Kosten, ROI und Amortisation für ein Gebäude.

    Parameter
    ---------
    building : dict
        Gebäudedaten. Erwartet mindestens:
        - pv_score (float) — vom pv_scorer
        - roof_area (float, optional) — Dachfläche in m²
        - property.electricity_consumption (float, optional) — Stromverbrauch
    params : dict, optional
        Überschreibt Standard-Parameter.

    Rückgabe
    --------
    dict mit Kosten, kWp, ROI, Amortisation, Einsparung.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    pv_score = building.get("pv_score", 50.0) or 50.0
    roof_area = building.get("roof_area")
    consumption = None
    prop = building.get("property", {})
    if prop:
        consumption = prop.get("electricity_consumption") or prop.get("stromverbrauch")

    # 1. kWp schätzen
    kwp = _estimate_kwp(roof_area, pv_score)

    # 2. Kosten
    cost_per_kwp = _get_cost_per_kwp(kwp, p)
    total_cost_kwp = round(kwp * cost_per_kwp, 2)

    # 3. Speicher (optional)
    battery_kwh = round(kwp * p["battery_kwh_per_kwp"], 1)
    battery_cost = round(battery_kwh * p["battery_cost_per_kwh"], 2)

    # 4. Gesamtinvestition
    total_investment = round(total_cost_kwp + battery_cost, 2)

    # 5. Jährlicher Ertrag
    annual_yield_kwh = _calculate_annual_yield(kwp, roof_area, pv_score)

    # 6. Eigenverbrauch und Einspeisung
    self_consumption_kwh = round(annual_yield_kwh * p["self_consumption_rate"], 0)
    feed_in_kwh = round(annual_yield_kwh * (1 - p["self_consumption_rate"]), 0)

    # 7. Kostenersparnis
    # Vermiedener Strombezug
    avoided_cost = round(self_consumption_kwh * p["electricity_price"], 2)
    # Einspeisevergütung
    feed_in_revenue = round(feed_in_kwh * p["feed_in_tariff"], 2)
    # Jährliche Wartung
    maintenance = round(total_investment * p["maintenance_pct"] / 100.0, 2)

    annual_savings = round(avoided_cost + feed_in_revenue - maintenance, 2)

    # 8. ROI und Amortisation
    # Einfache Amortisation (ohne Zins/Degradation)
    if annual_savings > 0:
        amortisation_years = round(total_investment / annual_savings, 1)
    else:
        amortisation_years = 999.0  # nie

    # ROI über die Lebensdauer
    total_earnings = 0.0
    yearly_savings = annual_savings
    for year in range(1, p["lifetime_years"] + 1):
        # Ertragsdegradation
        degradation_factor = (1 - p["degradation_pct"] / 100.0) ** (year - 1)
        # Strompreissteigerung
        price_factor = (1 + p["price_increase_pct"] / 100.0) ** (year - 1)
        total_earnings += yearly_savings * degradation_factor * price_factor
        yearly_savings = annual_savings  # reset for the factor calc

    net_profit = round(total_earnings - total_investment, 2)
    roi_pct = round((total_earnings / total_investment) * 100.0, 1)

    # 9. Vergleich zum aktuellen Stromverbrauch
    if consumption:
        try:
            c = float(consumption)
            coverage_pct = round(min(100.0, annual_yield_kwh / c * 100.0), 1)
        except (ValueError, TypeError):
            coverage_pct = None
    else:
        coverage_pct = None

    return {
        "building_id": building.get("building_id", building.get("id", "unknown")),
        "pv_score": pv_score,
        # Anlagendimension
        "estimated_kwp": kwp,
        "battery_kwh": battery_kwh,
        # Kosten
        "cost_per_kwp": cost_per_kwp,
        "total_cost_modules": total_cost_kwp,
        "battery_cost": battery_cost,
        "total_investment": total_investment,
        # Erträge
        "annual_yield_kwh": annual_yield_kwh,
        "self_consumption_kwh": self_consumption_kwh,
        "feed_in_kwh": feed_in_kwh,
        # Einsparung
        "annual_savings_eur": annual_savings,
        "avoided_cost_eur": avoided_cost,
        "feed_in_revenue_eur": feed_in_revenue,
        "maintenance_cost_eur": maintenance,
        # ROI
        "amortisation_years": amortisation_years,
        "net_profit_25y_eur": net_profit,
        "roi_25y_pct": roi_pct,
        "coverage_of_consumption_pct": coverage_pct,
    }


def calculate_costs_bulk(
    buildings: list[dict],
    params: Optional[dict] = None,
) -> list[dict]:
    """Berechnet Kosten für eine Liste von Gebäuden."""
    return [calculate_costs(b, params) for b in buildings]


# ─── CLI / Demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    if isinstance(data, dict):
        result = calculate_costs(data)
    else:
        result = calculate_costs_bulk(data)

    print(json.dumps(result, ensure_ascii=False, indent=2))