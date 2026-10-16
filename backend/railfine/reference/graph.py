"""Graphe du reseau PHYSIQUE et calcul de trajets entre gares.

Construction :
1. chaque ligne active (statut exploite ou inconnu) est decoupee en parties ;
2. les extremites "pendantes" sont accrochees a la partie voisine la plus proche
   (jonctions en T), selon une tolerance propre a la precision de la source ;
3. les gares de voyageurs sont projetees sur la voie la plus proche et deviennent
   des noeuds du graphe (les aretes s'arretent donc aux gares) ;
4. les sommets partages deviennent des noeuds ; les aretes conservent leur
   geometrie, leur longueur et l'identifiant de la ligne physique.

Un trajet calcule est le PLUS COURT CHEMIN sur l'infrastructure : c'est une
hypothese de parcours, pas la circulation reelle d'un train.
"""

from __future__ import annotations

import heapq
import logging
import math
import pickle
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely import wkb
from shapely.geometry import LineString, Point

from .store import ReferenceStore, haversine_km

log = logging.getLogger("railfine.graph")

# Tolerances (km) : raccord des extremites de lignes / projection des gares sur la voie.
SOURCE_TOLERANCES = {
    "sncf_rfn_lines": (0.08, 0.6),
    "infrabel_lines": (0.08, 0.6),
    "osm_overpass": (0.03, 0.5),
    "naturalearth_rail": (2.5, 4.0),
}
DEFAULT_TOLERANCE = (0.1, 0.8)
EXCLUDED_STATUSES = ("fermee", "declassee", "retranchee", "deposee", "neutralisee", "transferee")
GRAPH_FORMAT = 3


@dataclass
class Edge:
    u: int
    v: int
    coords: np.ndarray  # (n, 2) lon/lat
    length_km: float
    line_id: str


@dataclass
class PathResult:
    station_ids: list[str]
    edges: list[int]
    length_km: float
    coords: list[list[float]]
    lines: list[dict]
    missing_legs: list[tuple[str, str]] = field(default_factory=list)

    def to_geojson(self) -> dict:
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": self.coords},
                "properties": {"length_km": round(self.length_km, 1), "lines": self.lines}}


def _deg(km: float) -> float:
    return km / 111.0


def _poly_length_km(coords: np.ndarray) -> float:
    if len(coords) < 2:
        return 0.0
    lon1, lat1 = np.radians(coords[:-1, 0]), np.radians(coords[:-1, 1])
    lon2, lat2 = np.radians(coords[1:, 0]), np.radians(coords[1:, 1])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return float(np.sum(2 * 6371.0088 * np.arcsin(np.minimum(1.0, np.sqrt(a)))))


