"""Gares depuis les referentiels communautaires heberges sur GitHub.

- Trainline EU stations (ODbL) : France + Belgique, codes UIC ;
- iRail stations (CC0) : Belgique, noms FR/NL/DE/EN, nombre moyen d'arrets/jour.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..normalize import strip_accents
from ..sources import SOURCES
from ..store import ReferenceStore, StationRecord, normalize_uic
from .common import first_available

COUNTRIES = {"FR", "BE"}


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"t", "true", "1", "y", "yes"}


def parse_trainline(path: Path) -> list[StationRecord]:
    out: list[StationRecord] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            country = (row.get("country") or "").upper()
            if country not in COUNTRIES:
                continue
            uic = normalize_uic(row.get("uic"))
            if not uic or not uic.startswith(("87", "88")):
                continue  # villes, arrets de bus, gares etrangeres
            if row.get("same_as"):
                continue  # doublon declare d'une autre entree
            active = _truthy(row.get("is_suggestable")) or _truthy(row.get("sncf_is_enabled")) or _truthy(
                row.get("benerail_is_enabled")
            )
            if not active or _truthy(row.get("is_city")):
                continue
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if "routiere" in strip_accents(row.get("name") or "").lower():
                continue  # gares routieres (autocars) : hors reseau ferre
            # NB : les colonnes info:xx sont des indications (ville...), pas des noms de gare : non reprises.
            aliases: list = []
            out.append(
                StationRecord(
                    source="trainline_stations",
                    source_id=row["id"],
                    name=row["name"],
                    lat=lat,
                    lon=lon,
                    uic=uic,
                    country=country,
                    importance=2 if _truthy(row.get("is_main_station")) else 3,
                    aliases=aliases,
                    extra={"trainline_id": row["id"]},
                )
            )
    return out


def parse_irail(path: Path) -> list[StationRecord]:
    out: list[StationRecord] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            country = (row.get("country-code") or "").upper()
            if country not in COUNTRIES:
                continue
            uri = row.get("URI") or ""
            uic = normalize_uic(uri.rsplit("/", 1)[-1])
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                stops = float(row.get("avg_stop_times") or 0)
            except ValueError:
                stops = 0.0
            importance = 1 if stops >= 300 else 2 if stops >= 80 else 3
            aliases = [
                (row[f"alternative-{lang}"], lang)
                for lang in ("fr", "nl", "de", "en")
                if row.get(f"alternative-{lang}")
            ]
            out.append(
                StationRecord(
                    source="irail_stations",
                    source_id=uri.rsplit("/", 1)[-1],
                    name=row["name"],
                    lat=lat,
                    lon=lon,
                    uic=uic,
                    country=country,
                    importance=importance,
                    aliases=aliases,
                    extra={"avg_stop_times": round(stops, 1), "telegraph_code": row.get("telegraph-code") or None},
                )
            )
    return out


def import_trainline(store: ReferenceStore, raw_dir: Path, local_file: Path | None = None) -> int:
    src = SOURCES["trainline_stations"]
    if local_file:
        path, origin = local_file, str(local_file)
    else:
        path, origin = first_available(src.urls, raw_dir / "trainline" / "stations.csv")
    records = parse_trainline(path)
    n = store.replace_station_records(src.id, records)
    store.log_run(src.id, "ok", n, origin=origin)
    return n


def import_irail(store: ReferenceStore, raw_dir: Path, local_file: Path | None = None) -> int:
    src = SOURCES["irail_stations"]
    if local_file:
        path, origin = local_file, str(local_file)
    else:
        path, origin = first_available(src.urls, raw_dir / "irail" / "stations.csv")
    records = parse_irail(path)
    n = store.replace_station_records(src.id, records)
    store.log_run(src.id, "ok", n, origin=origin)
    return n
