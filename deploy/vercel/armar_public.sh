#!/usr/bin/env bash
# Vercel (despliegue desde GitHub): arma public/ con el frontend estático, sin las páginas internas del equipo.
# La función /api/* es api/index.py y lee backend/ (incluida la copia de anuncios backend/data/ads_snapshot.jsonl.gz).
set -euo pipefail
rm -rf public
mkdir -p public
cp -r frontend/. public/
rm -rf public/afiliaciones-check.html public/login.html public/Procfile public/package.json public/node_modules public/prototipo-*.html
test -f backend/data/ads_snapshot.jsonl.gz || { echo "Falta backend/data/ads_snapshot.jsonl.gz" >&2; exit 1; }
# Respuestas precalculadas (deploy/precalcular_api.py): solo se publican si salieron de esta misma copia de anuncios.
# Si no coinciden, la web lo pide todo a la función (más lento y gasta CPU, pero nunca muestra datos de otra copia).
if [ -f public/data/api/snapshot.sha256 ]; then
  actual="$(sha256sum backend/data/ads_snapshot.jsonl.gz | cut -d' ' -f1)"
  if [ "$actual" != "$(tr -d '[:space:]' < public/data/api/snapshot.sha256)" ]; then
    echo "AVISO: public/data/api no corresponde a la copia de anuncios actual; no se publica. Ejecuta: python deploy/precalcular_api.py" >&2
    rm -rf public/data/api
  else
    echo "Respuestas precalculadas: $(find public/data/api -name '*.json' | wc -l) archivos"
  fi
fi
echo "public/ listo: $(find public -type f | wc -l) archivos"
