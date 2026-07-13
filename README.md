# PV-Map — SolarRoute Scoring Engine

KI-gestützte Multi-Agenten-Plattform für PV-Vertrieb im Saarland.

## Scoring-Module

| Modul | Beschreibung |
|-------|-------------|
| `scoring/pv_scorer.py` | PV-Potenzial pro Gebäude (0-100) |
| `scoring/street_ranker.py` | Straßen-Ranking A+ bis D |
| `scoring/area_ranker.py` | Gebiets-Ranking ★☆☆☆☆ bis ★★★★★ |
| `scoring/cost_calculator.py` | Kosten, kWp, ROI, Amortisation |
| `scoring/scoring_pipeline.py` | Haupt-Orchestrator (CLI + API) |

## Nutzung

```bash
# Ein Gebäude bewerten
echo '{"roof_area": 85, "orientation": "S", ...}' | python3 scoring/pv_scorer.py

# Volle Pipeline
python3 scoring/scoring_pipeline.py input.json -o output.json
```

## Entwicklung

- `develop` — Integrationsbranch
- `feature/*` — Feature-Branches
- PRs via GitHub → Review durch den Lead → Squash-Merge