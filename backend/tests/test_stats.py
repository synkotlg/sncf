from railfine.analytics.stats import Filters, RefNames, apply_filters, build_frame, compute


def fine(i, amount, date, time, origin=None, dest=None, train=None, ttype=None, lines=(), status="payee", paid=None, reason=None, demo=False):
    return {
        "id": i, "amount_initial": amount, "amount_paid": paid, "currency": "EUR", "fine_date": date, "fine_time": time,
        "origin_resolved_id": origin, "dest_resolved_id": dest, "origin_name": origin, "dest_name": dest,
        "control_resolved_id": None, "train_number": train, "train_type": ttype, "carrier": "SNCF Voyageurs", "country": "FR",
        "reason": reason, "status": status, "geo_status": "path_inferred" if lines else "none", "geo_validated": 0,
        "line_label": None, "links": [{"kind": "line", "ref_id": l, "label": l, "km": 10} for l in lines], "is_demo": demo,
    }


NAMES = RefNames(stations={"A": "Gare A", "B": "Gare B", "C": "Gare C"}, lines={"L1": {"name": "Ligne 1"}, "L2": {"name": "Ligne 2"}})

FINES = [
    fine(1, 50.0, "2025-01-06", "08:10", "A", "B", "100", "TER", ["L1"], paid=50.0, reason="absence_titre"),  # lundi
    fine(2, 50.0, "2025-01-06", "08:40", "A", "B", "100", "TER", ["L1"], reason="absence_titre"),
    fine(3, 300.0, "2025-03-12", "18:05", "B", "C", "200", "TGV", ["L1", "L2"], reason="surclassement"),  # mercredi
    fine(4, None, "2025-03-15", None, None, None, None, None, []),  # samedi, incomplète
]


def test_summary_distinguishes_count_total_mean_median():
    res = compute(build_frame(FINES, NAMES), NAMES)
    s = res["summary"]
    assert s["count"] == 4
    assert s["total"] == 400.0
    assert s["paid"] == 50.0
    assert round(s["mean"], 2) == 133.33  # moyenne sur les 3 montants connus
    assert s["median"] == 50.0
    assert s["missing"]["amount"] == 1
    assert s["not_geolocated"] == 1


def test_rankings_by_count_vs_total():
    res = compute(build_frame(FINES, NAMES), NAMES)
    lines = res["rankings"]["lines"]
    assert lines["by_count"][0]["key"] == "L1" and lines["by_count"][0]["count"] == 3
    assert lines["by_total"][0]["key"] == "L1" and lines["by_total"][0]["total"] == 400.0
    assert {i["key"]: i["count"] for i in lines["by_count"]} == {"L1": 3, "L2": 1}
    trains = res["rankings"]["trains"]
    assert trains["by_count"][0]["key"] == "100"  # 2 amendes
    assert trains["by_total"][0]["key"] == "200"  # 300 EUR
    assert trains["by_mean"][0]["key"] == "200"
    od = res["rankings"]["od"]["by_count"][0]
    assert od["label"] == "Gare A → Gare B" and od["count"] == 2


def test_time_breakdowns():
    t = compute(build_frame(FINES, NAMES), NAMES)["time"]
    hours = {h["hour"]: h["count"] for h in t["hours"]}
    assert hours[8] == 2 and hours[18] == 1 and sum(hours.values()) == 3
    wd = {w["label"]: w["count"] for w in t["weekdays"]}
    assert wd["lundi"] == 2 and wd["mercredi"] == 1 and wd["samedi"] == 1
    months = [m["month"] for m in t["months"]]
    assert months == ["2025-01", "2025-02", "2025-03"]  # mois sans amende inclus (série continue)
    assert t["months"][1]["count"] == 0
    assert t["hours_ranked"][0]["hour"] == 8


def test_filters():
    df = build_frame(FINES, NAMES)
    assert len(apply_filters(df, Filters(date_from="2025-03-01"))) == 2
    assert len(apply_filters(df, Filters(line="L2"))) == 1
    assert len(apply_filters(df, Filters(station="C"))) == 1
    assert len(apply_filters(df, Filters(train_type="TER"))) == 2
    assert len(apply_filters(df, Filters(hour_from=18, hour_to=23))) == 1
    assert len(apply_filters(df, Filters.from_query({"include_demo": "false"}))) == 4


def test_empty():
    res = compute(build_frame([], NAMES), NAMES)
    assert res["empty"] and res["summary"]["count"] == 0
    assert any("risque" in c for c in res["caveats"])
