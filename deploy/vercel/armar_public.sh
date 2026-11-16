#!/usr/bin/env bash
# Vercel (despliegue desde GitHub): arma public/ con el frontend estático, sin las páginas internas del equipo.
# La función /api/* es api/index.py y lee backend/ (incluida la copia de anuncios backend/data/ads_snapshot.jsonl.gz).
set -euo pipefail
rm -rf public
mkdir -p public
cp -r frontend/. public/
rm -rf public/afiliaciones-check.html public/login.html public/Procfile public/package.json public/node_modules public/prototipo-*.html
test -f backend/data/ads_snapshot.jsonl.gz || { echo "Falta backend/data/ads_snapshot.jsonl.gz" >&2; exit 1; }
echo "public/ listo: $(find public -type f | wc -l) archivos"
