"""
Entrada del backend en Vercel (función Python). Vercel envía aquí todo /api/* (ver vercel.json) y FastAPI responde.

Showcase público: solo lectura, sin descargar de Meta (usa la copia compacta incluida en backend/data/ads_snapshot.jsonl.gz) y sin archivo histórico.
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")

for clave, valor in {
    "AD_LIBRARY_SNAPSHOT": os.path.join(_BACKEND, "data", "ads_snapshot.jsonl.gz"),
    "NOAI_SOLO_LECTURA": "true",
    "AD_LIBRARY_SOLO_COPIA": "true",
    "AD_LIBRARY_ARCHIVAR": "false",
    "AD_LIBRARY_SEGUNDO_PLANO": "false",
    "META_INTEGRATION_ENABLED": "false",
}.items():
    os.environ.setdefault(clave, valor)

sys.path.insert(0, _BACKEND)

from main import app  # noqa: E402,F401  (Vercel busca la variable «app»)
