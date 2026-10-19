"""Registre documente des sources de donnees ferroviaires ouvertes.

Chaque source precise : producteur, licence, frequence de mise a jour annoncee,
ce qu'elle represente (ligne physique / itineraire commercial / circulation)
et ses limites. Les URL de telechargement sont des *candidats* : si un portail
change d'adresse, l'importeur essaie les suivants puis signale l'echec.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    provider: str
    represents: str
    licence: str
    attribution: str
    update_frequency: str
    homepage: str
    urls: tuple[str, ...] = ()
    limits: str = ""
    priority: int = 50  # plus petit = prioritaire quand plusieurs sources decrivent le meme objet
    tags: tuple[str, ...] = field(default_factory=tuple)


SNCF_ODS_BASES = (
    "https://ressources.data.sncf.com/api/explore/v2.1",
    "https://data.sncf.com/api/explore/v2.1",
)
INFRABEL_ODS_BASES = ("https://opendata.infrabel.be/api/explore/v2.1",)

SOURCES: dict[str, Source] = {
    s.id: s
    for s in [
        Source(
            id="sncf_rfn_lines",
            name="Formes des lignes du Reseau Ferre National",
            provider="SNCF Reseau (SNCF Open Data)",
            represents="Lignes physiques (infrastructure), code ligne RFN",
            licence="Licence Ouverte / ODbL selon jeu (voir portail)",
            attribution="SNCF Reseau - data.sncf.com",
            update_frequency="Annuelle a semestrielle",
            homepage="https://data.sncf.com/explore/dataset/formes-des-lignes-du-rfn/",
            urls=("formes-des-lignes-du-rfn",),
            limits="Precision decametrique (1/50 000). Ne decrit ni les dessertes ni les horaires.",
            priority=10,
            tags=("lines", "FR"),
        ),
        Source(
            id="sncf_line_types",
            name="Lignes par type / par statut",
            provider="SNCF Reseau (SNCF Open Data)",
            represents="Attributs des lignes physiques (LGV, statut exploitee/neutralisee...)",
            licence="Licence Ouverte / ODbL selon jeu (voir portail)",
            attribution="SNCF Reseau - data.sncf.com",
            update_frequency="Semestrielle",
            homepage="https://data.sncf.com/explore/dataset/lignes-par-statut/",
            urls=("lignes-par-statut", "lignes-par-type"),
            limits="Decoupage par troncons ; un code ligne peut avoir plusieurs statuts.",
            priority=10,
            tags=("lines", "FR"),
        ),
        Source(
            id="sncf_stations",
            name="Gares de voyageurs / Liste des gares",
            provider="SNCF (SNCF Open Data)",
            represents="Gares et points remarquables (code UIC, coordonnees)",
            licence="ODbL / Licence Ouverte selon jeu",
            attribution="SNCF - data.sncf.com",
            update_frequency="Plusieurs fois par an",
            homepage="https://data.sncf.com/explore/dataset/gares-de-voyageurs/",
            urls=("gares-de-voyageurs", "liste-des-gares"),
            limits="Inclut des points sans trafic voyageurs dans 'liste-des-gares'.",
            priority=10,
            tags=("stations", "FR"),
        ),
        Source(
            id="sncf_gtfs",
            name="Horaires theoriques SNCF (GTFS TER, Intercites, TGV)",
            provider="SNCF Voyageurs (SNCF Open Data / transport.data.gouv.fr)",
            represents="Itineraires commerciaux (routes) et circulations (numeros de train)",
            licence="ODbL",
            attribution="SNCF Voyageurs",
            update_frequency="Quotidienne a hebdomadaire",
            homepage="https://transport.data.gouv.fr/datasets?type=public-transit&q=sncf",
            urls=(
                "https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip",
                "https://eu.ftp.opendatasoft.com/sncf/gtfs/export-ter-gtfs-last.zip",
                "https://eu.ftp.opendatasoft.com/sncf/gtfs/export-intercites-gtfs-last.zip",
                "https://eu.ftp.opendatasoft.com/sncf/gtfs/export_gtfs_voyages.zip",
            ),
            limits=(
                "Horaires theoriques sur une fenetre glissante (quelques semaines/mois) : "
                "un ancien numero de train peut ne plus y figurer. Pas de temps reel. "
                "Pas de traces (shapes) : la geometrie est reconstruite sur le reseau physique."
            ),
            priority=10,
            tags=("gtfs", "FR"),
        ),
        Source(
            id="infrabel_lines",
            name="Lignes et sections de lignes Infrabel",
            provider="Infrabel Open Data",
            represents="Lignes physiques belges (numero de ligne Infrabel)",
            licence="Licence Infrabel Open Data (reutilisation libre avec mention)",
            attribution="Infrabel",
            update_frequency="Plusieurs fois par an",
            homepage="https://opendata.infrabel.be/",
            urls=("lijnsecties", "geografische-positie-van-de-spoorlijnen", "spoorlijnen"),
            limits="Identifiants de jeux susceptibles d'evoluer ; recherche par mots-cles en secours.",
            priority=10,
            tags=("lines", "BE"),
        ),
        Source(
            id="infrabel_points",
            name="Points operationnels du reseau Infrabel",
            provider="Infrabel Open Data",
            represents="Gares et points operationnels belges",
            licence="Licence Infrabel Open Data",
            attribution="Infrabel",
            update_frequency="Plusieurs fois par an",
            homepage="https://opendata.infrabel.be/explore/dataset/operationele-punten-van-het-netwerk/",
            urls=("operationele-punten-van-het-netwerk",),
            limits="Contient aussi des points sans arret voyageurs.",
            priority=20,
            tags=("stations", "BE"),
        ),
        Source(
            id="sncb_gtfs",
            name="Horaires theoriques SNCB (GTFS)",
            provider="SNCB/NMBS",
            represents="Itineraires commerciaux et circulations belges",
            licence="Licence SNCB open data (conditions sur le portail)",
            attribution="SNCB/NMBS",
            update_frequency="Hebdomadaire",
            homepage="https://www.belgiantrain.be/fr/3rd-party-services/mobility-service-providers/public-data",
            urls=("https://sncb-opendata.hafas.de/gtfs/static/c21ac6758dd25af84cca5b707f3cb3de",),
            limits="Acces parfois soumis a enregistrement ; importer le ZIP manuellement si besoin.",
            priority=10,
            tags=("gtfs", "BE"),
        ),
        Source(
            id="osm_overpass",
            name="OpenStreetMap (Overpass API)",
            provider="Contributeurs OpenStreetMap",
            represents="Voies ferrees (railway=rail) et relations d'itineraires (route=train)",
            licence="ODbL 1.0",
            attribution="(c) contributeurs OpenStreetMap",
            update_frequency="Continue (instantane a la date d'import)",
            homepage="https://wiki.openstreetmap.org/wiki/Overpass_API",
            urls=("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"),
            limits="Donnees contributives, completude variable. Respecter les limites d'usage d'Overpass.",
            priority=30,
            tags=("lines", "routes", "FR", "BE"),
        ),
        Source(
            id="trainline_stations",
            name="Trainline EU stations",
            provider="Trainline (agrege OSM, SNCF Open Data, GeoNames)",
            represents="Gares (UIC, coordonnees, gare principale)",
            licence="ODbL 1.0",
            attribution="Trainline EU stations (ODbL)",
            update_frequency="Irreguliere (depot GitHub)",
            homepage="https://github.com/trainline-eu/stations",
            urls=("https://raw.githubusercontent.com/trainline-eu/stations/master/stations.csv",),
            limits=(
                "Inclut certains arrets d'autocars SNCF ayant un code UIC ; "
                "le drapeau 'gare principale' est indique comme peu fiable par l'editeur."
            ),
            priority=40,
            tags=("stations", "FR", "BE"),
        ),
        Source(
            id="irail_stations",
            name="iRail stations",
            provider="iRail (communaute open data belge)",
            represents="Gares belges, noms FR/NL/DE/EN, frequentation moyenne (arrets/jour)",
            licence="CC0 1.0",
            attribution="iRail",
            update_frequency="Irreguliere (depot GitHub)",
            homepage="https://github.com/iRail/stations",
            urls=("https://raw.githubusercontent.com/iRail/stations/master/stations.csv",),
            limits="Couvre la SNCB ; quelques gares etrangeres desservies.",
            priority=20,
            tags=("stations", "BE"),
        ),
        Source(
            id="naturalearth_rail",
            name="Natural Earth - Railroads 1:10m",
            provider="Natural Earth",
            represents="Reseau ferre physique simplifie (sans nom ni code de ligne)",
            licence="Domaine public",
            attribution="Made with Natural Earth",
            update_frequency="Pluriannuelle",
            homepage="https://www.naturalearthdata.com/downloads/10m-cultural-vectors/railroads/",
            urls=(
                "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_railroads.geojson",
            ),
            limits=(
                "Generalisation a petite echelle (ecarts de plusieurs centaines de metres a quelques km), "
                "lignes secondaires incompletes, aucun nom ni type de service. Pour la France et la Belgique, "
                "utilise seulement en secours quand les sources officielles ne sont pas encore importees ; "
                "pour les pays voisins (CH, DE, ES, GB), c'est la source affichee du reseau."
            ),
            priority=90,
            tags=("lines", "FR", "BE", "CH", "DE", "ES", "GB"),
        ),
        Source(
            id="fixed_links",
            name="Liaisons ferroviaires fixes transfrontalieres",
            provider="RailFine (trace a la main d'apres coordonnees publiques)",
            represents="Ouvrages reliant deux reseaux nationaux, absents des sources generalisees (tunnel sous la Manche)",
            licence="Domaine public (geometrie indicative)",
            attribution="RailFine",
            update_frequency="Statique",
            homepage="https://fr.wikipedia.org/wiki/Tunnel_sous_la_Manche",
            limits="Trace indicatif (ligne quasi rectiligne entre les deux portails), non geometrie d'ingenierie.",
            priority=5,
            tags=("lines", "FR", "GB"),
        ),
        Source(
            id="naturalearth_countries",
            name="Natural Earth - Admin 0 countries 1:10m",
            provider="Natural Earth",
            represents="Frontieres pour le fond de carte hors ligne",
            licence="Domaine public",
            attribution="Made with Natural Earth",
            update_frequency="Pluriannuelle",
            homepage="https://www.naturalearthdata.com/downloads/10m-cultural-vectors/",
            urls=(
                "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson",
            ),
            priority=90,
            tags=("basemap",),
        ),
    ]
}


def describe_sources() -> list[dict]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "provider": s.provider,
            "represents": s.represents,
            "licence": s.licence,
            "attribution": s.attribution,
            "update_frequency": s.update_frequency,
            "homepage": s.homepage,
            "limits": s.limits,
            "tags": list(s.tags),
        }
        for s in SOURCES.values()
    ]
