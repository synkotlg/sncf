"""Fixtures de test.

ATTENTION : le petit réseau et les gares définis ici sont SYNTHÉTIQUES (géométries
simplifiées, codes UIC fictifs) et servent uniquement à tester les algorithmes.
Ils ne sont jamais écrits dans le dossier data/ de l'application.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from shapely.geometry import LineString

from railfine.config import AppConfig
from railfine.reference import graph as graph_mod
from railfine.reference import matching
from railfine.reference.store import LineRecord, ReferenceStore, StationRecord

FIXTURES = Path(__file__).parent / "fixtures"

TEST_STATIONS = [
    # (id source, nom, lat, lon, uic, pays, alias)
    ("a", "Alpha Ville", 48.001, 2.0, "8700001", "FR", []),
    ("d", "Delta", 48.0005, 3.5, "8700002", "FR", []),
    ("b", "Beta Centre", 48.0, 4.0, "8700003", "FR", []),
    ("g", "Gamma", 46.0, 3.0, "8700004", "FR", []),
    ("s1", "Saint-Test", 48.0, 2.5, "8700005", "FR", []),
    ("s2", "Saint-Test", 45.0, 6.5, "8800006", "BE", []),
    ("bm", "Brussel-Zuid", 45.0, 6.9, "8800007", "BE", [("Bruxelles-Midi", "fr")]),
    ("lf", "Lille Flandres", 47.0, 5.0, "8700008", "FR", []),
    ("le", "Lille Europe", 47.002, 5.003, "8700009", "FR", []),
]


def build_reference(path: Path) -> ReferenceStore:
    store = ReferenceStore(path)
    store.replace_station_records("test_fixture", [
        StationRecord(source="test_fixture", source_id=sid, name=name, lat=lat, lon=lon, uic=uic, country=cc, aliases=aliases)
        for sid, name, lat, lon, uic, cc, aliases in TEST_STATIONS
    ])
    store.finalize()
    lines = [
        LineRecord(id="rfn:000001", code="000001", name="Ligne test A (Alpha - Beta)", country="FR", infra_type="classique",
                   status="exploitee", source="sncf_rfn_lines", geom=LineString([(2.0, 48.0), (2.5, 48.0), (3.5, 48.0), (4.0, 48.0)])),
        # branche qui rejoint la ligne A en son milieu SANS sommet commun (jonction en T à raccorder)
        LineRecord(id="rfn:000002", code="000002", name="Ligne test B (embranchement Gamma)", country="FR", infra_type="classique",
                   status="exploitee", source="sncf_rfn_lines", geom=LineString([(3.0, 46.0), (3.0, 47.0), (3.0, 47.9996)])),
        LineRecord(id="rfn:000003", code="000003", name="Ligne test C (isolée)", country="BE", infra_type="lgv",
                   status="exploitee", source="sncf_rfn_lines", geom=LineString([(6.5, 45.0), (6.9, 45.0)])),
        LineRecord(id="rfn:000004", code="000004", name="Ligne test fermée", country="FR", infra_type="classique",
                   status="fermee", source="sncf_rfn_lines", geom=LineString([(2.0, 48.0), (3.0, 46.0)])),
    ]
    store.replace_lines("sncf_rfn_lines", lines)
    store.finalize()
    graph_mod.reset_cache()
    matching.reset_index()
    return store


def gtfs_zip_bytes() -> bytes:
    """GTFS minimal synthétique : un train TER n° 12345 Alpha -> Delta -> Beta, le 14/03/2025."""
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA1,TER,https://example.invalid,Europe/Paris\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\nR1,A1,K99,Alpha - Beta,2\nBUS,A1,C1,Car de substitution,3\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,trip_short_name\nR1,S1,T1,12345,12345\nBUS,S1,T2,99999,99999\n",
        "stops.txt": ("stop_id,stop_name,stop_lat,stop_lon,parent_station\n"
                      "StopPoint:OCETrain TER-87000011,ALPHA VILLE,48.001,2.0,\n"
                      "StopPoint:OCETrain TER-87000029,DELTA,48.0005,3.5,\n"
                      "StopPoint:OCETrain TER-87000037,BETA CENTRE,48.0,4.0,\n"),
        "stop_times.txt": ("trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                           "T1,07:30:00,07:30:00,StopPoint:OCETrain TER-87000011,0\n"
                           "T1,07:52:00,07:53:00,StopPoint:OCETrain TER-87000029,1\n"
                           "T1,08:10:00,08:10:00,StopPoint:OCETrain TER-87000037,2\n"
                           "T2,09:00:00,09:00:00,StopPoint:OCETrain TER-87000011,0\n"
                           "T2,09:30:00,09:30:00,StopPoint:OCETrain TER-87000037,1\n"),
        "calendar_dates.txt": "service_id,date,exception_type\nS1,20250314,1\nS1,20250315,1\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    graph_mod.reset_cache()
    matching.reset_index()
    return AppConfig(tmp_path / "data")


@pytest.fixture
def ref_cfg(cfg) -> AppConfig:
    build_reference(cfg.paths.reference_db)
    return cfg


@pytest.fixture
def texts() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in (FIXTURES / "texts").glob("*.txt")}
