---
name: railfine-dev
description: Développer, tester et vérifier RailFine Analytics (backend FastAPI, frontend React/MapLibre). À utiliser pour toute modification de code du projet, ajout de champ d'amende, de statistique ou de couche cartographique.
---

# Développer sur RailFine Analytics

## Boucle de travail

1. `. .venv/bin/activate` (créer avec `python -m venv .venv && pip install -e ".[dev]"` si absent).
2. Modifier le code en respectant `.claude/CLAUDE.md` (séparation référence / import / utilisateur / analyse).
3. Backend : `python -m pytest` ; ajouter un test pour tout comportement nouveau
   (`backend/tests/`, données synthétiques uniquement, fixtures dans `conftest.py`).
4. Frontend : `cd frontend && npm run typecheck && npm run build`.
5. Vérification réelle : `railfine serve`, puis parcourir les pages (Chromium headless possible
   via Playwright : `executable_path` du Chromium installé) et contrôler la console.

## Ajouter un champ d'amende

1. Colonne dans `user/store.py` (SCHEMA + `FINE_FIELDS`), migration douce si la base existe
   (`ALTER TABLE` conditionnel).
2. Validation dans `user/service.py: clean_fine_payload`.
3. Détection éventuelle dans `ingest/parser.py` (valeur + confiance + extrait, jamais inventée).
4. Formulaire `frontend/src/components/FineForm.tsx` (+ `payloadFrom`) et type `Fine` dans `types.ts`.
5. Statistiques : `analytics/stats.py: build_frame` puis un classement via `ranking(...)`.

## Ajouter une statistique

- Toujours exposer `count`, `total`, `mean`, `median` (fonction `_agg`), classements `by_count`,
  `by_total`, `by_mean`.
- Graphiques : `frontend/src/components/charts.ts`, une seule mesure par graphique, couleurs de
  `theme.ts`, info-bulle indiquant les trois mesures.

## Pièges connus

- pandas 3 : chaînes en dtype `str`, utiliser `fillna` avant comparaison.
- MapLibre : les URL de tuiles doivent être absolues (`window.location.origin`).
- Les glyphes de la carte sont servis depuis `frontend/public/fonts/NotoSans-*` (plages 0-255,
  256-511, 8192-8447) ; une plage absente renvoie 404 (normal).
