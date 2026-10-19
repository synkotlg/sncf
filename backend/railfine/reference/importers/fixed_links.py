"""Liaisons ferroviaires fixes transfrontalieres tracees a la main.

Certaines liaisons majeures ne figurent pas (ou sont coupees) dans les sources
generalisees : le tunnel sous la Manche est un ouvrage sous-marin que Natural
Earth 1:10m ne represente pas, et le decoupage des reseaux par frontiere
terrestre laisserait de toute facon les reseaux francais et britannique
deconnectes. On ajoute donc ici une geometrie indicative, tracee d'apres les
coordonnees publiques des deux portails, pour que le reseau soit continu de part
et d'autre du detroit du Pas-de-Calais.

La ligne est enregistree avec ``country=None`` (ouvrage international) afin de
rester toujours active : la selection "meilleure source par pays" ne la met pas
en concurrence avec les lignes nationales.
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString

from ..store import LineRecord, ReferenceStore

SOURCE_ID = "fixed_links"

# Portail de Coquelles (Calais, FR) -> portail de Cheriton / Folkestone (GB).
# Trace quasi rectiligne sous le detroit du Pas-de-Calais (~50,5 km).
CHANNEL_TUNNEL: list[tuple[float, float]] = [
    (1.78160, 50.92240),  # portail francais (Coquelles)
    (1.70000, 50.95500),
    (1.52000, 51.00200),
    (1.33000, 51.04500),
    (1.12860, 51.09560),  # portail britannique (Cheriton, Folkestone)
]


def import_fixed_links(store: ReferenceStore, raw_dir: Path | None = None) -> int:
    records = [
        LineRecord(
            id="fixed:channel_tunnel",
            geom=LineString(CHANNEL_TUNNEL),
            source=SOURCE_ID,
            country=None,  # ouvrage international FR <-> GB : reste toujours actif
            infra_type="lgv",  # ligne a grande vitesse (Eurostar / Eurotunnel)
            electrified="oui",
            tracks="multiple",
            name="Tunnel sous la Manche (Eurotunnel)",
            extra={
                "operator": "Getlink / Eurotunnel",
                "connects": ["FR", "GB"],
                "length_km": 50.45,
                "opened": 1994,
            },
        )
    ]
    n = store.replace_lines(SOURCE_ID, records)
    store.log_run(SOURCE_ID, "ok", n)
    return n
