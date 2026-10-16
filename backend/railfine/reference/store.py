"""Base de reference ferroviaire (SQLite + index spatial R*Tree).

Trois objets distincts, jamais confondus :
- ``lines``  : lignes PHYSIQUES (infrastructure : voies, code ligne RFN / Infrabel) ;
- ``routes`` : itineraires COMMERCIAUX (ex. "TER Lyon - Grenoble", "IC Bruxelles - Liege") ;
- ``trains`` : CIRCULATIONS identifiees par un numero de train, avec leurs arrets et dates.

Les gares sont fusionnees par code UIC quand plusieurs sources les decrivent ;
la source la plus prioritaire fournit le nom et la position.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from shapely import wkb
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from ..db import connect
from .normalize import bilingual_variant, clean_display_name, match_key, normalize_name
from .sources import SOURCES

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS source_runs(
  source_id TEXT PRIMARY KEY, fetched_at TEXT, status TEXT, records INTEGER, message TEXT, origin TEXT
);
CREATE TABLE IF NOT EXISTS station_records(
  source TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL, uic TEXT, country TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, importance INTEGER, kind TEXT, aliases TEXT, extra TEXT,
  PRIMARY KEY(source, source_id)
);
CREATE TABLE IF NOT EXISTS stations(
  rid INTEGER PRIMARY KEY,
  id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  uic TEXT,
  country TEXT,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  importance INTEGER NOT NULL DEFAULT 3,
  kind TEXT NOT NULL DEFAULT 'station',
  source TEXT NOT NULL,
  sources TEXT,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_stations_uic ON stations(uic);
CREATE TABLE IF NOT EXISTS station_names(
  station_id TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL, lang TEXT, source TEXT,
  UNIQUE(station_id, key)
);
CREATE INDEX IF NOT EXISTS idx_station_names_key ON station_names(key);
CREATE VIRTUAL TABLE IF NOT EXISTS stations_rtree USING rtree(rid, minx, maxx, miny, maxy);
CREATE TABLE IF NOT EXISTS lines(
  rid INTEGER PRIMARY KEY,
  id TEXT UNIQUE NOT NULL,
  code TEXT,
  name TEXT,
  country TEXT,
  infra_type TEXT NOT NULL DEFAULT 'inconnu',
  status TEXT,
  electrified TEXT,
  max_speed INTEGER,
  tracks TEXT,
  length_km REAL,
  source TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  extra TEXT,
  geom BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lines_source ON lines(source);
CREATE INDEX IF NOT EXISTS idx_lines_code ON lines(code);
CREATE VIRTUAL TABLE IF NOT EXISTS lines_rtree USING rtree(rid, minx, maxx, miny, maxy);
CREATE TABLE IF NOT EXISTS routes(
  rid INTEGER PRIMARY KEY,
  id TEXT UNIQUE NOT NULL,
  short_name TEXT,
  long_name TEXT,
  category TEXT NOT NULL,
  operator TEXT,
  network TEXT,
  country TEXT,
  source TEXT NOT NULL,
  extra TEXT,
  geom BLOB
);
CREATE INDEX IF NOT EXISTS idx_routes_short ON routes(short_name);
CREATE VIRTUAL TABLE IF NOT EXISTS routes_rtree USING rtree(rid, minx, maxx, miny, maxy);
CREATE TABLE IF NOT EXISTS route_stops(
  route_id TEXT NOT NULL, seq INTEGER NOT NULL, station_id TEXT NOT NULL, PRIMARY KEY(route_id, seq)
);
CREATE TABLE IF NOT EXISTS trains(
  id INTEGER PRIMARY KEY,
  train_number TEXT NOT NULL,
  route_id TEXT,
  category TEXT,
  operator TEXT,
  pattern TEXT NOT NULL,
  dates TEXT,
  first_date TEXT,
  last_date TEXT,
  source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trains_number ON trains(train_number);
CREATE TABLE IF NOT EXISTS basemap(id TEXT PRIMARY KEY, name TEXT, geojson TEXT NOT NULL, source TEXT);
"""

# Rayon (km) en deca duquel deux enregistrements de meme nom sont consideres comme la meme gare.
SAME_STATION_KM = 1.5


@dataclass
class StationRecord:
    source: str
    source_id: str
    name: str
    lat: float
    lon: float
    uic: str | None = None
    country: str | None = None
    importance: int = 3
    kind: str = "station"
    aliases: list[tuple[str, str | None]] = field(default_factory=list)  # (nom, langue)
    extra: dict = field(default_factory=dict)