class RailGraph:
    def __init__(self, version: str):
        self.version = version
        self.nodes: list[tuple[float, float]] = []
        self.edges: list[Edge] = []
        self.adj: list[list[int]] = []
        self.station_node: dict[str, int] = {}
        self.station_snap_km: dict[str, float] = {}
        self.line_names: dict[str, dict] = {}

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, store: ReferenceStore) -> "RailGraph":
        conn = store.connect()
        try:
            version = store.get_meta(conn, "version", "empty") or "empty"
            graph = cls(version)
            parts: list[np.ndarray] = []
            part_line: list[str] = []
            part_tol: list[tuple[float, float]] = []
            for row in conn.execute("SELECT id, code, name, infra_type, status, source, geom FROM lines WHERE active=1"):
                status = (row["status"] or "").lower()
                if status and any(s in status for s in EXCLUDED_STATUSES) and "exploit" not in status:
                    continue
                graph.line_names[row["id"]] = {"id": row["id"], "code": row["code"], "name": row["name"],
                                               "infra_type": row["infra_type"]}
                geom = wkb.loads(row["geom"])
                for g in geom.geoms:
                    arr = np.asarray(g.coords, dtype=float)[:, :2]
                    if len(arr) >= 2:
                        parts.append(arr)
                        part_line.append(row["id"])
                        part_tol.append(SOURCE_TOLERANCES.get(row["source"], DEFAULT_TOLERANCE))
            stations = conn.execute("SELECT id, lon, lat FROM stations WHERE kind='station'").fetchall()
        finally:
            conn.close()
        if not parts:
            return graph
        graph._assemble(parts, part_line, part_tol, stations)
        log.info("graphe : %d noeuds, %d aretes, %d gares rattachees", len(graph.nodes), len(graph.edges), len(graph.station_node))
        return graph

    def _assemble(self, parts, part_line, part_tol, stations) -> None:
        geoms = [LineString(p) for p in parts]
        tree = shapely.STRtree(geoms)
        inserts: dict[int, list[tuple[float, tuple[float, float]]]] = defaultdict(list)

        # 1. raccord des extremites pendantes (jonctions en T ou extremites proches)
        end_pts, end_ref = [], []
        for i, p in enumerate(parts):
            end_pts.append(Point(p[0]))
            end_ref.append((i, 0))
            end_pts.append(Point(p[-1]))
            end_ref.append((i, -1))
        max_tol = _deg(max(t[0] for t in part_tol))
        pt_idx, geom_idx = tree.query(end_pts, predicate="dwithin", distance=max_tol)
        candidates: dict[int, list[int]] = defaultdict(list)
        for a, b in zip(pt_idx.tolist(), geom_idx.tolist()):
            if end_ref[a][0] != b:
                candidates[a].append(b)
        for a, gids in candidates.items():
            pi, pos = end_ref[a]
            pt = end_pts[a]
            tol = _deg(part_tol[pi][0])
            best = None
            for gid in gids:
                d = geoms[gid].distance(pt)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, gid)
            if best is None:
                continue
            gid = best[1]
            along = geoms[gid].project(pt)
            snapped = geoms[gid].interpolate(along)
            xy = (snapped.x, snapped.y)
            inserts[gid].append((along, xy))
            parts[pi] = parts[pi].copy()
            parts[pi][pos] = xy

        # 2. projection des gares sur la voie la plus proche
        station_xy: dict[str, tuple[float, float]] = {}
        if stations:
            spts = [Point(s["lon"], s["lat"]) for s in stations]
            max_stol = _deg(max(t[1] for t in part_tol))
            s_idx, g_idx = tree.query(spts, predicate="dwithin", distance=max_stol)
            near: dict[int, list[int]] = defaultdict(list)
            for a, b in zip(s_idx.tolist(), g_idx.tolist()):
                near[a].append(b)
            for a, gids in near.items():
                pt = spts[a]
                best = None
                for gid in gids:
                    d = geoms[gid].distance(pt)
                    if d <= _deg(part_tol[gid][1]) and (best is None or d < best[0]):
                        best = (d, gid)
                if best is None:
                    continue
                gid = best[1]
                along = geoms[gid].project(pt)
                snapped = geoms[gid].interpolate(along)
                xy = (snapped.x, snapped.y)
                inserts[gid].append((along, xy))
                sid = stations[a]["id"]
                station_xy[sid] = xy
                self.station_snap_km[sid] = round(haversine_km(pt.x, pt.y, xy[0], xy[1]), 3)

        # 3. insertion des points de raccord dans les parties
        for gid, items in inserts.items():
            base = parts[gid]
            seg_d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(base, axis=0).T))])
            merged = [(float(d), tuple(xy), 0) for d, xy in zip(seg_d, base)]
            merged += [(float(d), xy, 1) for d, xy in items]
            merged.sort(key=lambda t: (t[0], t[2]))
            out = []
            for _, xy, _ in merged:
                if not out or (abs(out[-1][0] - xy[0]) > 1e-9 or abs(out[-1][1] - xy[1]) > 1e-9):
                    out.append(xy)
            parts[gid] = np.asarray(out, dtype=float)

        # 4. noeuds = extremites + sommets partages + gares
        def key(xy) -> tuple[int, int]:
            return (int(round(xy[0] * 1e6)), int(round(xy[1] * 1e6)))

        usage: dict[tuple[int, int], int] = defaultdict(int)
        for p in parts:
            for xy in p:
                usage[key(xy)] += 1
        node_keys = set()
        for p in parts:
            node_keys.add(key(p[0]))
            node_keys.add(key(p[-1]))
        node_keys.update(k for k, n in usage.items() if n >= 2)
        station_keys = {sid: key(xy) for sid, xy in station_xy.items()}
        node_keys.update(station_keys.values())
        node_index: dict[tuple[int, int], int] = {}

        def node_of(xy) -> int:
            k = key(xy)
            idx = node_index.get(k)
            if idx is None:
                idx = len(self.nodes)
                node_index[k] = idx
                self.nodes.append((float(xy[0]), float(xy[1])))
                self.adj.append([])
            return idx

        for p, line_id in zip(parts, part_line):
            start = 0
            for j in range(1, len(p)):
                if key(p[j]) in node_keys or j == len(p) - 1:
                    seg = p[start : j + 1]
                    if len(seg) >= 2:
                        u, v = node_of(seg[0]), node_of(seg[-1])
                        length = _poly_length_km(seg)
                        if u != v or length > 0.01:
                            e = Edge(u, v, seg.astype(np.float64), length, line_id)
                            self.edges.append(e)
                            idx = len(self.edges) - 1
                            self.adj[u].append(idx)
                            if v != u:
                                self.adj[v].append(idx)
                    start = j
        for sid, k in station_keys.items():
            if k in node_index:
                self.station_node[sid] = node_index[k]

    # ------------------------------------------------------------- recherche
    def _astar(self, src: int, dst: int, max_km: float = 2500.0) -> list[tuple[int, bool]] | None:
        if src == dst:
            return []
        tx, ty = self.nodes[dst]

        def h(n: int) -> float:
            x, y = self.nodes[n]
            return haversine_km(x, y, tx, ty)

        best = {src: 0.0}
        prev: dict[int, tuple[int, int, bool]] = {}
        heap = [(h(src), 0.0, src)]
        while heap:
            _, d, n = heapq.heappop(heap)
            if n == dst:
                break
            if d > best.get(n, math.inf) or d > max_km:
                continue
            for ei in self.adj[n]:
                e = self.edges[ei]
                forward = e.u == n
                m = e.v if forward else e.u
                nd = d + e.length_km
                if nd < best.get(m, math.inf):
                    best[m] = nd
                    prev[m] = (n, ei, forward)
                    heapq.heappush(heap, (nd + h(m), nd, m))
        if dst not in prev:
            return None
        path = []
        n = dst
        while n != src:
            p, ei, forward = prev[n]
            path.append((ei, forward))
            n = p
        path.reverse()
        return path

    def path(self, station_ids: list[str]) -> PathResult | None:
        """Plus court chemin passant successivement par les gares donnees."""
        ids = [s for s in station_ids if s]
        if len(ids) < 2:
            return None
        coords: list[list[float]] = []
        edges: list[int] = []
        missing: list[tuple[str, str]] = []
        per_line: dict[str, float] = defaultdict(float)
        total = 0.0
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            na, nb = self.station_node.get(a), self.station_node.get(b)
            leg = self._astar(na, nb) if na is not None and nb is not None else None
            if leg is None:
                missing.append((a, b))
                continue
            for ei, forward in leg:
                e = self.edges[ei]
                c = e.coords if forward else e.coords[::-1]
                pts = c.tolist()
                if coords and coords[-1] == pts[0]:
                    pts = pts[1:]
                coords.extend(pts)
                edges.append(ei)
                per_line[e.line_id] += e.length_km
                total += e.length_km
        if not edges:
            return None
        lines = []
        for lid, km in sorted(per_line.items(), key=lambda kv: -kv[1]):
            info = dict(self.line_names.get(lid, {"id": lid}))
            info["km"] = round(km, 1)
            lines.append(info)
        return PathResult(station_ids=ids, edges=edges, length_km=total, coords=coords, lines=lines, missing_legs=missing)

    def edge_feature(self, ei: int) -> dict:
        e = self.edges[ei]
        info = self.line_names.get(e.line_id, {})
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": e.coords.tolist()},
                "properties": {"edge": ei, "line_id": e.line_id, "line_code": info.get("code"), "line_name": info.get("name"),
                               "length_km": round(e.length_km, 2)}}


