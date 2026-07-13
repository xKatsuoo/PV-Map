# PV-Map — Vision Module

Dachanalyse-Pipeline für die PV-Potenzialbewertung von Gebäuden im Saarland.

## Module

| Modul | Beschreibung |
|-------|-------------|
| `roof_analyzer.py` | Dachtyp, Ausrichtung, Fläche, Neigung (Heuristik aus Gebäudeumriss) |
| `shadow_analyzer.py` | Verschattungsanalyse (OSM-Tag-basierte Heuristik) |
| `pv_detector.py` | Erkennung bestehender PV-Anlagen (OSM-Tags, Platzhalter für CV) |
| `vision_pipeline.py` | Hauptpipeline: Orchestrierung + Gesamtscore + Vertriebs-Empfehlungen |

## Verwendung

```python
from vision.vision_pipeline import analyze_building

building = {
    "id": "example-123",
    "geometry": [(6.997, 49.236), (6.998, 49.236), (6.998, 49.237), (6.997, 49.237)],
    "tags": {"building": "yes", "roof:shape": "gabled", "building:levels": "2"},
}

result = analyze_building(building)
print(result["pv_suitability_score"])  # 0-100
print(result["potential"])             # sehr_gut / gut / mittel / schlecht / kein_neukunde
print(result["recommendation"])        # Handlungsempfehlung
```

## Datenformat

- **Input**: Gebäude-Dict mit `id`, `geometry` (Liste von `(lon, lat)`-Tupeln), `tags` (OSM-Property-Dict)
- **Output**: Dict mit allen Analyseergebnissen, Einzelscores und Gesamt-PV-Eignung

## Nächste Schritte

- Integration echter Satellitenbildanalyse (YOLO / Segment Anything)
- Computer-Vision-basierte PV-Erkennung auf Dachflächen
- Maschinelles Lernen für genauere Dachtyp-Klassifikation