"""Statistiques, couches cartographiques des amendes et exports CSV / JSON."""

from __future__ import annotations

import csv
import io
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ..analytics import mapdata
from ..analytics.stats import Filters, RefNames, apply_filters, build_frame, compute, frame_to_records
from ..db import connect
from ..reference import graph as graph_mod
from ..reference import matching
from . import rf

router = APIRouter(tags=["statistiques"])

_names_cache: dict = {}


def ref_names(state) -> RefNames:
    version = (str(state.reference.path), state.reference.version())
    if _names_cache.get("version") == version:
        return _names_cache["names"]
    names = RefNames()
    if state.reference.exists():
        idx = matching.get_index(state.reference)
        names.stations = {sid: s["name"] for sid, s in idx.stations.items()}
        conn = connect(state.reference.path, readonly=True)
        try:
            names.lines = {r["id"]: {"name": r["name"], "code": r["code"], "infra_type": r["infra_type"]}
                           for r in conn.execute("SELECT id, name, code, infra_type FROM lines")}
            names.routes = {r["id"]: dict(r) for r in conn.execute("SELECT id, short_name, long_name, category FROM routes")}
        finally:
            conn.close()
    _names_cache.update({"version": version, "names": names})
    return names


def _frame(state, request: Request):
    filters = Filters.from_query(dict(request.query_params))
    fines = state.fines.store.list_fines(include_demo=filters.include_demo)
    df = build_frame(fines, ref_names(state))
    return filters, df, apply_filters(df, filters)


@router.get("/stats")
def stats(request: Request, state=Depends(rf)):
    filters, full, df = _frame(state, request)
    res = compute(df, ref_names(state))
    res["filters"] = filters.__dict__
    res["total_unfiltered"] = int(len(full))
    # valeurs disponibles pour les listes de filtres
    if not full.empty:
        res["facets"] = {
            "carriers": sorted(full["carrier"].dropna().unique().tolist()),
            "train_types": sorted(full["train_type"].dropna().unique().tolist()),
            "reasons": sorted(full["reason"].dropna().unique().tolist()),
            "countries": sorted(full["country"].dropna().unique().tolist()),
            "years": sorted(int(y) for y in full["year"].dropna().unique().tolist()),
        }
    return res


@router.get("/map/fines")
def map_fines(request: Request, state=Depends(rf)):
    filters, _full, df = _frame(state, request)
    graph = graph_mod.get_graph(state.reference, state.cfg.paths.graph_cache) if state.reference.exists() else None
    paths = state.fines.store.paths()
    stale = [fid for fid, p in paths.items() if graph is not None and p["graph_version"] != graph.version]
    if stale:  # référentiel mis à jour depuis le calcul des trajets
        ctx = state.fines.geo_context()
        for fid in stale:
            state.fines.relocate(fid, ctx)
        paths = state.fines.store.paths()
        filters, _full, df = _frame(state, request)
    stations = matching.get_index(state.reference).stations if state.reference.exists() else {}
    layers = mapdata.build_layers(df, paths, graph, stations)
    layers["count"] = int(len(df))
    return layers


def _csv(rows: list[dict], columns: list[str] | None = None) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    cols = columns or list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=";")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return "﻿" + buf.getvalue()  # BOM : ouverture correcte des accents dans Excel


def _download(content: str | bytes, filename: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/fines.{fmt}")
def export_fines(fmt: str, request: Request, state=Depends(rf)):
    _filters, _full, df = _frame(state, request)
    records = frame_to_records(df)
    stamp = time.strftime("%Y%m%d")
    if fmt == "json":
        return _download(json.dumps({"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "fines": records}, ensure_ascii=False,
                                    indent=1, default=str), f"amendes-{stamp}.json", "application/json")
    if fmt == "csv":
        return _download(_csv(records), f"amendes-{stamp}.csv", "text/csv; charset=utf-8")
    return Response(status_code=404)


@router.get("/export/stats.{fmt}")
def export_stats(fmt: str, request: Request, state=Depends(rf)):
    filters, _full, df = _frame(state, request)
    res = compute(df, ref_names(state))
    stamp = time.strftime("%Y%m%d")
    if fmt == "json":
        res["filters"] = filters.__dict__
        return _download(json.dumps(res, ensure_ascii=False, indent=1, default=str), f"statistiques-{stamp}.json", "application/json")
    if fmt == "csv":
        rows = []
        labels = {"count": "Nombre d'amendes", "total": "Montant total des amendes", "paid": "Montant total payé",
                  "mean": "Montant moyen", "median": "Montant médian", "min": "Montant minimum", "max": "Montant maximum",
                  "with_amount": "Amendes avec montant", "with_paid_amount": "Amendes avec montant payé",
                  "first_date": "Première date", "last_date": "Dernière date", "geolocated": "Amendes géolocalisées",
                  "not_geolocated": "Amendes non géolocalisées", "demo": "Amendes d'exemple (fictives)"}
        for name, value in res.get("summary", {}).items():
            if not isinstance(value, (dict, list)):
                rows.append({"section": "synthese", "classement": "", "cle": name, "libelle": labels.get(name, name), "nombre": "", "montant_total": "",
                             "montant_moyen": "", "montant_median": "", "valeur": value})
        for section, rk in res.get("rankings", {}).items():
            for order in ("by_count", "by_total"):
                for i, item in enumerate(rk.get(order, []), start=1):
                    rows.append({"section": section, "classement": f"{order}#{i}", "cle": item["key"], "libelle": item["label"],
                                 "nombre": item["count"], "montant_total": item["total"], "montant_moyen": item["mean"],
                                 "montant_median": item["median"], "valeur": ""})
        for item in res.get("time", {}).get("hours", []):
            rows.append({"section": "heures", "classement": "", "cle": item["hour"], "libelle": f"{item['hour']:02d}h",
                         "nombre": item["count"], "montant_total": item["total"], "montant_moyen": item["mean"],
                         "montant_median": item["median"], "valeur": ""})
        for item in res.get("time", {}).get("weekdays", []):
            rows.append({"section": "jours", "classement": "", "cle": item["weekday"], "libelle": item["label"], "nombre": item["count"],
                         "montant_total": item["total"], "montant_moyen": item["mean"], "montant_median": item["median"], "valeur": ""})
        for item in res.get("time", {}).get("months", []):
            rows.append({"section": "mois", "classement": "", "cle": item["month"], "libelle": item["month"], "nombre": item["count"],
                         "montant_total": item["total"], "montant_moyen": item["mean"], "montant_median": item["median"], "valeur": ""})
        cols = ["section", "classement", "cle", "libelle", "nombre", "montant_total", "montant_moyen", "montant_median", "valeur"]
        return _download(_csv(rows, cols), f"statistiques-{stamp}.csv", "text/csv; charset=utf-8")
    return Response(status_code=404)
