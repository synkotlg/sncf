"""Import GTFS (horaires theoriques) : itineraires commerciaux et circulations (numeros de train).

Le GTFS est lu directement dans l'archive ZIP (aucune extraction sur disque,
donc pas de risque de traversee de repertoire). Seules les lignes ferroviaires
(route_type 2 et 100-199) sont conservees ; les autocars sont ignores.

Limites : un GTFS couvre une fenetre de dates (quelques semaines a quelques
mois). Un numero de train ancien peut ne plus y figurer, ou designer un autre
parcours : la correspondance tient compte de la date (confiance reduite hors
fenetre).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from ..normalize import match_key
from ..service_category import SNCB_SHORT_NAMES, categorize
from ..sources import SOURCES
from ..store import ReferenceStore, RouteRecord, haversine_km, normalize_uic
from .common import SourceUnavailable, download, first_available

log = logging.getLogger("railfine.import.gtfs")

RAIL_ROUTE_TYPES = {2} | set(range(100, 200))
UIC_IN_ID = re.compile(r"(?<!\d)(8[78]\d{5,6})(?!\d)")
SNCF_TRAIN_IN_TRIP = re.compile(r"OCESN(\d{3,6})")


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    member = next((n for n in zf.namelist() if n.split("/")[-1] == name), None)
    if member is None:
        return []
    with zf.open(member) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def _service_dates(zf: zipfile.ZipFile) -> dict[str, set[str]]:
    dates: dict[str, set[str]] = defaultdict(set)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for row in _read_csv(zf, "calendar.txt"):
        try:
            start = date(int(row["start_date"][:4]), int(row["start_date"][4:6]), int(row["start_date"][6:8]))
            end = date(int(row["end_date"][:4]), int(row["end_date"][4:6]), int(row["end_date"][6:8]))
        except (KeyError, ValueError):
            continue
        if (end - start).days > 800:
            end = start + timedelta(days=800)
        flags = [row.get(d) == "1" for d in days]
        d = start
        while d <= end:
            if flags[d.weekday()]:
                dates[row["service_id"]].add(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
    for row in _read_csv(zf, "calendar_dates.txt"):
        sid, ds, et = row.get("service_id"), row.get("date"), row.get("exception_type")
        if not sid or not ds:
            continue
        if et == "1":
            dates[sid].add(ds)
        elif et == "2":
            dates[sid].discard(ds)
    return dates


class StationResolver:
    """Rattache un arret GTFS a une gare de reference : code UIC d'abord, puis proximite + nom."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.by_uic = {r[0]: r[1] for r in conn.execute("SELECT uic, id FROM stations WHERE uic IS NOT NULL")}
        self.cache: dict[str, str | None] = {}

    def resolve(self, stop_id: str, name: str | None, lat: float | None, lon: float | None) -> str | None:
        if stop_id in self.cache:
            return self.cache[stop_id]
        sid = None
        for m in UIC_IN_ID.finditer(stop_id or ""):
            uic = normalize_uic(m.group(1))
            if uic and uic in self.by_uic:
                sid = self.by_uic[uic]
                break
        if sid is None and lat is not None and lon is not None:
            d = 0.01
            rows = self.conn.execute(
                """SELECT s.id, s.name, s.lon, s.lat FROM stations_rtree r JOIN stations s ON s.rid=r.rid
                   WHERE r.minx>=? AND r.maxx<=? AND r.miny>=? AND r.maxy<=?""",
                (lon - d, lon + d, lat - d, lat + d),
            ).fetchall()
            best = None
            for rid, rname, rlon, rlat in rows:
                dist = haversine_km(lon, lat, rlon, rlat)
                sim = fuzz.token_set_ratio(match_key(name), match_key(rname)) if name else 0
                if dist <= 0.5 and sim >= 70 and (best is None or dist < best[0]):
                    best = (dist, rid)
            sid = best[1] if best else None
        self.cache[stop_id] = sid
        return sid


def _train_number(trip: dict) -> str | None:
    for key in ("trip_short_name", "trip_headsign"):
        v = (trip.get(key) or "").strip()
        if re.fullmatch(r"\d{2,6}", v):
            return v.lstrip("0") or v
    m = SNCF_TRAIN_IN_TRIP.search(trip.get("trip_id") or "")
    if m:
        return m.group(1).lstrip("0")
    return None


