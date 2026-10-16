"""Tuiles vectorielles (Mapbox Vector Tiles) generees a la volee depuis la base de reference.

Le navigateur ne charge que les tuiles visibles, simplifiees selon le niveau de
zoom : un zoom arriere sur toute la France reste leger.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from pathlib import Path

import mapbox_vector_tile
import numpy as np
import shapely
from shapely import wkb
from shapely.geometry import Point

from ..db import connect

EXTENT = 4096
BUFFER = 64
LAYERS = ("lines", "stations", "routes")


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2.0**z

    def lon(xx):
        return xx / n * 360.0 - 180.0

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


def _projector(z: int, x: int, y: int):
    n = 2.0**z

    def fn(coords: np.ndarray) -> np.ndarray:
        lon = coords[:, 0]
        lat = np.clip(coords[:, 1], -85.0511, 85.0511)
        mx = (lon + 180.0) / 360.0
        my = 0.5 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / (2 * np.pi)
        px = (mx * n - x) * EXTENT
        py = (my * n - y) * EXTENT
        return np.column_stack([px, py])

    return fn


def station_min_importance(z: int) -> int:
    return 2 if z < 9 else 3


class TileRenderer:
    def __init__(self, db_path: Path, max_items: int = 3000):
        self.db_path = db_path
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self.max_items = max_items

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def render(self, version: str, layer: str, z: int, x: int, y: int) -> bytes:
        if layer not in LAYERS:
            raise ValueError("couche inconnue")
        if not (0 <= z <= 22 and 0 <= x < 2**z and 0 <= y < 2**z):
            raise ValueError("tuile hors limites")
        key = (version, layer, z, x, y)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        data = self._render(layer, z, x, y)
        with self._lock:
            self._cache[key] = data
            if len(self._cache) > self.max_items:
                self._cache.popitem(last=False)
        return data

    def _render(self, layer: str, z: int, x: int, y: int) -> bytes:
        if not self.db_path.exists():
            return mapbox_vector_tile.encode([])
        minx, miny, maxx, maxy = tile_bounds(z, x, y)
        bx = (maxx - minx) * BUFFER / EXTENT
        by = (maxy - miny) * BUFFER / EXTENT
        q = (minx - bx, maxx + bx, miny - by, maxy + by)
        proj = _projector(z, x, y)
        clip = (-BUFFER, -BUFFER, EXTENT + BUFFER, EXTENT + BUFFER)
        tol = 1.0 if z >= 10 else 2.0
        features = []
        conn = connect(self.db_path, readonly=True)
        try:
            if layer == "lines":
                rows = conn.execute(
                    """SELECT l.id, l.code, l.name, l.country, l.infra_type, l.status, l.source, l.length_km, l.electrified, l.geom
                       FROM lines_rtree r JOIN lines l ON l.rid=r.rid
                       WHERE l.active=1 AND r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?""",
                    (q[0], q[2], q[1], q[3]),
                ).fetchall()
                for row in rows:
                    if z < 7 and row["infra_type"] == "raccordement":
                        continue
                    geom = self._prepare(wkb.loads(row["geom"]), proj, clip, tol)
                    if geom is None:
                        continue
                    features.append({"geometry": geom, "properties": {
                        "id": row["id"], "code": row["code"] or "", "name": row["name"] or "", "country": row["country"] or "",
                        "infra_type": row["infra_type"], "status": row["status"] or "", "source": row["source"],
                        "length_km": row["length_km"] or 0, "electrified": row["electrified"] or "",
                    }})
            elif layer == "routes":
                rows = conn.execute(
                    """SELECT ro.id, ro.short_name, ro.long_name, ro.category, ro.operator, ro.country, ro.source, ro.geom
                       FROM routes_rtree r JOIN routes ro ON ro.rid=r.rid
                       WHERE ro.geom IS NOT NULL AND r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=?""",
                    (q[0], q[2], q[1], q[3]),
                ).fetchall()
                for row in rows:
                    geom = self._prepare(wkb.loads(row["geom"]), proj, clip, tol)
                    if geom is None:
                        continue
                    features.append({"geometry": geom, "properties": {
                        "id": row["id"], "short_name": row["short_name"] or "", "long_name": row["long_name"] or "",
                        "category": row["category"], "operator": row["operator"] or "", "country": row["country"] or "",
                        "source": row["source"],
                    }})
            else:
                kinds = ("station", "operational_point") if z >= 11 else ("station",)
                rows = conn.execute(
                    f"""SELECT s.id, s.name, s.uic, s.country, s.importance, s.kind, s.lon, s.lat
                       FROM stations_rtree r JOIN stations s ON s.rid=r.rid
                       WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=? AND s.importance<=?
                       AND s.kind IN ({",".join("?" * len(kinds))})
                       ORDER BY s.importance""",
                    (q[0], q[2], q[1], q[3], station_min_importance(z), *kinds),
                ).fetchall()
                for row in rows:
                    px, py = proj(np.array([[row["lon"], row["lat"]]]))[0]
                    features.append({"geometry": Point(px, py), "properties": {
                        "id": row["id"], "name": row["name"], "uic": row["uic"] or "", "country": row["country"] or "",
                        "importance": row["importance"], "kind": row["kind"],
                    }})
        finally:
            conn.close()
        if not features:
            return mapbox_vector_tile.encode([])
        return mapbox_vector_tile.encode(
            [{"name": layer, "features": features}],
            default_options={"y_coord_down": True, "extents": EXTENT},
        )

    @staticmethod
    def _prepare(geom, proj, clip, tol):
        g = shapely.transform(geom, proj)
        g = shapely.clip_by_rect(g, *clip)
        if g.is_empty:
            return None
        g = g.simplify(tol, preserve_topology=False)
        if g.is_empty or g.length < 1:
            return None
        return g
