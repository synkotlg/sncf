"""Couches cartographiques des amendes : tronçons du réseau, gares, relations O-D non tracées, points d'amende.

Chaque tronçon (arête du graphe du réseau physique) porte : nombre d'amendes,
montant total, montant moyen, histogramme horaire, créneau dominant, mois,
catégories de trains et part des trajets confirmés / présumés.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from ..categories import time_slot
from ..reference.graph import RailGraph


def _round(v):
    return None if v is None or pd.isna(v) else round(float(v), 2)


def build_layers(df: pd.DataFrame, paths: dict[int, dict], graph: RailGraph | None, stations: dict[str, dict]) -> dict:
    empty = {"type": "FeatureCollection", "features": []}
    if df.empty:
        return {"segments": empty, "stations": empty, "od": empty, "fines": empty, "unlocated": 0, "max": {}}
    rows = {int(r["id"]): r for r in df.to_dict(orient="records")}
    seg: dict[int, dict] = defaultdict(lambda: {"ids": set(), "total": 0.0, "n_amount": 0, "hours": [0] * 24, "slots": Counter(),
                                                 "months": Counter(), "types": Counter(), "confirmed": 0, "presumed": 0})
    path_coords: dict[int, list] = {}
    for fid, r in rows.items():
        p = paths.get(fid)
        if not p or graph is None or p["graph_version"] != graph.version:
            continue
        coords = []
        for ei in p["edges"]:
            if ei >= len(graph.edges):
                continue
            s = seg[ei]
            if fid in s["ids"]:
                continue
            s["ids"].add(fid)
            if r["amount_initial"] is not None and not pd.isna(r["amount_initial"]):
                s["total"] += float(r["amount_initial"])
                s["n_amount"] += 1
            h = r["hour"]
            if h is not None and not pd.isna(h):
                s["hours"][int(h)] += 1
                s["slots"][time_slot(int(h))] += 1
            if r["month"]:
                s["months"][r["month"]] += 1
            s["types"][r["train_type"] or "INCONNU"] += 1
            if r["geo_status"] in ("train_confirmed", "manual") or r["geo_validated"]:
                s["confirmed"] += 1
            else:
                s["presumed"] += 1
            if not coords:
                coords = graph.edges[ei].coords.tolist()
        path_coords[fid] = coords
    seg_features = []
    for ei, s in seg.items():
        e = graph.edges[ei]
        info = graph.line_names.get(e.line_id, {})
        n = len(s["ids"])
        seg_features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": e.coords.round(5).tolist()},
                             "properties": {
                                 "edge": ei, "line_id": e.line_id, "line_name": info.get("name") or "", "line_code": info.get("code") or "",
                                 "count": n, "total": round(s["total"], 2), "mean": round(s["total"] / s["n_amount"], 2) if s["n_amount"] else None,
                                 "hours": s["hours"], "dominant_slot": s["slots"].most_common(1)[0][0] if s["slots"] else None,
                                 "months": dict(sorted(s["months"].items())), "types": dict(s["types"]),
                                 "confirmed": s["confirmed"], "presumed": s["presumed"], "fine_ids": sorted(s["ids"]),
                                 "length_km": round(e.length_km, 2),
                             }})
    # gares concernées
    st = defaultdict(lambda: {"ids": set(), "total": 0.0, "roles": Counter(), "hours": [0] * 24})
    for fid, r in rows.items():
        for col, role in (("origin_id", "départ"), ("dest_id", "arrivée"), ("control_id", "contrôle")):
            sid = r[col]
            if not sid or sid not in stations:
                continue
            s = st[sid]
            s["roles"][role] += 1
            if fid not in s["ids"]:
                s["ids"].add(fid)
                if r["amount_initial"] is not None and not pd.isna(r["amount_initial"]):
                    s["total"] += float(r["amount_initial"])
                if r["hour"] is not None and not pd.isna(r["hour"]):
                    s["hours"][int(r["hour"])] += 1
    st_features = []
    for sid, s in st.items():
        info = stations[sid]
        st_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [info["lon"], info["lat"]]},
                            "properties": {"station_id": sid, "name": info["name"], "count": len(s["ids"]), "total": round(s["total"], 2),
                                           "roles": dict(s["roles"]), "hours": s["hours"], "fine_ids": sorted(s["ids"])}})
    # relations O-D sans tracé ferroviaire (affichées en pointillé, jamais comme une voie)
    od = defaultdict(lambda: {"ids": [], "total": 0.0})
    for fid, r in rows.items():
        if fid in path_coords or not r["origin_id"] or not r["dest_id"]:
            continue
        if r["origin_id"] not in stations or r["dest_id"] not in stations:
            continue
        k = (r["origin_id"], r["dest_id"])
        od[k]["ids"].append(fid)
        if r["amount_initial"] is not None and not pd.isna(r["amount_initial"]):
            od[k]["total"] += float(r["amount_initial"])
    od_features = []
    for (a, b), v in od.items():
        sa, sb = stations[a], stations[b]
        od_features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[sa["lon"], sa["lat"]], [sb["lon"], sb["lat"]]]},
                            "properties": {"origin": sa["name"], "dest": sb["name"], "count": len(v["ids"]), "total": round(v["total"], 2),
                                           "fine_ids": v["ids"]}})
    # points d'amende (gare de contrôle > départ > arrivée > début du tracé)
    fine_features = []
    unlocated = 0
    for fid, r in rows.items():
        pt = None
        for col in ("control_id", "origin_id", "dest_id"):
            sid = r[col]
            if sid and sid in stations:
                pt = [stations[sid]["lon"], stations[sid]["lat"]]
                break
        if pt is None and path_coords.get(fid):
            pt = path_coords[fid][0]
        if pt is None:
            unlocated += 1
            continue
        fine_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": pt},
                              "properties": {"fine_id": fid, "date": r["date"].strftime("%Y-%m-%d") if not pd.isna(r["date"]) else None,
                                             "time": r["time"], "amount": _round(r["amount_initial"]), "train_type": r["train_type"],
                                             "geo_status": r["geo_status"], "is_demo": bool(r["is_demo"])}})
    maxima = {
        "count": max((f["properties"]["count"] for f in seg_features), default=0),
        "total": max((f["properties"]["total"] for f in seg_features), default=0),
        "mean": max((f["properties"]["mean"] or 0 for f in seg_features), default=0),
        "station_count": max((f["properties"]["count"] for f in st_features), default=0),
    }
    return {
        "segments": {"type": "FeatureCollection", "features": seg_features},
        "stations": {"type": "FeatureCollection", "features": st_features},
        "od": {"type": "FeatureCollection", "features": od_features},
        "fines": {"type": "FeatureCollection", "features": fine_features},
        "unlocated": unlocated,
        "max": maxima,
    }
