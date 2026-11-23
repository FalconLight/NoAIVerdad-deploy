"""
Precalcula como archivos estáticos las respuestas de la API que más se piden en el showcase (Vercel).

Por qué: el plan gratuito de Vercel da 4 horas de CPU al mes a la función de Python, y cada instancia nueva tarda varios segundos solo en
leer la copia de anuncios. Con estos archivos, la vista por defecto (y el período completo) se sirve desde la CDN sin ejecutar Python.

Qué genera (en frontend/data/api/):
  · un .json por cada ruta precalculada, con la misma respuesta que daría /api/...;
  · manifest.json: ruta exacta (tal como la arma fetchApi en js/app.js) -> archivo, más el rango de fechas por defecto;
  · snapshot.sha256: huella de la copia de anuncios con la que se calcularon. deploy/vercel/armar_public.sh compara esa huella con la copia
    actual y, si no coinciden, no publica estos archivos (la web vuelve a pedirlo todo a la función: nunca sirve datos de otra copia).

Uso, cada vez que cambie backend/data/ads_snapshot.jsonl.gz (desde la raíz del repo, con un Python que tenga las dependencias):
    python deploy/precalcular_api.py
"""
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(RAIZ, "backend", "data", "ads_snapshot.jsonl.gz")
SALIDA = os.path.join(RAIZ, "frontend", "data", "api")

# Mismos identificadores que provinciasEcuador en js/app.js; «todas» = nacional
ALCANCES = ["todas", "azuay", "bolivar", "canar", "carchi", "chimborazo", "cotopaxi", "el_oro", "esmeraldas", "galapagos", "guayas",
            "imbabura", "loja", "los_rios", "manabi", "morona_santiago", "napo", "orellana", "pastaza", "pichincha", "santa_elena",
            "santo_domingo", "sucumbios", "tungurahua", "zamora_chinchipe"]

# Rutas tal como las pide la vista Conexiones (cargarTop, cargarStats, cargarMensajes, cargarRed) antes de que fetchApi añada los filtros
RUTAS_POR_ALCANCE = [
    "/api/ads/top-gastadores?provincia={a}&limite=6000",
    "/api/dashboard/stats?provincia={a}",
    "/api/ads/textos-duplicados?provincia={a}&limite=200&revisados=true",
    "/api/ads/red-pagadores?provincia={a}&limite=40&max_paginas=6000",
]
RUTAS_UNICAS = ["/api/ads/mapa"]


def huella(ruta_archivo: str) -> str:
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def con_filtros(ruta: str, sin_cne: bool, solo_activos: bool, fechas) -> str:
    """Igual que fetchApi en js/app.js: sin_cne, después solo_activos, después las fechas."""
    if sin_cne:
        ruta += ("&" if "?" in ruta else "?") + "sin_cne=true"
    if solo_activos:
        ruta += ("&" if "?" in ruta else "?") + "solo_activos=true"
    if fechas:
        ruta += ("&" if "?" in ruta else "?") + f"fecha_desde={fechas[0]}&fecha_hasta={fechas[1]}"
    return ruta


def main() -> int:
    sys.path.insert(0, RAIZ)
    from fastapi.testclient import TestClient
    from api.index import app                       # fija el modo de solo lectura y la copia de anuncios del repo

    cliente = TestClient(app)
    estado = cliente.get("/api/ads/top-gastadores?provincia=todas&limite=1").json().get("estado") or {}
    hasta = estado.get("hasta")
    if not hasta:
        print("La copia de anuncios no dice hasta qué fecha llega (estado.hasta).", file=sys.stderr)
        return 1
    desde = (date.fromisoformat(hasta) - timedelta(days=6)).isoformat()
    defecto = {"desde": desde, "hasta": hasta, "solo_activos": True}

    # Combinaciones de filtros: la vista por defecto (últimos 7 días de la copia + solo activos), el período completo y solo activos sin fechas;
    # cada una con y sin «Ocultar CNE»
    combinaciones = [(cne, act, fechas) for cne in (False, True)
                     for act, fechas in ((True, (desde, hasta)), (False, None), (True, None))]

    if os.path.isdir(SALIDA):
        shutil.rmtree(SALIDA)
    os.makedirs(SALIDA)
    rutas = {}
    total_bytes = 0
    inicio = time.time()
    for cne, act, fechas in combinaciones:
        base = RUTAS_UNICAS + [r.format(a=a) for a in ALCANCES for r in RUTAS_POR_ALCANCE]
        for r in base:
            ruta = con_filtros(r, cne, act, fechas)
            resp = cliente.get(ruta)
            if resp.status_code != 200:
                print(f"  omitida ({resp.status_code}): {ruta}", file=sys.stderr)
                continue
            nombre = hashlib.sha1(ruta.encode("utf-8")).hexdigest()[:16] + ".json"
            contenido = json.dumps(resp.json(), ensure_ascii=False, separators=(",", ":"))
            with open(os.path.join(SALIDA, nombre), "w", encoding="utf-8") as f:
                f.write(contenido)
            rutas[ruta] = nombre
            total_bytes += len(contenido.encode("utf-8"))
        print(f"  filtros sin_cne={cne} solo_activos={act} fechas={fechas}: listo ({time.time() - inicio:.0f} s)")

    manifiesto = {"version": 1, "generado": time.strftime("%Y-%m-%dT%H:%M:%S"), "copia_hasta": hasta, "defecto": defecto, "rutas": rutas}
    with open(os.path.join(SALIDA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SALIDA, "snapshot.sha256"), "w", encoding="ascii") as f:
        f.write(huella(SNAPSHOT) + "\n")
    print(f"{len(rutas)} respuestas, {total_bytes / 1e6:.1f} MB, en {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
