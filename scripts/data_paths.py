"""Canonical local paths for Waterpark data pipelines.

Keep path decisions here so a dataset move does not require editing every
collector and preprocessing script.  Large/raw artifacts are local-only; small
manifests, QA tables and reproducible code are safe to keep in Git.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
OUTPUTS = ROOT / "outputs"

RAW_FLOOD_TRACE = RAW / "flood-trace"
RAW_VWORLD_BUILDINGS = RAW / "vworld-buildings"
RAW_VWORLD_GYEONGBUK = RAW_VWORLD_BUILDINGS / "gyeongbuk"
RAW_BUILDING_REGISTER = RAW / "building-register"
RAW_KMA_RAIN = RAW / "kma-rain"
RAW_KMA_STATIONS = RAW / "kma-stations"
RAW_OSM_CACHE = RAW / "osm-cache"
RAW_OSM_ROUTING = RAW / "osm-routing"

INTERIM_FLOOD_TRACE = INTERIM / "flood-trace"
INTERIM_FLOOD_TRACE_GYEONGBUK = INTERIM_FLOOD_TRACE / "gyeongbuk"
INTERIM_BUILDING_REGISTER = INTERIM / "building-register"
INTERIM_VWORLD_BUILDINGS = INTERIM / "vworld-buildings"

PROCESSED_BUILDINGS = PROCESSED / "buildings"
PROCESSED_RAINFALL = PROCESSED / "rainfall"
PROCESSED_PARKING = PROCESSED / "parking"
PROCESSED_ML_TRAINING = PROCESSED / "ml" / "training"
PROCESSED_ML_PREDICTIONS = PROCESSED / "ml" / "predictions"
OUTPUTS_ROUTING = OUTPUTS / "routing"
