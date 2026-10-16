# Dossier de données (non versionné)

- `reference/` : référentiel ferroviaire public, régénérable avec `railfine data update`
  (`rail.sqlite`, `graph.pickle`, téléchargements bruts dans `raw/`).
- `user/` : VOS DONNÉES PERSONNELLES — amendes (`railfine.sqlite`), documents importés
  (`documents/`, nommés par empreinte SHA-256), paramètres (`settings.json`), sel de hachage
  (`.secret`), exports (`exports/`).

Ne partagez pas `user/`. Utilisez Paramètres > Sauvegarde pour en faire une copie.
