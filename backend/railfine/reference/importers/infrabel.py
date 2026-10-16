"""Infrabel Open Data (Belgique, portail Opendatasoft).

- lignes physiques : sections de lignes geolocalisees (numero de ligne Infrabel) ;
- points operationnels : gares, haltes et points techniques (noms FR/NL).

Les identifiants de jeux d'Infrabel ont change plusieurs fois : on essaie une
liste de candidats puis une recherche plein texte dans le catalogue.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

from ..normalize import strip_accents
from ..sources import INFRABEL_ODS_BASES, SOURCES
from ..store import LineRecord, ReferenceStore, StationRecord, as_multiline
from .common import load_geojson, ods_export, pick, pick_contains

# Lignes a grande vitesse belges (numerotation Infrabel) : L1, L2, L3, L4.
BE_HSL = {"1", "2", "3", "4"}


def _code(props: dict) -> str | None:
    v = pick(props, "ligne", "lijn", "line", "lijnnummer", "numero_ligne", "ls_lijn", "lijn_nr", "nr_lijn") or pick_contains(
        props, "lijn", "ligne", "line"
    )
    if v is None:
        return None
    s = str(v).strip().upper()
    s = re.sub(r"^(L|LIGNE|LIJN)\s*", "", s)
    return s or None


def parse_lines(features: list[dict]) -> list[LineRecord]:
    groups: dict[str, list] = defaultdict(list)
    for f in features:
        g = f.get("geometry")
        if not g or g.get("type") not in ("LineString", "MultiLineString"):
            continue
        code = _code(f.get("properties") or {})
        if not code:
            continue
        try:
            groups[code].append(shape(g))
        except (ValueError, TypeError, AttributeError):
            continue
    out = []
    for code, geoms in groups.items():
        geom = as_multiline(unary_union(geoms))
        if geom is None:
            continue
        base = re.match(r"\d+", code)
        infra = "lgv" if base and base.group(0) in BE_HSL and code == base.group(0) else "classique"
        out.append(LineRecord(id=f"infrabel:{code}", code=f"L{code}", name=f"Ligne {code}", geom=geom, country="BE",
                              source="infrabel_lines", infra_type=infra, status="exploitee"))
    return out


def parse_points(features: list[dict]) -> list[StationRecord]:
    out = []
    for i, f in enumerate(features):
        g = f.get("geometry")
        props = f.get("properties") or {}
        if not g or g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        fr = pick(props, "longnamefrench", "nom_fr", "name_fr", "longnamefr")
        nl = pick(props, "longnamedutch", "nom_nl", "name_nl", "longnamenl")
        name = fr or nl or pick(props, "name", "nom", "naam")
        if not name:
            continue
        cls = strip_accents(str(pick(props, "classification", "type", "class", default=""))).lower()
        kind = "station" if any(w in cls for w in ("station", "halte", "arret", "stopplaats", "gare")) else "operational_point"
        aliases = [(str(v), lang) for v, lang in ((fr, "fr"), (nl, "nl")) if v]
        out.append(StationRecord(source="infrabel_points", source_id=str(pick(props, "ptcarid", "id", default=i)),
                                 name=str(name), lat=float(lat), lon=float(lon), country="BE", importance=3, kind=kind,
                                 aliases=aliases, extra={"taf_tap": pick(props, "taftapcode")}))
    return out


def import_lines(store: ReferenceStore, raw_dir: Path) -> int:
    src = SOURCES["infrabel_lines"]
    path, origin = ods_export(INFRABEL_ODS_BASES, src.urls, raw_dir / "infrabel", "geojson",
                              search_terms=["lijnsecties", "spoorlijnen", "lignes ferroviaires"])
    records = parse_lines(load_geojson(path))
    n = store.replace_lines(src.id, records)
    store.log_run(src.id, "ok", n, origin=origin)
    return n


def import_points(store: ReferenceStore, raw_dir: Path) -> int:
    src = SOURCES["infrabel_points"]
    path, origin = ods_export(INFRABEL_ODS_BASES, src.urls, raw_dir / "infrabel", "geojson",
                              search_terms=["operationele punten", "points operationnels"])
    records = parse_points(load_geojson(path))
    n = store.replace_station_records(src.id, records)
    store.log_run(src.id, "ok", n, origin=origin)
    return n
