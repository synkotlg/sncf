"""OpenStreetMap via Overpass API (ODbL).

- ``railway=rail`` avec ``usage=main|branch`` (hors voies de service) : lignes physiques,
  regroupees par reference de ligne / nom, ``highspeed=yes`` -> LGV ;
- relations ``route=train`` : itineraires commerciaux (TER, TGV, Intercites,
  Transilien, RER, SNCB...) avec leurs arrets.

Les requetes sont volumineuses : elles ne sont lancees qu'a la demande et le
resultat brut est conserve dans data/reference/raw/osm pour eviter de
solliciter inutilement les serveurs Overpass (usage raisonnable exige).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

from ..sources import SOURCES
from ..store import LineRecord, ReferenceStore, RouteRecord, haversine_km
from ..service_category import categorize
from .common import SourceUnavailable, download

log = logging.getLogger("railfine.import.osm")

COUNTRY_ISO = {"FR": "FR", "BE": "BE"}

LINES_QUERY = """[out:json][timeout:900][maxsize:1073741824];
area["ISO3166-1"="{cc}"][admin_level=2]->.a;
way(area.a)["railway"="rail"]["usage"~"^(main|branch)$"]["service"!~"."];
out tags geom;"""

ROUTES_QUERY = """[out:json][timeout:900][maxsize:1073741824];
area["ISO3166-1"="{cc}"][admin_level=2]->.a;
rel(area.a)["route"="train"];
out tags geom;"""


def _overpass(query: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 100:
        return dest
    errors = []
    for url in SOURCES["osm_overpass"].urls:
        try:
            return download(url, dest, timeout=1200, retries=1, data={"data": query})
        except SourceUnavailable as exc:
            errors.append(str(exc))
    raise SourceUnavailable(" | ".join(errors))


def _way_line(geometry: list[dict]) -> LineString | None:
    coords = [(p["lon"], p["lat"]) for p in geometry or [] if p]
    return LineString(coords) if len(coords) >= 2 else None


def parse_lines(elements: list[dict], cc: str) -> list[LineRecord]:
    groups: dict[tuple, dict] = defaultdict(lambda: {"lines": [], "tags": {}})
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        line = _way_line(el.get("geometry"))
        if line is None:
            continue
        hs = tags.get("highspeed") == "yes"
        ref = tags.get("ref:FR:SNCF_Reseau") or tags.get("railway:ref") or tags.get("ref")
        key = (ref or tags.get("name") or f"way{el['id']}", tags.get("usage"), hs)
        g = groups[key]
        g["lines"].append(line)
        for k in ("name", "usage", "electrified", "maxspeed", "operator", "gauge"):
            if tags.get(k) and k not in g["tags"]:
                g["tags"][k] = tags[k]
        g["ref"] = ref
    out = []
    for i, ((label, usage, hs), g) in enumerate(groups.items()):
        merged = linemerge(g["lines"])
        geom = merged if isinstance(merged, (LineString, MultiLineString)) else MultiLineString(g["lines"])
        speed = g["tags"].get("maxspeed")
        try:
            max_speed = int(str(speed).split()[0]) if speed else None
        except ValueError:
            max_speed = None
        out.append(
            LineRecord(
                id=f"osm:{cc}:{i}",
                code=g.get("ref"),
                name=g["tags"].get("name") or (f"Ligne {g['ref']}" if g.get("ref") else None),
                geom=geom,
                country=cc,
                source="osm_overpass",
                infra_type="lgv" if hs else ("classique" if usage == "main" else "raccordement" if usage == "branch" else "inconnu"),
                status="exploitee",
                electrified=g["tags"].get("electrified"),
                max_speed=max_speed,
                extra={"usage": usage, "operator": g["tags"].get("operator")},
            )
        )
    return out


def _nearest_station(conn: sqlite3.Connection, lon: float, lat: float, max_km: float = 0.4) -> str | None:
    d = 0.01
    rows = conn.execute(
        """SELECT s.id, s.lon, s.lat FROM stations_rtree r JOIN stations s ON s.rid = r.rid
           WHERE r.minx >= ? AND r.maxx <= ? AND r.miny >= ? AND r.maxy <= ? AND s.kind='station'""",
        (lon - d, lon + d, lat - d, lat + d),
    ).fetchall()
    best = None
    for sid, slon, slat in rows:
        dist = haversine_km(lon, lat, slon, slat)
        if dist <= max_km and (best is None or dist < best[0]):
            best = (dist, sid)
    return best[1] if best else None


def parse_routes(elements: list[dict], cc: str, conn: sqlite3.Connection | None) -> list[RouteRecord]:
    out = []
    for el in elements:
        if el.get("type") != "relation":
            continue
        tags = el.get("tags") or {}
        lines = []
        stops: list[str] = []
        for m in el.get("members") or []:
            if m.get("type") == "way" and m.get("role", "") in ("", "forward", "backward", "route"):
                line = _way_line(m.get("geometry"))
                if line is not None:
                    lines.append(line)
            elif m.get("type") == "node" and m.get("role", "").startswith("stop") and conn is not None:
                if "lat" in m and "lon" in m:
                    sid = _nearest_station(conn, m["lon"], m["lat"])
                    if sid and (not stops or stops[-1] != sid):
                        stops.append(sid)
        geom = None
        if lines:
            merged = linemerge(lines)
            geom = merged if isinstance(merged, (LineString, MultiLineString)) else MultiLineString(lines)
        category = categorize(tags.get("network"), tags.get("operator"), tags.get("name"), tags.get("ref"), tags.get("service"),
                              tags.get("brand"))
        out.append(
            RouteRecord(
                id=f"osm:rel:{el['id']}",
                category=category,
                source="osm_overpass",
                short_name=tags.get("ref"),
                long_name=tags.get("name") or " - ".join(x for x in (tags.get("from"), tags.get("to")) if x) or None,
                operator=tags.get("operator"),
                network=tags.get("network"),
                country=cc,
                stops=stops,
                geom=geom,
                extra={"service": tags.get("service"), "osm_relation": el["id"]},
            )
        )
    return out


def import_osm(store: ReferenceStore, raw_dir: Path, countries=("FR", "BE"), what=("lines", "routes"),
               refresh: bool = False) -> dict:
    result = {}
    all_lines: list[LineRecord] = []
    all_routes: list[RouteRecord] = []
    conn = store.connect()
    try:
        for cc in countries:
            if "lines" in what:
                dest = raw_dir / "osm" / f"rail_{cc}.json"
                if refresh and dest.exists():
                    dest.unlink()
                path = _overpass(LINES_QUERY.format(cc=COUNTRY_ISO[cc]), dest)
                els = json.loads(path.read_text(encoding="utf-8")).get("elements", [])
                lines = parse_lines(els, cc)
                all_lines.extend(lines)
                result[f"lines_{cc}"] = len(lines)
            if "routes" in what:
                dest = raw_dir / "osm" / f"routes_{cc}.json"
                if refresh and dest.exists():
                    dest.unlink()
                path = _overpass(ROUTES_QUERY.format(cc=COUNTRY_ISO[cc]), dest)
                els = json.loads(path.read_text(encoding="utf-8")).get("elements", [])
                routes = parse_routes(els, cc, conn)
                all_routes.extend(routes)
                result[f"routes_{cc}"] = len(routes)
    finally:
        conn.close()
    if "lines" in what:
        store.replace_lines("osm_overpass", all_lines)
    if "routes" in what:
        store.replace_routes("osm_overpass", all_routes)
    store.log_run("osm_overpass", "ok", len(all_lines) + len(all_routes), origin=json.dumps(result))
    return result
