"""SNCF Open Data (portail Opendatasoft, API Explore v2.1).

Jeux utilises (identifiants verifies sur le portail, avec recherche plein texte en secours) :
- ``formes-des-lignes-du-rfn``      : geometrie des lignes physiques par code ligne RFN ;
- ``lignes-par-statut``             : statut d'exploitation par troncon ;
- ``lignes-lgv-et-par-ecartement``  : distinction LGV / ligne classique ;
- ``gares-de-voyageurs``            : gares de voyageurs (UIC, segment DRG A/B/C) ;
- ``liste-des-gares``               : tous les points du RFN (voyageurs O/N, fret O/N).

Les noms de champs varient selon les millesimes : la lecture est tolerante
(``pick``) et les champs introuvables restent vides plutot qu'inventes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

from ..normalize import strip_accents
from ..sources import SNCF_ODS_BASES, SOURCES
from ..store import LineRecord, ReferenceStore, StationRecord, as_multiline, normalize_uic
from .common import SourceUnavailable, load_geojson, ods_export, pick, pick_contains

log = logging.getLogger("railfine.import.sncf")

OPERATED = "exploitee"


def _norm(s) -> str:
    return strip_accents(str(s or "")).lower().strip()


def _line_code(props: dict) -> str | None:
    v = pick(props, "code_ligne", "codeligne", "code_lig", "ligne", "code")
    if v is None:
        return None
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(6) if s.isdigit() else s


def classify_infra(name: str | None, type_values: list[str]) -> str:
    """Nature de la ligne physique : uniquement a partir d'attributs explicites (jamais devinee)."""
    import re

    text = " ".join(_norm(v) for v in [name, *type_values] if v)
    if "grande vitesse" in text or re.search(r"\blgv\b", text):
        return "lgv"
    types_text = " ".join(_norm(v) for v in type_values)
    if re.search(r"\b(raccordement|embranchement|voie de service|voie portuaire|desserte portuaire)\b", types_text):
        return "raccordement"
    return "classique" if text else "inconnu"


def parse_line_features(features: list[dict], statuses: dict[str, set[str]], types: dict[str, list[str]]) -> list[LineRecord]:
    by_code: dict[str, dict] = defaultdict(lambda: {"geoms": [], "name": None})
    for f in features:
        g = f.get("geometry")
        if not g:
            continue
        props = f.get("properties") or {}
        code = _line_code(props)
        if not code:
            continue
        try:
            geom = shape(g)
        except (ValueError, TypeError, AttributeError):
            continue
        entry = by_code[code]
        entry["geoms"].append(geom)
        entry["name"] = entry["name"] or pick(props, "lib_ligne", "libelle_ligne", "nom_ligne", "libelle")
    out = []
    for code, entry in by_code.items():
        geom = as_multiline(unary_union(entry["geoms"]))
        if geom is None:
            continue
        sts = statuses.get(code, set())
        if not sts:
            status = None
        elif any(OPERATED in _norm(s) for s in sts):
            status = "exploitee"
        else:
            status = sorted(_norm(s) for s in sts)[0]
        out.append(
            LineRecord(
                id=f"rfn:{code}",
                code=code,
                name=entry["name"],
                geom=geom,
                country="FR",
                source="sncf_rfn_lines",
                infra_type=classify_infra(entry["name"], types.get(code, [])),
                status=status,
                extra={"statuts": sorted(sts)} if sts else {},
            )
        )
    return out


def _attributes(features: list[dict], *value_keys: str, contains: tuple[str, ...] = ()) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for f in features:
        props = f.get("properties") or {}
        code = _line_code(props)
        if not code:
            continue
        v = pick(props, *value_keys) or (pick_contains(props, *contains) if contains else None)
        if v:
            out[code].append(str(v))
    return out


def import_lines(store: ReferenceStore, raw_dir: Path) -> int:
    dest = raw_dir / "sncf"
    path, origin = ods_export(SNCF_ODS_BASES, ["formes-des-lignes-du-rfn"], dest, "geojson",
                              search_terms=["formes des lignes du rfn"])
    features = load_geojson(path)
    statuses: dict[str, set[str]] = defaultdict(set)
    types: dict[str, list[str]] = defaultdict(list)
    for ds, target in (("lignes-par-statut", "status"), ("lignes-lgv-et-par-ecartement", "type"), ("lignes-par-type", "type")):
        try:
            p, _ = ods_export(SNCF_ODS_BASES, [ds], dest, "geojson")
        except SourceUnavailable as exc:
            log.warning("jeu %s indisponible : %s", ds, exc)
            continue
        feats = load_geojson(p)
        if target == "status":
            for code, vals in _attributes(feats, "libelle", "statut", "lib_statut", "mnemo", contains=("statut",)).items():
                statuses[code].update(vals)
        else:
            for code, vals in _attributes(feats, "catlig", "type_ligne", "libelle", "type", contains=("type", "cat")).items():
                types[code].extend(vals)
    records = parse_line_features(features, statuses, types)
    n = store.replace_lines("sncf_rfn_lines", records)
    store.log_run("sncf_rfn_lines", "ok", n, origin=origin)
    store.log_run("sncf_line_types", "ok" if statuses or types else "partiel", len(statuses) + len(types), origin="lignes-par-statut, lignes-lgv-et-par-ecartement")
    return n


def _point(f: dict, props: dict) -> tuple[float, float] | None:
    g = f.get("geometry")
    if g and g.get("type") == "Point":
        lon, lat = g["coordinates"][:2]
        return float(lat), float(lon)
    gp = pick(props, "position_geographique", "geo_point_2d", "c_geo", "coordonnees")
    if isinstance(gp, dict) and "lat" in gp and "lon" in gp:
        return float(gp["lat"]), float(gp["lon"])
    if isinstance(gp, (list, tuple)) and len(gp) == 2:
        return float(gp[0]), float(gp[1])
    lat = pick(props, "latitude", "y_wgs84", "lat")
    lon = pick(props, "longitude", "x_wgs84", "lon")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None
    return None


def parse_passenger_stations(features: list[dict]) -> list[StationRecord]:
    out = []
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        pt = _point(f, props)
        name = pick(props, "nom", "nom_gare", "libelle", "intitule_gare", "alias_libelle_noncontraint")
        if not pt or not name:
            continue
        uics = str(pick(props, "codes_uic", "code_uic", "uic", "code_uic_complet", default="") or "")
        uic = None
        for part in uics.replace(",", ";").split(";"):
            uic = normalize_uic(part)
            if uic:
                break
        seg = str(pick(props, "segment_drg", "segmentdrg_libelle", "segment", default="") or "").strip().upper()[:1]
        importance = {"A": 1, "B": 2, "C": 3}.get(seg, 3)
        aliases = []
        short = pick(props, "libellecourt", "trigramme")
        if short and len(str(short)) > 3:
            aliases.append((str(short), "fr"))
        out.append(StationRecord(source="sncf_stations", source_id=f"gv:{uic or i}", name=str(name), lat=pt[0], lon=pt[1],
                                 uic=uic, country="FR", importance=importance, aliases=aliases,
                                 extra={"segment_drg": seg or None}))
    return out


def parse_rfn_points(features: list[dict]) -> list[StationRecord]:
    out = []
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        pt = _point(f, props)
        name = pick(props, "libelle", "nom", "libelle_gare")
        if not pt or not name:
            continue
        uic = normalize_uic(pick(props, "code_uic", "uic"))
        voyageurs = _norm(pick(props, "voyageurs", default=""))
        kind = "station" if voyageurs in {"o", "oui", "true", "1"} else "operational_point"
        out.append(StationRecord(source="sncf_stations", source_id=f"rfn:{uic or i}:{i}", name=str(name), lat=pt[0], lon=pt[1],
                                 uic=uic, country="FR", importance=3, kind=kind,
                                 extra={"code_ligne": _line_code(props), "pk": pick(props, "pk")}))
    return out


def import_stations(store: ReferenceStore, raw_dir: Path) -> int:
    dest = raw_dir / "sncf"
    records: list[StationRecord] = []
    origins = []
    try:
        p, origin = ods_export(SNCF_ODS_BASES, ["gares-de-voyageurs", "referentiel-gares-voyageurs"], dest, "geojson",
                               search_terms=["gares de voyageurs"])
        records.extend(parse_passenger_stations(load_geojson(p)))
        origins.append(origin)
    except SourceUnavailable as exc:
        log.warning("gares de voyageurs indisponibles : %s", exc)
    try:
        p, origin = ods_export(SNCF_ODS_BASES, ["liste-des-gares"], dest, "geojson")
        records.extend(parse_rfn_points(load_geojson(p)))
        origins.append(origin)
    except SourceUnavailable as exc:
        log.warning("liste des gares indisponible : %s", exc)
    if not records:
        raise SourceUnavailable("Aucun jeu de gares SNCF accessible")
    n = store.replace_station_records("sncf_stations", records)
    store.log_run("sncf_stations", "ok", n, origin=" ; ".join(origins))
    return n


SOURCE = SOURCES["sncf_rfn_lines"]
