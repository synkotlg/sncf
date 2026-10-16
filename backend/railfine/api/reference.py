"""Référentiel ferroviaire : état des sources, recherche de gares, fiches, trajets, tuiles vectorielles."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from shapely import wkb
from shapely.geometry import mapping

from ..categories import options
from ..db import connect
from ..reference import graph as graph_mod
from ..reference import matching
from ..reference.sources import describe_sources
from ..reference.update import GROUPS, import_gtfs_file, run_update
from . import rf

router = APIRouter(tags=["référentiel"])


@router.get("/options")
def get_options():
    return options()


@router.get("/reference/status")
def reference_status(state=Depends(rf)):
    store = state.reference
    return {
        "version": store.version(),
        "counts": store.counts(),
        "runs": store.source_runs(),
        "sources": describe_sources(),
        "update": {k: v for k, v in state.update_job.items() if k != "thread"},
        "groups": list(GROUPS),
    }


def _require_reference(state):
    if not state.reference.exists():
        raise HTTPException(404, "Référentiel non importé : lancez la mise à jour des données (Paramètres ou `railfine data update`).")


@router.get("/reference/stations/search")
def search_stations(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(10, ge=1, le=30),
                    include_points: bool = False, state=Depends(rf)):
    _require_reference(state)
    idx = matching.get_index(state.reference)
    return {"results": idx.search(q, limit=limit, include_points=include_points)}


@router.get("/reference/stations/match")
def match_station(q: str = Query(..., min_length=1, max_length=120), country: str | None = None, state=Depends(rf)):
    _require_reference(state)
    idx = matching.get_index(state.reference)
    return idx.match(q, threshold=float(state.cfg.settings.station_match_threshold), country_hint=country).to_dict()


@router.get("/reference/stations/{station_id}")
def station_detail(station_id: str, state=Depends(rf)):
    _require_reference(state)
    conn = connect(state.reference.path, readonly=True)
    try:
        r = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
        if not r:
            raise HTTPException(404, "gare inconnue")
        d = dict(r)
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else {}
        d["names"] = [dict(x) for x in conn.execute("SELECT name, lang, source FROM station_names WHERE station_id=?", (station_id,))]
        d["routes"] = [dict(x) for x in conn.execute(
            """SELECT DISTINCT r.id, r.short_name, r.long_name, r.category, r.operator FROM route_stops s
               JOIN routes r ON r.id=s.route_id WHERE s.station_id=? LIMIT 50""", (station_id,))]
        g = graph_mod.get_graph(state.reference, state.cfg.paths.graph_cache)
        d["on_network"] = station_id in g.station_node
        d["snap_km"] = g.station_snap_km.get(station_id)
        return d
    finally:
        conn.close()


@router.get("/reference/lines/{line_id}")
def line_detail(line_id: str, geometry: bool = False, state=Depends(rf)):
    _require_reference(state)
    conn = connect(state.reference.path, readonly=True)
    try:
        r = conn.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
        if not r:
            raise HTTPException(404, "ligne inconnue")
        d = {k: r[k] for k in r.keys() if k != "geom"}
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else {}
        if geometry:
            d["geometry"] = mapping(wkb.loads(r["geom"]).simplify(0.0005))
        return d
    finally:
        conn.close()


@router.get("/reference/routes")
def list_routes(category: str | None = None, q: str | None = None, limit: int = Query(50, le=500), state=Depends(rf)):
    _require_reference(state)
    conn = connect(state.reference.path, readonly=True)
    try:
        sql = "SELECT id, short_name, long_name, category, operator, country, source, geom IS NOT NULL AS has_geom FROM routes WHERE 1=1"
        params: list = []
        if category:
            sql += " AND category=?"
            params.append(category)
        if q:
            sql += " AND (short_name LIKE ? OR long_name LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY category, short_name LIMIT ?"
        params.append(limit)
        return {"results": [dict(r) for r in conn.execute(sql, params)]}
    finally:
        conn.close()


@router.get("/reference/routes/{route_id}")
def route_detail(route_id: str, state=Depends(rf)):
    _require_reference(state)
    conn = connect(state.reference.path, readonly=True)
    try:
        r = conn.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
        if not r:
            raise HTTPException(404, "itinéraire inconnu")
        d = {k: r[k] for k in r.keys() if k != "geom"}
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else {}
        d["stops"] = [dict(x) for x in conn.execute(
            """SELECT s.seq, st.id, st.name FROM route_stops s JOIN stations st ON st.id=s.station_id
               WHERE s.route_id=? ORDER BY s.seq""", (route_id,))]
        d["trains"] = [x[0] for x in conn.execute("SELECT DISTINCT train_number FROM trains WHERE route_id=? LIMIT 200", (route_id,))]
        return d
    finally:
        conn.close()


@router.get("/reference/trains/{number}")
def train_detail(number: str, state=Depends(rf)):
    _require_reference(state)
    conn = connect(state.reference.path, readonly=True)
    try:
        rows = conn.execute("SELECT train_number, route_id, category, operator, pattern, first_date, last_date, source FROM trains WHERE train_number=?",
                            (number.lstrip("0") or number,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["pattern"] = json.loads(d["pattern"])
            out.append(d)
        return {"results": out}
    finally:
        conn.close()


@router.get("/reference/path")
def path_between(from_id: str = Query(..., alias="from"), to_id: str = Query(..., alias="to"), via: str | None = None,
                 state=Depends(rf)):
    """Plus court chemin sur l'infrastructure : une hypothèse de parcours, pas un horaire."""
    _require_reference(state)
    g = graph_mod.get_graph(state.reference, state.cfg.paths.graph_cache)
    ids = [from_id, *[v for v in (via or "").split(",") if v], to_id]
    missing = [s for s in ids if s not in g.station_node]
    if missing:
        raise HTTPException(422, f"gare(s) non rattachée(s) au réseau physique importé : {', '.join(missing)}")
    res = g.path(ids)
    if res is None:
        raise HTTPException(404, "aucun chemin trouvé sur le réseau importé (réseau discontinu ou incomplet)")
    feat = res.to_geojson()
    feat["properties"]["missing_legs"] = res.missing_legs
    feat["properties"]["disclaimer"] = ("Itinéraire calculé sur l'infrastructure (plus court chemin) : il ne correspond pas "
                                        "nécessairement au parcours d'un train commercial.")
    return feat


