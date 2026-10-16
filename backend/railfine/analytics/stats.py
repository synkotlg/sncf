"""Statistiques descriptives des amendes importées.

Toujours distinguer : NOMBRE d'amendes, MONTANT TOTAL, MONTANT MOYEN (et médian).
Ces chiffres décrivent VOS amendes : sans le nombre total de trajets effectués,
ils ne mesurent pas un risque d'être verbalisé, et une concentration sur une
ligne ou un horaire peut simplement refléter vos habitudes de déplacement
(corrélation, pas causalité).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..categories import COUNTRIES, FINE_STATUSES, GEO_STATUSES, REASONS, TIME_SLOTS, TRAIN_TYPES, WEEKDAYS_FR, time_slot

MISSING = "(non renseigné)"

CAVEATS = [
    "Ces statistiques décrivent uniquement les amendes importées : elles ne mesurent pas un risque d'amende. "
    "Calculer un risque par ligne ou par horaire exigerait de connaître le nombre total de vos trajets.",
    "Une concentration d'amendes sur une ligne, une gare ou un horaire est une corrélation : elle peut refléter "
    "vos habitudes de déplacement plutôt qu'une intensité de contrôle.",
    "Une amende dont le trajet emprunte plusieurs lignes physiques est comptée pour chacune d'elles : "
    "les totaux par ligne ne s'additionnent pas.",
    "Les trajets « présumés » sont des plus courts chemins sur le réseau : ils peuvent différer du parcours réel.",
]


@dataclass
class Filters:
    date_from: str | None = None
    date_to: str | None = None
    country: str | None = None
    carrier: str | None = None
    line: str | None = None
    route: str | None = None
    station: str | None = None
    train_type: str | None = None
    train_number: str | None = None
    reason: str | None = None
    status: str | None = None
    geo_status: str | None = None
    hour_from: int | None = None
    hour_to: int | None = None
    include_demo: bool = True
    confirmed_only: bool = False

    @classmethod
    def from_query(cls, q: dict[str, Any]) -> "Filters":
        f = cls()
        for k in ("date_from", "date_to", "country", "carrier", "line", "route", "station", "train_type", "train_number",
                  "reason", "status", "geo_status"):
            v = q.get(k)
            if v not in (None, ""):
                setattr(f, k, str(v)[:120])
        for k in ("hour_from", "hour_to"):
            v = q.get(k)
            if v not in (None, ""):
                try:
                    setattr(f, k, max(0, min(23, int(v))))
                except (TypeError, ValueError):
                    pass
        for k in ("include_demo", "confirmed_only"):
            v = q.get(k)
            if v not in (None, ""):
                setattr(f, k, str(v).lower() in ("1", "true", "oui", "yes", "on"))
        return f


@dataclass
class RefNames:
    stations: dict[str, str] = field(default_factory=dict)
    lines: dict[str, dict] = field(default_factory=dict)
    routes: dict[str, dict] = field(default_factory=dict)


def build_frame(fines: list[dict], names: RefNames) -> pd.DataFrame:
    rows = []
    for f in fines:
        d = f.get("fine_date")
        t = f.get("fine_time")
        hour = int(t[:2]) if t and len(t) >= 2 and t[:2].isdigit() else None
        o_id, d_id = f.get("origin_resolved_id"), f.get("dest_resolved_id")
        o_label = names.stations.get(o_id) if o_id else None
        d_label = names.stations.get(d_id) if d_id else None
        lines = [l for l in f.get("links", []) if l["kind"] == "line"]
        route_links = [l for l in f.get("links", []) if l["kind"] == "route"]
        route_key = route_links[0]["ref_id"] if route_links else (f"label:{f['line_label']}" if f.get("line_label") else None)
        route_label = None
        if route_links:
            r = names.routes.get(route_links[0]["ref_id"], {})
            route_label = " ".join(x for x in (r.get("category"), r.get("short_name"), r.get("long_name")) if x) or route_links[0].get("label")
        elif f.get("line_label"):
            route_label = f"{f['line_label']} (libellé du document)"
        rows.append({
            "id": f["id"],
            "amount_initial": f.get("amount_initial"),
            "amount_paid": f.get("amount_paid"),
            "currency": f.get("currency") or "EUR",
            "date": pd.to_datetime(d, errors="coerce") if d else pd.NaT,
            "hour": hour,
            "time": t,
            "origin_id": o_id,
            "origin_label": o_label or (f"{f['origin_name']} (non apparié)" if f.get("origin_name") else None),
            "dest_id": d_id,
            "dest_label": d_label or (f"{f['dest_name']} (non apparié)" if f.get("dest_name") else None),
            "control_id": f.get("control_resolved_id"),
            "control_label": names.stations.get(f.get("control_resolved_id")) if f.get("control_resolved_id") else None,
            "train_number": f.get("train_number"),
            "train_type": f.get("train_type"),
            "carrier": f.get("carrier"),
            "country": f.get("country"),
            "reason": f.get("reason"),
            "status": f.get("status") or "inconnue",
            "geo_status": f.get("geo_status") or "none",
            "geo_validated": bool(f.get("geo_validated")),
            "route_key": route_key,
            "route_label": route_label,
            "line_ids": [l["ref_id"] for l in lines],
            "is_demo": bool(f.get("is_demo")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["amount_initial"] = pd.to_numeric(df["amount_initial"], errors="coerce")
    df["amount_paid"] = pd.to_numeric(df["amount_paid"], errors="coerce")
    df["hour"] = pd.to_numeric(df["hour"], errors="coerce").astype("Int64")
    df["weekday"] = df["date"].dt.weekday.astype("Int64")
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["year"] = df["date"].dt.year.astype("Int64")
    return df


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if not f.include_demo:
        m &= ~df["is_demo"]
    if f.date_from:
        m &= df["date"] >= pd.to_datetime(f.date_from, errors="coerce")
    if f.date_to:
        m &= df["date"] <= pd.to_datetime(f.date_to, errors="coerce")
    for col in ("country", "carrier", "train_type", "reason", "status", "geo_status", "train_number"):
        v = getattr(f, col)
        if v:
            m &= df[col].fillna("") == v
    if f.route:
        m &= df["route_key"].fillna("") == f.route
    if f.line:
        m &= df["line_ids"].apply(lambda ids: f.line in ids)
    if f.station:
        st = f.station
        m &= (df["origin_id"].fillna("") == st) | (df["dest_id"].fillna("") == st) | (df["control_id"].fillna("") == st)
    if f.hour_from is not None:
        m &= df["hour"].fillna(-1) >= f.hour_from
    if f.hour_to is not None:
        m &= df["hour"].fillna(99) <= f.hour_to
    if f.confirmed_only:
        m &= df["geo_status"].isin(["train_confirmed", "manual"]) | df["geo_validated"]
    return df[m]


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(fv) else round(fv, 2)


def _agg(group: pd.DataFrame) -> dict:
    amounts = group["amount_initial"].dropna()
    return {
        "count": int(group["id"].nunique()),
        "total": _num(amounts.sum()) if len(amounts) else 0.0,
        "mean": _num(amounts.mean()) if len(amounts) else None,
        "median": _num(amounts.median()) if len(amounts) else None,
        "paid": _num(group["amount_paid"].dropna().sum()) if group["amount_paid"].notna().any() else 0.0,
        "with_amount": int(len(amounts)),
    }


def ranking(df: pd.DataFrame, key: str, label: str | None = None, labels: dict | None = None, explode: bool = False,
            keep_missing: bool = False, top: int = 20) -> dict:
    """Classements par nombre ET par montant total (le montant moyen est fourni pour chaque entrée)."""
    if df.empty:
        return {"by_count": [], "by_total": [], "by_mean": [], "missing": 0}
    data = df.explode(key) if explode else df
    missing = int(data[key].isna().sum()) if not explode else int(df[key].apply(lambda v: len(v) == 0).sum())
    if keep_missing:
        data = data.assign(**{key: data[key].fillna(MISSING)})
    data = data[data[key].notna()]
    items = []
    for k, g in data.groupby(key, sort=False):
        lab = labels.get(k, k) if labels else (g[label].dropna().iloc[0] if label and g[label].notna().any() else k)
        items.append({"key": str(k), "label": str(lab), **_agg(g)})
    by_count = sorted(items, key=lambda x: (-x["count"], -(x["total"] or 0), x["label"]))[:top]
    by_total = sorted(items, key=lambda x: (-(x["total"] or 0), -x["count"], x["label"]))[:top]
    by_mean = sorted([i for i in items if i["mean"] is not None], key=lambda x: (-(x["mean"] or 0), -x["count"]))[:top]
    return {"by_count": by_count, "by_total": by_total, "by_mean": by_mean, "missing": missing}


def compute(df: pd.DataFrame, names: RefNames) -> dict:
    if df.empty:
        return {"summary": {"count": 0, "total": 0.0, "paid": 0.0, "mean": None, "median": None}, "rankings": {}, "time": {},
                "caveats": CAVEATS, "empty": True}
    amounts = df["amount_initial"].dropna()
    paid = df["amount_paid"].dropna()
    summary = {
        "count": int(len(df)),
        "total": _num(amounts.sum()) or 0.0,
        "paid": _num(paid.sum()) or 0.0,
        "mean": _num(amounts.mean()) if len(amounts) else None,
        "median": _num(amounts.median()) if len(amounts) else None,
        "min": _num(amounts.min()) if len(amounts) else None,
        "max": _num(amounts.max()) if len(amounts) else None,
        "with_amount": int(len(amounts)),
        "with_paid_amount": int(len(paid)),
        "currencies": sorted(df["currency"].dropna().unique().tolist()),
        "first_date": df["date"].min().date().isoformat() if df["date"].notna().any() else None,
        "last_date": df["date"].max().date().isoformat() if df["date"].notna().any() else None,
        "by_status": {k: int(v) for k, v in df["status"].value_counts().items()},
        "by_geo_status": {k: int(v) for k, v in df["geo_status"].value_counts().items()},
        "geolocated": int(df["geo_status"].isin(["train_confirmed", "train_route", "path_inferred", "manual", "od_only"]).sum()),
        "not_geolocated": int((df["geo_status"] == "none").sum()),
        "missing": {
            "amount": int(df["amount_initial"].isna().sum()),
            "date": int(df["date"].isna().sum()),
            "time": int(df["hour"].isna().sum()),
            "stations": int((df["origin_id"].isna() & df["dest_id"].isna()).sum()),
            "train_type": int(df["train_type"].isna().sum()),
        },
        "demo": int(df["is_demo"].sum()),
    }
    line_labels = {k: (v.get("name") or v.get("code") or k) for k, v in names.lines.items()}
    od = df[df["origin_label"].notna() & df["dest_label"].notna()].assign(
        od=lambda x: x["origin_label"] + " → " + x["dest_label"])
    stations_any = pd.concat([
        df[["id", "amount_initial", "amount_paid", "origin_id", "origin_label"]].rename(columns={"origin_id": "sid", "origin_label": "slabel"}),
        df[["id", "amount_initial", "amount_paid", "dest_id", "dest_label"]].rename(columns={"dest_id": "sid", "dest_label": "slabel"}),
        df[["id", "amount_initial", "amount_paid", "control_id", "control_label"]].rename(columns={"control_id": "sid", "control_label": "slabel"}),
    ])
    stations_any = stations_any[stations_any["sid"].notna()].drop_duplicates(["id", "sid"])
    rankings = {
        "lines": ranking(df, "line_ids", labels=line_labels, explode=True),
        "routes": ranking(df, "route_key", "route_label"),
        "od": ranking(od, "od", "od") if not od.empty else ranking(od, "id"),
        "trains": ranking(df, "train_number", "train_number"),
        "train_types": ranking(df, "train_type", labels={**TRAIN_TYPES, MISSING: MISSING}, keep_missing=True),
        "origins": ranking(df, "origin_label", "origin_label"),
        "destinations": ranking(df, "dest_label", "dest_label"),
        "stations": ranking(stations_any, "sid", "slabel"),
        "reasons": ranking(df, "reason", labels={**REASONS, MISSING: MISSING}, keep_missing=True),
        "carriers": ranking(df, "carrier", "carrier", keep_missing=True),
        "countries": ranking(df, "country", labels={**COUNTRIES, MISSING: MISSING}, keep_missing=True),
        "statuses": ranking(df, "status", labels=FINE_STATUSES),
        "geo_statuses": ranking(df, "geo_status", labels=GEO_STATUSES),
    }
    hours = []
    for h in range(24):
        g = df[df["hour"] == h]
        hours.append({"hour": h, **_agg(g)} if len(g) else {"hour": h, "count": 0, "total": 0.0, "mean": None, "median": None, "paid": 0.0, "with_amount": 0})
    slots = []
    for label, a, b in TIME_SLOTS:
        g = df[(df["hour"] >= a) & (df["hour"] <= b)]
        slots.append({"slot": label, **(_agg(g) if len(g) else {"count": 0, "total": 0.0, "mean": None, "median": None, "paid": 0.0, "with_amount": 0})})
    weekdays = []
    for i, name in enumerate(WEEKDAYS_FR):
        g = df[df["weekday"] == i]
        weekdays.append({"weekday": i, "label": name, **(_agg(g) if len(g) else {"count": 0, "total": 0.0, "mean": None, "median": None, "paid": 0.0, "with_amount": 0})})
    heat = []
    sub = df[df["weekday"].notna() & df["hour"].notna()]
    if not sub.empty:
        for (wd, h), g in sub.groupby(["weekday", "hour"]):
            heat.append({"weekday": int(wd), "hour": int(h), "count": int(len(g)), "total": _num(g["amount_initial"].dropna().sum()) or 0.0})
    months = []
    if df["month"].notna().any():
        periods = pd.period_range(df["date"].min(), df["date"].max(), freq="M")
        for p in periods:
            key = p.strftime("%Y-%m")
            g = df[df["month"] == key]
            months.append({"month": key, **(_agg(g) if len(g) else {"count": 0, "total": 0.0, "mean": None, "median": None, "paid": 0.0, "with_amount": 0})})
    years = [{"year": int(y), **_agg(g)} for y, g in df[df["year"].notna()].groupby("year")]
    ranked_hours = sorted([h for h in hours if h["count"]], key=lambda x: (-x["count"], -(x["total"] or 0)))
    return {
        "summary": summary,
        "rankings": rankings,
        "time": {"hours": hours, "hours_ranked": ranked_hours, "slots": slots, "weekdays": weekdays, "heatmap": heat,
                 "months": months, "years": years},
        "caveats": CAVEATS,
        "empty": False,
    }


def frame_to_records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    out = df.drop(columns=["line_ids"]).copy()
    out["line_ids"] = df["line_ids"].apply(lambda v: ";".join(v))
    out["date"] = df["date"].dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")
