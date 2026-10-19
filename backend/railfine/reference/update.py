"""Orchestration de la mise a jour du referentiel ferroviaire.

Groupes de sources :
- ``base``     : sources communautaires/domaine public heberges sur GitHub (gares Trainline + iRail,
                 frontieres et reseau Natural Earth FR/BE + voisins CH/DE/ES/GB, tunnel sous la Manche) ;
- ``sncf``     : SNCF Open Data (lignes RFN, statuts, gares) ;
- ``infrabel`` : Infrabel Open Data (lignes et points operationnels belges) ;
- ``osm``      : OpenStreetMap / Overpass (voies et itineraires route=train) ;
- ``gtfs``     : horaires theoriques SNCF + SNCB (itineraires et numeros de train).

Chaque etape est independante : l'echec d'une source est journalise et
n'empeche pas les autres. Aucune donnee n'est simulee en cas d'echec.
"""

from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Callable

from ..config import AppConfig
from . import graph as graph_mod
from . import matching
from .importers import fixed_links, gtfs, infrabel, naturalearth, osm_overpass, sncf_opendata, stations_github
from .importers.common import SourceUnavailable
from .store import ReferenceStore

log = logging.getLogger("railfine.update")

GROUPS = ("base", "sncf", "infrabel", "osm", "gtfs")
DEFAULT_GROUPS = ("base", "sncf", "infrabel", "gtfs")


def run_update(cfg: AppConfig, groups=DEFAULT_GROUPS, progress: Callable[[str], None] | None = None,
               gtfs_files: dict[str, Path] | None = None) -> dict:
    store = ReferenceStore(cfg.paths.reference_db)
    raw = cfg.paths.raw_dir
    report: dict[str, dict] = {}

    def say(msg: str) -> None:
        log.info(msg)
        if progress:
            progress(msg)

    def step(name: str, source_id: str, fn: Callable[[], object]) -> None:
        say(f"{name} ...")
        t0 = time.time()
        try:
            result = fn()
            report[name] = {"status": "ok", "result": result, "seconds": round(time.time() - t0, 1)}
            say(f"{name} : ok ({result})")
        except SourceUnavailable as exc:
            report[name] = {"status": "indisponible", "message": str(exc)}
            store.log_run(source_id, "indisponible", 0, message=str(exc))
            say(f"{name} : source indisponible - {exc}")
        except Exception as exc:  # erreur de format : on journalise et on continue
            report[name] = {"status": "erreur", "message": f"{type(exc).__name__}: {exc}"}
            store.log_run(source_id, "erreur", 0, message=traceback.format_exc()[-1500:])
            say(f"{name} : erreur - {exc}")

    groups = tuple(g for g in groups if g in GROUPS)
    countries_path = raw / "naturalearth" / "ne_10m_admin_0_countries.geojson"

    # 1. gares (necessaires avant GTFS / OSM pour rattacher les arrets)
    if "base" in groups:
        step("Fond de carte (Natural Earth)", "naturalearth_countries", lambda: naturalearth.import_basemap(store, raw)[0])
        step("Gares Trainline", "trainline_stations", lambda: stations_github.import_trainline(store, raw))
        step("Gares iRail", "irail_stations", lambda: stations_github.import_irail(store, raw))
    if "sncf" in groups:
        step("Gares SNCF", "sncf_stations", lambda: sncf_opendata.import_stations(store, raw))
    if "infrabel" in groups:
        step("Points operationnels Infrabel", "infrabel_points", lambda: infrabel.import_points(store, raw))
    say("Fusion des gares ...")
    report["fusion_gares"] = store.finalize()

    # 2. lignes physiques
    if "base" in groups and countries_path.exists():
        step("Reseau de secours (Natural Earth)", "naturalearth_rail",
             lambda: naturalearth.import_rail(store, raw, countries_path))
    if "sncf" in groups:
        step("Lignes RFN (SNCF Reseau)", "sncf_rfn_lines", lambda: sncf_opendata.import_lines(store, raw))
    if "infrabel" in groups:
        step("Lignes Infrabel", "infrabel_lines", lambda: infrabel.import_lines(store, raw))
    if "osm" in groups:
        step("OpenStreetMap (voies + itineraires)", "osm_overpass", lambda: osm_overpass.import_osm(store, raw))
    if "base" in groups:
        step("Liaisons fixes (tunnel sous la Manche)", "fixed_links", lambda: fixed_links.import_fixed_links(store, raw))

    # 3. itineraires commerciaux et circulations
    if "gtfs" in groups:
        files = gtfs_files or {}
        step("GTFS SNCF", "sncf_gtfs", lambda: gtfs.import_gtfs(store, raw, "sncf_gtfs", file=files.get("sncf_gtfs")))
        step("GTFS SNCB", "sncb_gtfs", lambda: gtfs.import_gtfs(store, raw, "sncb_gtfs", file=files.get("sncb_gtfs")))

    say("Consolidation ...")
    report["consolidation"] = store.finalize()
    graph_mod.reset_cache()
    matching.reset_index()
    say("Construction du graphe du reseau ...")
    g = graph_mod.get_graph(store, cfg.paths.graph_cache)
    report["graphe"] = {"noeuds": len(g.nodes), "aretes": len(g.edges), "gares_rattachees": len(g.station_node)}
    say("Traces des itineraires commerciaux ...")
    report["itineraires_traces"] = graph_mod.build_route_geometries(store, g)
    say("Mise a jour terminee.")
    return report


def import_gtfs_file(cfg: AppConfig, source_id: str, file: Path) -> dict:
    store = ReferenceStore(cfg.paths.reference_db)
    result = gtfs.import_gtfs(store, cfg.paths.raw_dir, source_id, file=file)
    store.finalize()
    graph_mod.reset_cache()
    matching.reset_index()
    g = graph_mod.get_graph(store, cfg.paths.graph_cache)
    result["itineraires_traces"] = graph_mod.build_route_geometries(store, g)
    return result