# --------------------------------------------------------------------- cache
_lock = threading.Lock()
_cached: RailGraph | None = None
_cached_path: str | None = None


def get_graph(store: ReferenceStore, cache_file: Path | None = None) -> RailGraph:
    """Graphe courant (construit a la demande, mis en cache memoire + disque, invalide par version)."""
    global _cached, _cached_path
    version = store.version()
    with _lock:
        if _cached is not None and _cached.version == version and _cached_path == str(store.path):
            return _cached
        if cache_file and cache_file.exists():
            try:
                with cache_file.open("rb") as fh:
                    fmt, g = pickle.load(fh)  # fichier genere localement par l'application elle-meme
                if fmt == GRAPH_FORMAT and isinstance(g, RailGraph) and g.version == version:
                    _cached, _cached_path = g, str(store.path)
                    return g
            except Exception:  # cache corrompu ou obsolete : on reconstruit
                log.warning("cache du graphe illisible, reconstruction")
        g = RailGraph.build(store)
        if cache_file:
            try:
                tmp = cache_file.with_suffix(".tmp")
                with tmp.open("wb") as fh:
                    pickle.dump((GRAPH_FORMAT, g), fh, protocol=pickle.HIGHEST_PROTOCOL)
                tmp.replace(cache_file)
            except OSError:
                pass
        _cached, _cached_path = g, str(store.path)
        return g


def reset_cache() -> None:
    global _cached
    with _lock:
        _cached = None


def build_route_geometries(store: ReferenceStore, graph: RailGraph, only_missing: bool = True) -> int:
    """Reconstruit la geometrie des itineraires commerciaux sans trace (GTFS) le long du reseau physique."""
    conn = store.connect()
    updated = 0
    try:
        rows = conn.execute("SELECT rid, id FROM routes" + (" WHERE geom IS NULL" if only_missing else "")).fetchall()
        for rid, route_id in rows:
            stops = [r[0] for r in conn.execute("SELECT station_id FROM route_stops WHERE route_id=? ORDER BY seq", (route_id,))]
            res = graph.path(stops)
            if res is None or len(res.coords) < 2:
                continue
            ml = shapely.MultiLineString([res.coords])
            minx, miny, maxx, maxy = ml.bounds
            conn.execute("UPDATE routes SET geom=? WHERE rid=?", (wkb.dumps(ml), rid))
            conn.execute("INSERT OR REPLACE INTO routes_rtree(rid, minx, maxx, miny, maxy) VALUES(?,?,?,?,?)",
                         (rid, minx, maxx, miny, maxy))
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated
