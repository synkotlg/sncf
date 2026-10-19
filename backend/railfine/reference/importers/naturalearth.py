"""Natural Earth (domaine public) : frontieres pour le fond hors ligne et reseau ferre de secours.

Le reseau Natural Earth est generalise (echelle 1:10 000 000) et ne porte ni
nom ni code de ligne : il n'est active que si aucune source officielle de
lignes n'a ete importee pour le pays concerne.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..sources import SOURCES
from ..store import LineRecord, ReferenceStore
from .common import first_available

BASEMAP_COUNTRIES = {"FRA", "BEL", "LUX", "DEU", "NLD", "CHE", "ITA", "ESP", "GBR", "AND", "MCO"}
# Pays dont on importe le reseau ferre (France/Belgique + voisins pour avoir
# le contexte tout autour de la France). Pour ces pays, Natural Earth est la
# seule source de lignes : son reseau generalise est donc affiche directement.
RAIL_COUNTRIES = {"FRA": "FR", "BEL": "BE", "CHE": "CH", "DEU": "DE", "ESP": "ES", "GBR": "GB"}


def _iso3(props: dict) -> str | None:
    for key in ("ADM0_A3", "ISO_A3", "SOV_A3", "ADM0_A3_US"):
        v = props.get(key)
        if v and v != "-99":
            return v
    return None


def load_country_shapes(countries_path: Path) -> dict[str, tuple[str, object]]:
    data = json.loads(countries_path.read_text(encoding="utf-8"))
    out = {}
    for f in data["features"]:
        iso = _iso3(f["properties"])
        if iso in BASEMAP_COUNTRIES:
            geom = shape(f["geometry"])
            if iso == "FRA":
                # metropole + Corse uniquement (exclut l'outre-mer pour le fond de carte)
                geom = geom.intersection(shape({"type": "Polygon", "coordinates": [[[-6, 41], [10, 41], [10, 52], [-6, 52], [-6, 41]]]}))
            out[iso] = (f["properties"].get("NAME_FR") or f["properties"].get("NAME") or iso, geom)
    return out


def import_basemap(store: ReferenceStore, raw_dir: Path, local_file: Path | None = None) -> tuple[int, Path]:
    src = SOURCES["naturalearth_countries"]
    if local_file:
        path, origin = local_file, str(local_file)
    else:
        path, origin = first_available(src.urls, raw_dir / "naturalearth" / "ne_10m_admin_0_countries.geojson")
    shapes = load_country_shapes(path)
    items = []
    for iso, (name, geom) in shapes.items():
        tolerance = 0.002 if iso in RAIL_COUNTRIES else 0.01
        simplified = geom.simplify(tolerance, preserve_topology=True)
        items.append((iso, name, {"type": "Feature", "properties": {"iso": iso, "name": name, "focus": iso in RAIL_COUNTRIES},
                                  "geometry": mapping(simplified)}))
    store.set_basemap(items, src.id)
    store.log_run(src.id, "ok", len(items), origin=origin)
    return len(items), path


def import_rail(store: ReferenceStore, raw_dir: Path, countries_path: Path, local_file: Path | None = None) -> int:
    src = SOURCES["naturalearth_rail"]
    if local_file:
        path, origin = local_file, str(local_file)
    else:
        path, origin = first_available(src.urls, raw_dir / "naturalearth" / "ne_10m_railroads.geojson")
    shapes = load_country_shapes(countries_path)
    clips = {cc: unary_union([shapes[iso][1]]).buffer(0.02) for iso, cc in RAIL_COUNTRIES.items() if iso in shapes}
    bbox = unary_union(list(clips.values())).bounds
    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for i, f in enumerate(data["features"]):
        if not f.get("geometry"):
            continue
        geom = shape(f["geometry"])
        minx, miny, maxx, maxy = geom.bounds
        if maxx < bbox[0] or minx > bbox[2] or maxy < bbox[1] or miny > bbox[3]:
            continue
        props = f.get("properties") or {}
        for cc, clip in clips.items():
            if not geom.intersects(clip):
                continue
            part = geom.intersection(clip)
            if part.is_empty or part.length < 1e-4:
                continue
            records.append(
                LineRecord(
                    id=f"ne:{i}:{cc}",
                    geom=part,
                    source=src.id,
                    country=cc,
                    infra_type="inconnu",
                    electrified="oui" if props.get("electric") == 1 else None,
                    tracks="multiple" if props.get("mult_track") == 1 else None,
                    name=f"Tronçon sans nom #{i} (Natural Earth, {cc})",
                    extra={"natural_earth_category": props.get("category"), "scalerank": props.get("scalerank")},
                )
            )
    n = store.replace_lines(src.id, records)
    store.log_run(src.id, "ok", n, origin=origin)
    return n
