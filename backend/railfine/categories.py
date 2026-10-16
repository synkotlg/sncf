"""Vocabulaires contrôlés partagés par l'extraction, le stockage, les statistiques et l'interface."""

from __future__ import annotations

# Catégories commerciales de trains (service), distinctes de la nature de l'infrastructure.
TRAIN_TYPES: dict[str, str] = {
    "TGV": "TGV (INOUI, OUIGO, Lyria...)",
    "TER": "TER",
    "INTERCITES": "Intercités",
    "TRANSILIEN": "Transilien",
    "RER": "RER",
    "SNCB": "Trains belges (SNCB/NMBS)",
    "EUROSTAR": "Eurostar / ex-Thalys",
    "AUTRE": "Autre",
    "INCONNU": "Inconnu",
}

# Nature de l'infrastructure (ligne physique).
INFRA_TYPES: dict[str, str] = {
    "lgv": "Ligne à grande vitesse",
    "classique": "Ligne classique",
    "raccordement": "Raccordement / embranchement",
    "inconnu": "Type non renseigné",
}

FINE_STATUSES: dict[str, str] = {
    "a_payer": "À payer",
    "payee": "Payée",
    "contestee": "Contestée",
    "inconnue": "Inconnue",
}

REASONS: dict[str, str] = {
    "absence_titre": "Absence de titre de transport",
    "titre_non_valide": "Titre non valable pour ce trajet / ce train",
    "non_validation": "Titre non validé (non composté)",
    "surclassement": "Voyage en classe supérieure",
    "reduction": "Réduction ou carte non justifiée",
    "depassement": "Dépassement de parcours",
    "comportement": "Comportement (tabac, pieds sur siège...)",
    "refus": "Refus d'obtempérer / identité",
    "autre": "Autre motif",
}

GEO_STATUSES: dict[str, str] = {
    "train_confirmed": "Trajet relié via le numéro de train (GTFS)",
    "train_route": "Train identifié, portion parcourue inconnue (itinéraire complet)",
    "path_inferred": "Trajet présumé (plus court chemin sur le réseau)",
    "manual": "Correspondance définie manuellement",
    "od_only": "Gares identifiées, tracé ferroviaire indisponible",
    "station_only": "Une seule gare identifiée",
    "none": "Non géolocalisée",
}

COUNTRIES: dict[str, str] = {"FR": "France", "BE": "Belgique"}

TIME_SLOTS: list[tuple[str, int, int]] = [
    ("nuit (0h-5h)", 0, 5),
    ("pointe matin (6h-9h)", 6, 9),
    ("journée (10h-15h)", 10, 15),
    ("pointe soir (16h-19h)", 16, 19),
    ("soirée (20h-23h)", 20, 23),
]

WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def time_slot(hour: int | None) -> str | None:
    if hour is None:
        return None
    for label, start, end in TIME_SLOTS:
        if start <= hour <= end:
            return label
    return None


def options() -> dict:
    return {
        "train_types": TRAIN_TYPES,
        "infra_types": INFRA_TYPES,
        "statuses": FINE_STATUSES,
        "reasons": REASONS,
        "geo_statuses": GEO_STATUSES,
        "countries": COUNTRIES,
        "time_slots": [t[0] for t in TIME_SLOTS],
        "weekdays": WEEKDAYS_FR,
    }