@dataclass
class LineRecord:
    id: str
    geom: BaseGeometry
    source: str
    code: str | None = None
    name: str | None = None
    country: str | None = None
    infra_type: str = "inconnu"
    status: str | None = None
    electrified: str | None = None
    max_speed: int | None = None
    tracks: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class RouteRecord:
    id: str
    category: str
    source: str
    short_name: str | None = None
    long_name: str | None = None
    operator: str | None = None
    network: str | None = None
    country: str | None = None
    stops: list[str] = field(default_factory=list)
    geom: BaseGeometry | None = None
    extra: dict = field(default_factory=dict)


def normalize_uic(code: str | int | None) -> str | None:
    """Ramene un code UIC a 7 chiffres (pays + gare), sans cle de controle.

    "87751230" (UIC8 SNCF) -> "8775123" ; "008814001" (iRail) -> "8814001".
    """
    if code is None:
        return None
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if not digits:
        return None
    digits = digits.lstrip("0")
    if len(digits) == 8:
        digits = digits[:7]
    if len(digits) == 6:  # code sans indicatif pays : ambigu, on l'ignore
        return None
    if len(digits) != 7:
        return None
    return digits


def as_multiline(geom: BaseGeometry) -> MultiLineString | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, MultiLineString):
        return geom
    if isinstance(geom, LineString):
        return MultiLineString([geom])
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (LineString, MultiLineString))]
    lines: list[LineString] = []
    for p in parts:
        lines.extend(p.geoms if isinstance(p, MultiLineString) else [p])
    return MultiLineString(lines) if lines else None


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0088 * asin(min(1.0, sqrt(a)))


def geom_length_km(geom: BaseGeometry) -> float:
    total = 0.0
    for line in as_multiline(geom).geoms if as_multiline(geom) else []:
        coords = list(line.coords)
        for (x1, y1, *_), (x2, y2, *_) in zip(coords, coords[1:]):
            total += haversine_km(x1, y1, x2, y2)
    return total


