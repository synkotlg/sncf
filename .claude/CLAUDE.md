# RailFine Analytics — guide du dépôt

Application locale (FastAPI + React/TypeScript/MapLibre) : carte ferroviaire France/Belgique et
analyse des amendes de l'utilisateur. Langue de l'interface et des messages : français.

## Commandes

- Environnement : `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
- Tests backend : `python -m pytest` (doivent tous passer avant un commit)
- Front : `cd frontend && npm install && npm run typecheck && npm run build`
- Serveur : `railfine serve` (http://127.0.0.1:8000, sert `frontend/dist`)
- Référentiel : `railfine data update [--groups base,sncf,infrabel,osm,gtfs]`, `railfine data status`
- Exemples fictifs : `railfine demo load|remove|documents`

## Règles du projet (à respecter)

- Ne jamais confondre ligne physique (`lines`), itinéraire commercial (`routes`) et circulation
  (`trains`) : tables, libellés et statistiques séparés.
- Ne jamais inventer de données : un champ non trouvé reste vide, un appariement ambigu renvoie
  des candidats (pas de choix au hasard), une source indisponible est signalée (pas de données
  simulées). Les exemples sont FICTIFS et marqués `is_demo`.
- Statistiques : toujours distinguer nombre, montant total, montant moyen/médian ; ne pas parler
  de risque ni de causalité (voir `analytics/stats.py: CAVEATS`).
- Confidentialité : données utilisateur uniquement dans `data/user/` (gitignoré) ; numéro de
  dossier stocké seulement en HMAC ; pas d'appel réseau avec des données d'amende ; OCR local.
- Sécurité : requêtes modifiantes avec l'en-tête `X-RailFine-Request: 1` ; type réel des fichiers
  vérifié (`ingest/filetypes.py`) ; jamais de nom de fichier utilisateur comme chemin.
- Séparation des dossiers : `reference/` (données publiques), `ingest/` (import), `user/`
  (données personnelles), `analytics/` (résultats), `frontend/src/map/` (cartographie),
  `config.py` (paramètres).
- Interface sombre : couleurs dans `frontend/src/theme.ts` (palette validée contraste/daltonisme,
  ordre fixe des catégories). Une seule échelle par graphique (pas de double axe).
- Pas d'emoji dans le code, les messages ni la documentation.

## Repères

- Importeurs de sources : `backend/railfine/reference/importers/` ; registre documenté :
  `reference/sources.py` (ajouter toute nouvelle source ici avec licence, fréquence, limites).
- Extraction des champs : `ingest/parser.py` (tests : `backend/tests/test_parser.py`, textes
  fictifs dans `backend/tests/fixtures/texts/`).
- Rattachement carte : `user/geomatch.py` ; graphe : `reference/graph.py`.
- Les caches du graphe et de l'index des gares sont indexés par (chemin de base, version).
