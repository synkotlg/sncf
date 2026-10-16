---
name: railfine-data
description: Mettre à jour ou étendre le référentiel ferroviaire de RailFine (SNCF Open Data, Infrabel, GTFS SNCF/SNCB, OpenStreetMap, Trainline, iRail, Natural Earth) et diagnostiquer une source en échec.
---

# Référentiel ferroviaire

## Mettre à jour

- `railfine data update` (groupes par défaut : base, sncf, infrabel, gtfs) ; `--groups osm` pour
  OpenStreetMap (volumineux). Résultat par source : `railfine data status` ou Paramètres.
- GTFS téléchargé manuellement : `railfine data gtfs --source sncf_gtfs|sncb_gtfs --file x.zip`.
- Après mise à jour, les amendes sont recalculées (`railfine rematch` sinon).

## Diagnostiquer une source en échec

1. Lire le message dans `source_runs` (`railfine data status`) : HTTP 403/404, quota (429), format.
2. Opendatasoft (SNCF, Infrabel) : vérifier l'identifiant du jeu sur le portail ; le corriger dans
   `reference/sources.py` (`urls`) ou dans l'appel `ods_export` de l'importeur. Les champs sont lus
   de façon tolérante (`importers/common.py: pick`) : ajouter le nouveau nom de champ à la liste
   des candidats plutôt que de supposer.
3. Ne jamais remplacer une source manquante par des données inventées : laisser la source en
   « indisponible » et documenter la limite dans le README.

## Ajouter une source

1. Déclarer la source dans `reference/sources.py` (producteur, ce qu'elle représente, licence,
   fréquence, limites, priorité : plus petit = prioritaire).
2. Écrire l'importeur dans `reference/importers/` en produisant `StationRecord`, `LineRecord`
   (ligne physique), `RouteRecord` (itinéraire commercial) ou des lignes `trains` (circulations).
3. L'ajouter à `reference/update.py` dans le bon groupe, puis un test de parsing sur un petit
   fichier synthétique de même format.
4. Pour un nouveau type de ligne physique, définir sa tolérance dans `graph.py: SOURCE_TOLERANCES`.