class ReferenceStore:
    def __init__(self, path: Path):
        self.path = path

    # -- connexion -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        conn.executescript(SCHEMA)
        return conn

    def exists(self) -> bool:
        return self.path.exists()

    # -- meta ------------------------------------------------------------
    @staticmethod
    def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def version(self) -> str:
        if not self.exists():
            return "empty"
        conn = self.connect()
        try:
            return self.get_meta(conn, "version", "empty") or "empty"
        finally:
            conn.close()

    @staticmethod
    def record_run(conn, source_id: str, status: str, records: int, message: str = "", origin: str = "") -> None:
        conn.execute(
            """INSERT INTO source_runs(source_id, fetched_at, status, records, message, origin)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET fetched_at=excluded.fetched_at, status=excluded.status,
               records=excluded.records, message=excluded.message, origin=excluded.origin""",
            (source_id, time.strftime("%Y-%m-%dT%H:%M:%S"), status, records, message[:2000], origin[:500]),
        )

    def log_run(self, source_id: str, status: str, records: int, message: str = "", origin: str = "") -> None:
        conn = self.connect()
        try:
            self.record_run(conn, source_id, status, records, message, origin)
            conn.commit()
        finally:
            conn.close()

    # -- ecriture : gares ------------------------------------------------
    def replace_station_records(self, source: str, records: Iterable[StationRecord]) -> int:
        conn = self.connect()
        try:
            conn.execute("DELETE FROM station_records WHERE source=?", (source,))
            n = 0
            for r in records:
                conn.execute(
                    """INSERT OR REPLACE INTO station_records(source, source_id, name, uic, country, lat, lon,
                       importance, kind, aliases, extra) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        source,
                        str(r.source_id),
                        clean_display_name(r.name),
                        normalize_uic(r.uic),
                        r.country,
                        float(r.lat),
                        float(r.lon),
                        int(r.importance or 3),
                        r.kind or "station",
                        json.dumps(r.aliases, ensure_ascii=False),
                        json.dumps(r.extra, ensure_ascii=False) if r.extra else None,
                    ),
                )
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()

    # -- ecriture : lignes -----------------------------------------------
    def replace_lines(self, source: str, records: Iterable[LineRecord]) -> int:
        conn = self.connect()
        try:
            old = [r[0] for r in conn.execute("SELECT rid FROM lines WHERE source=?", (source,))]
            for rid in old:
                conn.execute("DELETE FROM lines_rtree WHERE rid=?", (rid,))
            conn.execute("DELETE FROM lines WHERE source=?", (source,))
            n = 0
            for r in records:
                ml = as_multiline(r.geom)
                if ml is None:
                    continue
                minx, miny, maxx, maxy = ml.bounds
                cur = conn.execute(
                    """INSERT OR REPLACE INTO lines(id, code, name, country, infra_type, status, electrified, max_speed,
                       tracks, length_km, source, extra, geom) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.id,
                        r.code,
                        r.name,
                        r.country,
                        r.infra_type or "inconnu",
                        r.status,
                        r.electrified,
                        r.max_speed,
                        r.tracks,
                        round(geom_length_km(ml), 3),
                        source,
                        json.dumps(r.extra, ensure_ascii=False) if r.extra else None,
                        wkb.dumps(ml),
                    ),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO lines_rtree(rid, minx, maxx, miny, maxy) VALUES(?,?,?,?,?)",
                    (cur.lastrowid, minx, maxx, miny, maxy),
                )
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()

    # -- ecriture : itineraires et circulations ----------------------------
    def replace_routes(self, source: str, routes: Iterable[RouteRecord]) -> int:
        conn = self.connect()
        try:
            old = [(r[0], r[1]) for r in conn.execute("SELECT rid, id FROM routes WHERE source=?", (source,))]
            for rid, rid_text in old:
                conn.execute("DELETE FROM routes_rtree WHERE rid=?", (rid,))
                conn.execute("DELETE FROM route_stops WHERE route_id=?", (rid_text,))
            conn.execute("DELETE FROM routes WHERE source=?", (source,))
            n = 0
            for r in routes:
                geom_blob = None
                bounds = None
                if r.geom is not None and not r.geom.is_empty:
                    ml = as_multiline(r.geom)
                    if ml is not None:
                        geom_blob = wkb.dumps(ml)
                        bounds = ml.bounds
                cur = conn.execute(
                    """INSERT OR REPLACE INTO routes(id, short_name, long_name, category, operator, network, country,
                       source, extra, geom) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.id,
                        r.short_name,
                        r.long_name,
                        r.category,
                        r.operator,
                        r.network,
                        r.country,
                        source,
                        json.dumps(r.extra, ensure_ascii=False) if r.extra else None,
                        geom_blob,
                    ),
                )
                if bounds:
                    conn.execute(
                        "INSERT OR REPLACE INTO routes_rtree(rid, minx, maxx, miny, maxy) VALUES(?,?,?,?,?)",
                        (cur.lastrowid, bounds[0], bounds[2], bounds[1], bounds[3]),
                    )
                for seq, sid in enumerate(r.stops):
                    conn.execute("INSERT OR REPLACE INTO route_stops(route_id, seq, station_id) VALUES(?,?,?)", (r.id, seq, sid))
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()

    def replace_trains(self, source: str, rows: Iterable[dict]) -> int:
        conn = self.connect()
        try:
            conn.execute("DELETE FROM trains WHERE source=?", (source,))
            n = 0
            for t in rows:
                conn.execute(
                    """INSERT INTO trains(train_number, route_id, category, operator, pattern, dates, first_date,
                       last_date, source) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        t["train_number"],
                        t.get("route_id"),
                        t.get("category"),
                        t.get("operator"),
                        json.dumps(t["pattern"], ensure_ascii=False),
                        t.get("dates"),
                        t.get("first_date"),
                        t.get("last_date"),
                        source,
                    ),
                )
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()

    def set_basemap(self, items: list[tuple[str, str, dict]], source: str) -> None:
        conn = self.connect()
        try:
            conn.execute("DELETE FROM basemap WHERE source=?", (source,))
            for bid, name, gj in items:
                conn.execute(
                    "INSERT OR REPLACE INTO basemap(id, name, geojson, source) VALUES(?,?,?,?)",
                    (bid, name, json.dumps(gj, separators=(",", ":")), source),
                )
            conn.commit()
        finally:
            conn.close()

    # -- consolidation ---------------------------------------------------
    def finalize(self) -> dict:
        """Fusionne les gares, choisit la meilleure source de lignes par pays, incremente la version."""
        conn = self.connect()
        try:
            stats = self._merge_stations(conn)
            self._activate_best_line_sources(conn)
            self.set_meta(conn, "version", str(int(time.time())))
            self.set_meta(conn, "finalized_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
            conn.commit()
            return stats
        finally:
            conn.close()

    def _merge_stations(self, conn: sqlite3.Connection) -> dict:
        rows = conn.execute("SELECT * FROM station_records").fetchall()

        def prio(source: str) -> int:
            s = SOURCES.get(source)
            return s.priority if s else 50

        rows = sorted(rows, key=lambda r: (prio(r["source"]), r["importance"] or 3))
        merged: dict[str, dict] = {}
        by_uic: dict[str, str] = {}
        by_key: dict[str, list[str]] = {}

        for r in rows:
            uic = r["uic"]
            key = match_key(r["name"])
            target = None
            if uic and uic in by_uic:
                target = by_uic[uic]
            elif key in by_key:
                # meme nom normalise et position proche : meme gare (sinon : homonyme distinct)
                for cand in by_key[key]:
                    m = merged[cand]
                    if haversine_km(m["lon"], m["lat"], r["lon"], r["lat"]) <= SAME_STATION_KM:
                        if not uic or not m["uic"] or m["uic"] == uic:
                            target = cand
                            break
            aliases = [(r["name"], None)] + [tuple(a) for a in json.loads(r["aliases"] or "[]")]
            if target is None:
                sid = f"uic:{uic}" if uic else f"{r['source']}:{r['source_id']}"
                if sid in merged:
                    sid = f"{r['source']}:{r['source_id']}"
                merged[sid] = {
                    "id": sid,
                    "name": r["name"],
                    "uic": uic,
                    "country": r["country"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "importance": r["importance"] or 3,
                    "kind": r["kind"] or "station",
                    "source": r["source"],
                    "sources": {r["source"]},
                    "aliases": list(aliases),
                    "extra": json.loads(r["extra"]) if r["extra"] else {},
                }
                if uic:
                    by_uic[uic] = sid
                by_key.setdefault(key, []).append(sid)
            else:
                m = merged[target]
                m["sources"].add(r["source"])
                m["aliases"].extend(aliases)
                m["importance"] = min(m["importance"], r["importance"] or 3)
                if m["kind"] != "station" and (r["kind"] or "station") == "station":
                    m["kind"] = "station"
                if not m["uic"] and uic:
                    m["uic"] = uic
                    by_uic[uic] = target
                if not m["country"] and r["country"]:
                    m["country"] = r["country"]
                if r["extra"]:
                    for k, v in json.loads(r["extra"]).items():
                        m["extra"].setdefault(k, v)

        conn.execute("DELETE FROM stations")
        conn.execute("DELETE FROM stations_rtree")
        conn.execute("DELETE FROM station_names")
        for m in merged.values():
            cur = conn.execute(
                """INSERT INTO stations(id, name, uic, country, lat, lon, importance, kind, source, sources, extra)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    m["id"],
                    m["name"],
                    m["uic"],
                    m["country"],
                    m["lat"],
                    m["lon"],
                    m["importance"],
                    m["kind"],
                    m["source"],
                    ",".join(sorted(m["sources"])),
                    json.dumps(m["extra"], ensure_ascii=False) if m["extra"] else None,
                ),
            )
            conn.execute(
                "INSERT INTO stations_rtree(rid, minx, maxx, miny, maxy) VALUES(?,?,?,?,?)",
                (cur.lastrowid, m["lon"], m["lon"], m["lat"], m["lat"]),
            )
            seen: set[str] = set()
            for alias, lang in m["aliases"]:
                if not alias:
                    continue
                for variant in (alias, bilingual_variant(alias)):
                    if not variant:
                        continue
                    k = match_key(variant)
                    if not k or k in seen:
                        continue
                    seen.add(k)
                    conn.execute(
                        "INSERT OR IGNORE INTO station_names(station_id, name, key, lang, source) VALUES(?,?,?,?,?)",
                        (m["id"], clean_display_name(alias), k, lang, m["source"]),
                    )
        return {"stations": len(merged), "records": len(rows)}

    def _activate_best_line_sources(self, conn: sqlite3.Connection) -> None:
        counts = conn.execute("SELECT country, source, COUNT(*) FROM lines GROUP BY country, source").fetchall()
        best: dict[str | None, tuple[int, str]] = {}
        for country, source, n in counts:
            if not n:
                continue
            p = SOURCES[source].priority if source in SOURCES else 50
            if country not in best or p < best[country][0]:
                best[country] = (p, source)
        conn.execute("UPDATE lines SET active=0")
        for country, (_, source) in best.items():
            if country is None:
                conn.execute("UPDATE lines SET active=1 WHERE country IS NULL AND source=?", (source,))
            else:
                conn.execute("UPDATE lines SET active=1 WHERE country=? AND source=?", (country, source))

    # -- lecture ---------------------------------------------------------
    def counts(self) -> dict:
        if not self.exists():
            return {"stations": 0, "lines": 0, "active_lines": 0, "routes": 0, "trains": 0}
        conn = self.connect()
        try:
            return {
                "stations": conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0],
                "lines": conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0],
                "active_lines": conn.execute("SELECT COUNT(*) FROM lines WHERE active=1").fetchone()[0],
                "routes": conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0],
                "trains": conn.execute("SELECT COUNT(DISTINCT train_number) FROM trains").fetchone()[0],
                "line_sources": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT source, country, active, COUNT(*) AS n, ROUND(SUM(length_km)) AS km FROM lines GROUP BY source, country, active"
                    )
                ],
            }
        finally:
            conn.close()

    def source_runs(self) -> list[dict]:
        if not self.exists():
            return []
        conn = self.connect()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM source_runs ORDER BY source_id")]
        finally:
            conn.close()
