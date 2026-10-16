#!/usr/bin/env sh
# Lancement de RailFine Analytics (macOS / Linux), après installation (voir README.md)
set -e
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] || { echo "Environnement Python absent : voir README (Installation)"; exit 1; }
. .venv/bin/activate
[ -f frontend/dist/index.html ] || { echo "Interface non compilée : cd frontend && npm install && npm run build"; exit 1; }
exec railfine serve