@router.get("/reference/basemap")
def basemap(state=Depends(rf)):
    if not state.reference.exists():
        return {"type": "FeatureCollection", "features": []}
    conn = connect(state.reference.path, readonly=True)
    try:
        feats = [json.loads(r[0]) for r in conn.execute("SELECT geojson FROM basemap")]
    finally:
        conn.close()
    return Response(json.dumps({"type": "FeatureCollection", "features": feats}), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/tiles/{layer}/{z}/{x}/{y}.pbf")
def tile(layer: str, z: int, x: int, y: int, state=Depends(rf)):
    try:
        data = state.tiles.render(state.reference.version(), layer, z, x, y)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return Response(data, media_type="application/x-protobuf", headers={"Cache-Control": "public, max-age=3600"})


@router.post("/reference/update")
def start_update(body: dict | None = None, state=Depends(rf)):
    job = state.update_job
    if job.get("running"):
        raise HTTPException(409, "une mise à jour est déjà en cours")
    groups = [g for g in (body or {}).get("groups", ["base", "sncf", "infrabel", "gtfs"]) if g in GROUPS]
    job.update({"running": True, "log": [], "report": None, "groups": groups})

    def work():
        try:
            report = run_update(state.cfg, groups, progress=lambda m: job["log"].append(m))
            job["report"] = report
            state.tiles.clear()
            job["log"].append("Recalcul de la géolocalisation des amendes ...")
            n = state.fines.relocate_all()
            job["log"].append(f"{n} amende(s) recalculée(s).")
        except Exception as exc:  # signalé dans le journal de la tâche
            job["log"].append(f"Erreur : {exc}")
        finally:
            job["running"] = False

    threading.Thread(target=work, name="railfine-update", daemon=True).start()
    return {"started": True, "groups": groups}


@router.post("/reference/gtfs")
async def upload_gtfs(source: str = Query(..., pattern="^(sncf_gtfs|sncb_gtfs)$"), file: UploadFile = File(...), state=Depends(rf)):
    """Import manuel d'un fichier GTFS (ZIP) téléchargé par l'utilisateur sur le portail officiel."""
    if state.update_job.get("running"):
        raise HTTPException(409, "une mise à jour est déjà en cours")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=state.cfg.paths.raw_dir) as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > 1_500_000_000:
                raise HTTPException(413, "fichier trop volumineux")
            tmp.write(chunk)
        path = Path(tmp.name)
    try:
        result = import_gtfs_file(state.cfg, source, path)
    except Exception as exc:
        raise HTTPException(422, f"GTFS illisible : {exc}")
    finally:
        path.unlink(missing_ok=True)
    state.tiles.clear()
    state.fines.relocate_all()
    return result