def parse_gtfs(zip_path: Path, conn: sqlite3.Connection, source_id: str, country: str | None) -> tuple[list[RouteRecord], list[dict]]:
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.file_size > 3_000_000_000:
                raise ValueError("Fichier GTFS anormalement volumineux")
        agencies = {r.get("agency_id", ""): r.get("agency_name", "") for r in _read_csv(zf, "agency.txt")}
        default_agency = next(iter(agencies.values()), "")
        routes = {}
        for r in _read_csv(zf, "routes.txt"):
            try:
                rtype = int(r.get("route_type") or -1)
            except ValueError:
                rtype = -1
            if rtype in RAIL_ROUTE_TYPES:
                routes[r["route_id"]] = r
        trips = {t["trip_id"]: t for t in _read_csv(zf, "trips.txt") if t.get("route_id") in routes}
        stops = {s["stop_id"]: s for s in _read_csv(zf, "stops.txt")}
        service_dates = _service_dates(zf)
        member = next((n for n in zf.namelist() if n.split("/")[-1] == "stop_times.txt"), None)
        if member is None:
            raise ValueError("stop_times.txt absent du GTFS")
        with zf.open(member) as fh:
            st = pd.read_csv(fh, usecols=["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"],
                             dtype=str, keep_default_na=False, encoding="utf-8-sig")
    st = st[st["trip_id"].isin(trips.keys())]
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
    st = st.sort_values(["trip_id", "stop_sequence"])

    resolver = StationResolver(conn)

    def station_for(stop_id: str) -> str | None:
        s = stops.get(stop_id) or {}
        try:
            lat, lon = float(s.get("stop_lat") or "nan"), float(s.get("stop_lon") or "nan")
            if lat != lat:
                lat = lon = None
        except ValueError:
            lat = lon = None
        sid = resolver.resolve(stop_id, s.get("stop_name"), lat, lon)
        if sid is None and s.get("parent_station"):
            p = stops.get(s["parent_station"]) or {}
            sid = resolver.resolve(s["parent_station"], p.get("stop_name"), lat, lon)
        return sid

    trains: dict[tuple, dict] = {}
    route_patterns: dict[str, Counter] = defaultdict(Counter)
    route_stop_hint: dict[str, str] = {}
    for trip_id, grp in st.groupby("trip_id", sort=False):
        trip = trips[trip_id]
        route = routes[trip["route_id"]]
        pattern = []
        for stop_id, arr, dep in zip(grp["stop_id"], grp["arrival_time"], grp["departure_time"]):
            pattern.append([station_for(stop_id), (arr or "")[:5] or None, (dep or "")[:5] or None, stops.get(stop_id, {}).get("stop_name")])
            route_stop_hint.setdefault(trip["route_id"], stop_id)
        stations = tuple(p[0] for p in pattern)
        if sum(1 for s in stations if s) >= 2:
            route_patterns[trip["route_id"]][tuple(s for s in stations if s)] += 1
        number = _train_number(trip)
        if not number:
            continue
        key = (number, trip["route_id"], stations)
        entry = trains.setdefault(key, {"train_number": number, "route_id": f"gtfs:{source_id}:{trip['route_id']}",
                                        "pattern": pattern, "dates": set()})
        entry["dates"] |= service_dates.get(trip.get("service_id"), set())

    route_records: list[RouteRecord] = []
    categories: dict[str, str] = {}
    for rid, r in routes.items():
        agency = agencies.get(r.get("agency_id", ""), default_agency)
        short = (r.get("route_short_name") or "").strip()
        cat = categorize(agency, None, r.get("route_long_name"), short, r.get("route_desc"), route_stop_hint.get(rid))
        if cat == "AUTRE" and (country == "BE" or short.upper() in SNCB_SHORT_NAMES and "sncb" in agency.lower()):
            cat = "SNCB"
        categories[rid] = cat
        patterns = route_patterns.get(rid)
        stops_seq = list(max(patterns.items(), key=lambda kv: (kv[1], len(kv[0])))[0]) if patterns else []
        route_records.append(RouteRecord(id=f"gtfs:{source_id}:{rid}", category=cat, source=source_id, short_name=short or None,
                                         long_name=(r.get("route_long_name") or "").strip() or None, operator=agency or None,
                                         country=country, stops=stops_seq,
                                         extra={"route_type": r.get("route_type"), "gtfs_route_id": rid}))
    train_rows = []
    for (number, rid, _), t in trains.items():
        ds = sorted(t["dates"])
        train_rows.append({
            "train_number": number,
            "route_id": t["route_id"],
            "category": categories.get(rid, "AUTRE"),
            "operator": agencies.get(routes[rid].get("agency_id", ""), default_agency) or None,
            "pattern": t["pattern"],
            "dates": ",".join(ds) if ds else None,
            "first_date": ds[0] if ds else None,
            "last_date": ds[-1] if ds else None,
        })
    return route_records, train_rows


def import_gtfs(store: ReferenceStore, raw_dir: Path, source_id: str, file: Path | None = None, url: str | None = None,
                country: str | None = None) -> dict:
    if source_id not in SOURCES:
        raise ValueError(f"source GTFS inconnue : {source_id}")
    src = SOURCES[source_id]
    if file:
        path, origin = file, str(file)
    elif url:
        path, origin = download(url, raw_dir / "gtfs" / f"{source_id}.zip", timeout=900), url
    else:
        path, origin = first_available(src.urls, raw_dir / "gtfs" / f"{source_id}.zip", timeout=900)
    if not zipfile.is_zipfile(path):
        raise SourceUnavailable(f"{origin} n'est pas une archive ZIP GTFS")
    country = country or ("BE" if source_id == "sncb_gtfs" else "FR")
    conn = store.connect()
    try:
        routes, trains = parse_gtfs(path, conn, source_id, country)
    finally:
        conn.close()
    n_routes = store.replace_routes(source_id, routes)
    n_trains = store.replace_trains(source_id, trains)
    store.log_run(source_id, "ok", n_trains, origin=origin, message=f"{n_routes} itineraires, {n_trains} circulations")
    return {"routes": n_routes, "trains": n_trains}
