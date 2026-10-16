"""Appariement des gares, graphe du réseau, tuiles, importeurs (sur données SYNTHÉTIQUES)."""

from pathlib import Path

import mapbox_vector_tile

from railfine.reference import graph as graph_mod
from railfine.reference import matching
from railfine.reference.importers import gtfs, sncf_opendata, stations_github
from railfine.reference.service_category import categorize
from railfine.reference.store import ReferenceStore
from railfine.reference.tiles import TileRenderer

from .conftest import gtfs_zip_bytes


def test_station_matching(ref_cfg):
    idx = matching.get_index(ReferenceStore(ref_cfg.paths.reference_db))
    m = idx.match("ALPHA VILLE")
    assert m.station_id == "uic:8700001" and m.confidence == 1.0 and not m.ambiguous
    # alias bilingue
    assert idx.match("Bruxelles-Midi").station_id == "uic:8800007"
    # homonymes éloignés : choix manuel, sauf indice de pays
    hom = idx.match("Saint-Test")
    assert hom.station_id is None and hom.ambiguous
    assert idx.match("Saint-Test", country_hint="BE").station_id == "uic:8800006"
    # libellé partiel commun à plusieurs gares : jamais choisi au hasard
    part = idx.match("Lille")
    assert part.station_id is None and part.ambiguous and len(part.candidates) == 2
    # nom inconnu : rien
    assert idx.match("Zzyzx").station_id is None
    # erreur d'OCR légère tolérée
    assert idx.match("ALPHA V1LLE").station_id == "uic:8700001"


def test_find_mentions(ref_cfg):
    idx = matching.get_index(ReferenceStore(ref_cfg.paths.reference_db))
    names = [n for n, _ in idx.find_mentions("Voyage de ALPHA VILLE vers Beta Centre")]
    assert names == ["Alpha Ville", "Beta Centre"]


def test_graph_path_with_t_junction(ref_cfg):
    store = ReferenceStore(ref_cfg.paths.reference_db)
    g = graph_mod.get_graph(store, ref_cfg.paths.graph_cache)
    for sid in ("uic:8700001", "uic:8700003", "uic:8700004"):
        assert sid in g.station_node
    res = g.path(["uic:8700001", "uic:8700004"])
    assert res is not None
    ids = {l["id"] for l in res.lines}
    assert ids == {"rfn:000001", "rfn:000002"}  # la jonction en T a été raccordée
    assert "rfn:000004" not in ids  # ligne fermée exclue
    assert 290 < res.length_km < 305  # 74,4 km (1 degre de longitude a 48N) + 222 km
    # réseau disjoint : pas de chemin inventé
    assert g.path(["uic:8700001", "uic:8800006"]) is None


def test_graph_cache_reload(ref_cfg):
    store = ReferenceStore(ref_cfg.paths.reference_db)
    g1 = graph_mod.get_graph(store, ref_cfg.paths.graph_cache)
    graph_mod.reset_cache()
    g2 = graph_mod.get_graph(store, ref_cfg.paths.graph_cache)  # relu depuis le cache disque
    assert len(g1.edges) == len(g2.edges) and g2.version == g1.version


def test_tiles(ref_cfg):
    store = ReferenceStore(ref_cfg.paths.reference_db)
    tr = TileRenderer(store.path)
    data = tr.render(store.version(), "lines", 5, 16, 11)
    decoded = mapbox_vector_tile.decode(data)
    assert "lines" in decoded and len(decoded["lines"]["features"]) >= 1
    stations = mapbox_vector_tile.decode(tr.render(store.version(), "stations", 10, 517, 352))
    assert isinstance(stations, dict)


def test_gtfs_import_and_train_index(ref_cfg, tmp_path):
    store = ReferenceStore(ref_cfg.paths.reference_db)
    zpath = tmp_path / "g.zip"
    zpath.write_bytes(gtfs_zip_bytes())
    res = gtfs.import_gtfs(store, ref_cfg.paths.raw_dir, "sncf_gtfs", file=zpath)
    assert res == {"routes": 1, "trains": 1}  # l'autocar est ignoré
    conn = store.connect()
    row = conn.execute("SELECT * FROM trains WHERE train_number='12345'").fetchone()
    conn.close()
    assert row["category"] == "TER"
    assert "20250314" in row["dates"]


def test_trainline_and_irail_parsers(tmp_path):
    tl = tmp_path / "t.csv"
    tl.write_text(
        "id;name;uic;latitude;longitude;country;is_city;is_main_station;is_suggestable;sncf_is_enabled;benerail_is_enabled;same_as\n"
        "1;Gare Test;87000011;48.0;2.0;FR;f;t;t;t;f;\n"
        "2;Ville Test;;48.0;2.0;FR;t;f;t;f;f;\n"
        "3;Doublon;87000029;48.0;2.0;FR;f;f;t;t;f;1\n"
        "4;Test Gare Routière;87000037;48.0;2.0;FR;f;f;t;t;f;\n",
        encoding="utf-8",
    )
    recs = stations_github.parse_trainline(tl)
    assert [r.name for r in recs] == ["Gare Test"] and recs[0].uic == "8700001" and recs[0].importance == 2
    ir = tmp_path / "i.csv"
    ir.write_text(
        "URI,name,alternative-fr,alternative-nl,alternative-de,alternative-en,taf-tap-code,telegraph-code,country-code,longitude,latitude,avg_stop_times,official_transfer_time\n"
        "http://irail.be/stations/NMBS/008800007,Brussel-Zuid,Bruxelles-Midi,,,,,,be,4.3,50.8,900,\n",
        encoding="utf-8",
    )
    r = stations_github.parse_irail(ir)[0]
    assert r.uic == "8800007" and r.importance == 1 and ("Bruxelles-Midi", "fr") in r.aliases


def test_sncf_line_parsing():
    feats = [
        {"type": "Feature", "properties": {"code_ligne": "752000", "lib_ligne": "LGV Sud-Est"},
         "geometry": {"type": "LineString", "coordinates": [[2.0, 48.0], [3.0, 47.0]]}},
        {"type": "Feature", "properties": {"code_ligne": 830000, "lib_ligne": "Ligne de Paris-Lyon à Marseille"},
         "geometry": {"type": "LineString", "coordinates": [[2.0, 48.0], [4.0, 45.0]]}},
    ]
    recs = {r.code: r for r in sncf_opendata.parse_line_features(feats, {"830000": {"Exploitée"}}, {})}
    assert recs["752000"].infra_type == "lgv"
    assert recs["830000"].infra_type == "classique"
    assert recs["830000"].status == "exploitee"
    assert sncf_opendata.classify_infra("Ligne de la Porte", []) == "classique"


def test_service_categories():
    assert categorize("TER Hauts-de-France") == "TER"
    assert categorize(None, "SNCF", "TGV INOUI Paris - Lyon") == "TGV"
    assert categorize("Transilien", None, "Ligne P") == "TRANSILIEN"
    assert categorize("RER", None, "RER B") == "RER"
    assert categorize("NMBS/SNCB") == "SNCB"
    assert categorize(None, None, "Train touristique") == "AUTRE"
