"""Rattachement d'une amende au référentiel : gares, circulation, itinéraire commercial, lignes physiques.

Ordre de fiabilité :
1. numéro de train trouvé dans les horaires GTFS à la date de l'amende et desservant les gares
   -> trajet suivant les arrêts du train (``train_confirmed``) ;
2. gares de départ et d'arrivée identifiées -> plus court chemin sur le réseau physique,
   explicitement présenté comme une HYPOTHÈSE (``path_inferred``) ;
3. gares identifiées sans tracé possible (``od_only``), une seule gare (``station_only``) ;
4. sinon : amende NON géolocalisée, conservée dans les statistiques générales.

Aucune ligne n'est attribuée au hasard : en cas d'ambiguïté, les candidats sont
renvoyés pour une validation manuelle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..config import AppConfig
from ..db import connect
from ..reference import graph as graph_mod
from ..reference import matching
from ..reference.store import ReferenceStore


@dataclass
class GeoContext:
    store: ReferenceStore
    index: matching.StationIndex
    graph: graph_mod.RailGraph | None
    threshold: float
    infer_paths: bool

    @classmethod
    def load(cls, cfg: AppConfig) -> "GeoContext":
        store = ReferenceStore(cfg.paths.reference_db)
        s = cfg.settings
        graph = graph_mod.get_graph(store, cfg.paths.graph_cache) if store.exists() else None
        return cls(store, matching.get_index(store), graph, float(s.station_match_threshold), s.infer_paths)

    def station(self, sid: str | None) -> dict | None:
        return self.index.stations.get(sid) if sid else None


def _yyyymmdd(iso: str | None) -> str | None:
    return iso.replace("-", "") if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else None


def _resolve_station(ctx: GeoContext, manual_id: str | None, name: str | None, country: str | None,
                     near: tuple[float, float] | None) -> dict:
    if manual_id and ctx.station(manual_id):
        st = ctx.station(manual_id)
        return {"id": manual_id, "name": st["name"], "confidence": 1.0, "method": "manuel", "candidates": []}
    if not name:
        return {"id": None, "name": None, "confidence": 0.0, "method": None, "candidates": []}
    m = ctx.index.match(name, threshold=ctx.threshold, country_hint=country, near=near)
    return {"id": m.station_id, "name": m.name, "confidence": round(m.confidence, 2), "method": "auto", "reason": m.reason,
            "ambiguous": m.ambiguous, "candidates": [c.to_dict() for c in m.candidates[:6]]}


def _train_candidates(ctx: GeoContext, number: str) -> list[dict]:
    if not number or not ctx.store.exists():
        return []
    conn = connect(ctx.store.path, readonly=True)
    try:
        rows = conn.execute(
            """SELECT t.train_number, t.route_id, t.category, t.operator, t.pattern, t.dates, t.first_date, t.last_date,
                      r.short_name, r.long_name
               FROM trains t LEFT JOIN routes r ON r.id=t.route_id WHERE t.train_number=?""",
            (str(number).lstrip("0") or str(number),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _routes_for(ctx: GeoContext, line_label: str | None, origin: str | None, dest: str | None, country: str | None) -> list[dict]:
    if not ctx.store.exists():
        return []
    conn = connect(ctx.store.path, readonly=True)
    try:
        out = []
        if line_label:
            m = re.match(r"(?:rer|ligne)\s+(.+)$", line_label.strip(), re.I)
            short = (m.group(1) if m else line_label).strip().upper()
            rows = conn.execute("SELECT id, short_name, long_name, category, country FROM routes WHERE UPPER(short_name)=?", (short,)).fetchall()
            for r in rows:
                if country and r["country"] and r["country"] != country:
                    continue
                if line_label.upper().startswith("RER") and r["category"] != "RER":
                    continue
                out.append({**dict(r), "method": "libellé de ligne"})
            if out:
                return out
        if origin and dest:
            rows = conn.execute(
                """SELECT r.id, r.short_name, r.long_name, r.category, r.country FROM routes r
                   WHERE r.id IN (SELECT a.route_id FROM route_stops a JOIN route_stops b ON a.route_id=b.route_id
                                  WHERE a.station_id=? AND b.station_id=?)""",
                (origin, dest),
            ).fetchall()
            out = [{**dict(r), "method": "gares desservies"} for r in rows]
        return out
    finally:
        conn.close()


def geolocate(fine: dict, ctx: GeoContext) -> tuple[dict, list[dict], dict | None]:
    detail: dict = {"messages": []}
    msgs = detail["messages"]
    if fine.get("geo_disabled"):
        return ({"status": "none", "confidence": None, "detail": {"messages": ["géolocalisation désactivée par l'utilisateur"]}},
                [], None)
    country = fine.get("country")
    # 1. gares
    o = _resolve_station(ctx, fine.get("origin_station_id"), fine.get("origin_name"), country, None)
    near_o = (ctx.station(o["id"])["lat"], ctx.station(o["id"])["lon"]) if o["id"] else None
    d = _resolve_station(ctx, fine.get("dest_station_id"), fine.get("dest_name"), country, near_o)
    if o["id"] is None and d["id"] and fine.get("origin_name"):
        near_d = (ctx.station(d["id"])["lat"], ctx.station(d["id"])["lon"])
        o = _resolve_station(ctx, None, fine.get("origin_name"), country, near_d)
    c = _resolve_station(ctx, fine.get("control_station_id"), fine.get("control_station_name"), country, near_o)
    via = [v for v in (fine.get("via_station_ids") or []) if ctx.station(v)]

    # 2. circulation (numéro de train)
    train_used = None
    pattern_ids: list[str] = []
    cands = _train_candidates(ctx, fine.get("train_number")) if fine.get("train_number") else []
    if fine.get("train_number") and not cands:
        msgs.append("numéro de train absent des horaires importés (GTFS non importé ou hors période couverte)")
    if cands:
        day = _yyyymmdd(fine.get("fine_date"))
        scored = []
        for t in cands:
            pattern = json.loads(t["pattern"])
            sids = [p[0] for p in pattern if p[0]]
            # désambiguïsation des gares grâce aux arrêts du train
            oo, dd = o, d
            for res in (oo, dd):
                if res["id"] is None and res["candidates"]:
                    hit = [cand for cand in res["candidates"] if cand["id"] in sids]
                    if len(hit) == 1:
                        res.update({"id": hit[0]["id"], "name": hit[0]["name"], "confidence": 0.8,
                                    "reason": "désambiguïsé par les arrêts du train"})
            date_ok = bool(day and t["dates"] and day in t["dates"].split(","))
            o_in = o["id"] in sids if o["id"] else None
            d_in = d["id"] in sids if d["id"] else None
            order_ok = (o_in and d_in and sids.index(o["id"]) < sids.index(d["id"])) if (o_in and d_in) else None
            score = (2 if date_ok else 0) + (2 if order_ok else 0) + (1 if (o_in or d_in) else 0) - (3 if (o_in is False or d_in is False) else 0)
            scored.append((score, date_ok, o_in, d_in, order_ok, t, sids))
        scored.sort(key=lambda x: -x[0])
        best = scored[0]
        score, date_ok, o_in, d_in, order_ok, t, sids = best
        tie = len(scored) > 1 and scored[1][0] == score and scored[1][5]["route_id"] != t["route_id"]
        if o_in is False or d_in is False:
            msgs.append(f"le train {t['train_number']} (horaires importés) ne dessert pas les gares indiquées : non utilisé")
        elif tie:
            msgs.append(f"plusieurs circulations n° {t['train_number']} possibles : choix manuel requis")
        else:
            train_used = {"train_number": t["train_number"], "route_id": t["route_id"], "category": t["category"],
                          "operator": t["operator"], "date_ok": date_ok, "route_label": t["short_name"] or t["long_name"]}
            if order_ok:
                pattern_ids = sids[sids.index(o["id"]): sids.index(d["id"]) + 1]
            elif o_in and not d["id"]:
                pattern_ids = sids[sids.index(o["id"]):]
            elif d_in and not o["id"]:
                pattern_ids = sids[: sids.index(d["id"]) + 1]
            else:
                pattern_ids = sids
            if not date_ok:
                msgs.append("circulation trouvée mais pas à la date de l'amende (horaires d'une autre période) : à vérifier")

    # 3. itinéraire commercial
    route_id = train_used["route_id"] if train_used else None
    route_label = train_used.get("route_label") if train_used else None
    if not route_id:
        rc = _routes_for(ctx, fine.get("line_label"), o["id"], d["id"], country)
        if len(rc) == 1:
            route_id, route_label = rc[0]["id"], rc[0]["short_name"] or rc[0]["long_name"]
            detail["route_method"] = rc[0]["method"]
        elif len(rc) > 1:
            detail["route_candidates"] = rc[:8]
            msgs.append(f"{len(rc)} itinéraires commerciaux possibles : non attribué automatiquement")

    # 4. tracé sur le réseau physique
    path = None
    method = None
    g = ctx.graph
    if g is not None and g.edges:
        if pattern_ids and len(pattern_ids) >= 2:
            path = g.path(pattern_ids)
            method = "train"
        elif o["id"] and d["id"] and (ctx.infer_paths or via):
            path = g.path([o["id"], *via, d["id"]])
            method = "via" if via else "plus_court_chemin"
        if path is not None and path.missing_legs:
            msgs.append(f"{len(path.missing_legs)} tronçon(s) sans tracé possible sur le réseau importé")
    elif o["id"] and d["id"]:
        msgs.append("aucun réseau physique importé : tracé impossible")

    # 5. statut et confiance
    st_conf = [x["confidence"] for x in (o, d) if x["id"]]
    base_conf = min(st_conf) if st_conf else 0.0
    if train_used and pattern_ids and (o["id"] or d["id"]):
        status = "train_confirmed"
        conf = base_conf * (0.95 if train_used["date_ok"] else 0.75)
    elif train_used and pattern_ids:
        status = "train_route"
        conf = 0.6 if train_used["date_ok"] else 0.45
    elif path is not None and method == "via":
        status = "manual"
        conf = base_conf
    elif path is not None:
        status = "path_inferred"
        conf = base_conf * 0.7
    elif o["id"] and d["id"]:
        status = "od_only"
        conf = base_conf
    elif o["id"] or d["id"] or c["id"]:
        status = "station_only"
        conf = max(o["confidence"], d["confidence"], c["confidence"])
    else:
        status = "none"
        conf = None
    if fine.get("geo_validated") and status != "none":
        conf = 1.0
    links: list[dict] = []
    if path is not None:
        for ln in path.lines:
            links.append({"kind": "line", "ref_id": ln["id"], "label": ln.get("name") or ln.get("code") or ln["id"], "km": ln["km"],
                          "confidence": conf, "method": method})
    if route_id:
        links.append({"kind": "route", "ref_id": route_id, "label": route_label, "confidence": conf,
                      "method": "train" if train_used else detail.get("route_method")})
    if train_used:
        links.append({"kind": "train", "ref_id": train_used["train_number"], "label": f"{train_used['category']} {train_used['train_number']}",
                      "confidence": conf, "method": "gtfs"})

    countries = {ctx.station(x)["country"] for x in (o["id"], d["id"]) if x and ctx.station(x)}
    detail.update({"origin": o, "dest": d, "control": c, "via": via, "train": train_used, "path_method": method,
                   "path_km": round(path.length_km, 1) if path else None})
    geo = {
        "status": status,
        "confidence": round(conf, 2) if conf is not None else None,
        "detail": detail,
        "route_id": route_id,
        "country": next(iter(countries)) if len(countries) == 1 else None,
        "origin_resolved_id": o["id"],
        "dest_resolved_id": d["id"],
        "control_resolved_id": c["id"],
    }
    path_row = None
    if path is not None:
        path_row = {"graph_version": g.version, "edges": path.edges, "length_km": round(path.length_km, 2), "method": method}
    return geo, links, path_row


def train_type_hint(geo: dict) -> str | None:
    train = (geo.get("detail") or {}).get("train")
    return train.get("category") if train else None
