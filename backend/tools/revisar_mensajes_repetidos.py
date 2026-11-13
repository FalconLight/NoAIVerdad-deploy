"""
Revisa los «mensajes repetidos» con la copia local de anuncios (backend/data/ads_snapshot.json): imprime los grupos que la app reportaría,
con lo necesario para decidir si cada uno es una coincidencia real. NO llama a Meta ni escribe nada.

Uso (desde la carpeta backend/):
    .\\.venv\\Scripts\\python.exe tools\\revisar_mensajes_repetidos.py                    # resumen y los 20 primeros grupos
    .\\.venv\\Scripts\\python.exe tools\\revisar_mensajes_repetidos.py --todos            # todos los grupos
    .\\.venv\\Scripts\\python.exe tools\\revisar_mensajes_repetidos.py --aisladas         # solo las coincidencias aisladas (las más dudosas)
    .\\.venv\\Scripts\\python.exe tools\\revisar_mensajes_repetidos.py --umbral 0.9       # prueba otro umbral de similitud (por defecto 0.8)
    .\\.venv\\Scripts\\python.exe tools\\revisar_mensajes_repetidos.py --provincia Guayas --con-cne

Cómo leer cada grupo:
- «textos» = 1 es el mismo texto palabra por palabra (sin contar enlaces, hashtags ni menciones); más de 1, variantes casi idénticas.
- «coincidencias» = en cuántos grupos aparecen juntas las mismas páginas. 1 es una coincidencia aislada (puede ser casual: ambas copian
  un comunicado); cuantas más, más pesa el patrón (o una sola mano detrás de varias páginas: únelas en Entidades).
- «días» entre el primer y el último anuncio del grupo; 0 = el mismo día.
- «mismo partido» solo aparece si TODAS las páginas tienen el mismo partido verificado en afiliaciones.json (reuso esperado).
Después de un cambio en el método (backend/ads_library.py: `_texto_comparable`, `_sustituye_datos`, `_info_textos`), ejecútalo antes y después y
compara los grupos: el método no debe perder coincidencias reales ni inventar otras.
"""
import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar_cliente():
    """Un cliente que solo lee la copia local: sin token real, con la copia siempre vigente y con la red bloqueada."""
    os.environ["META_AD_LIBRARY_TOKEN"] = "sin-red"
    os.environ["META_INTEGRATION_ENABLED"] = "true"
    os.environ["AD_LIBRARY_CACHE_MIN"] = "100000000"
    sys.path.insert(0, RAIZ)
    import ads_library

    def sin_red(*_args, **_kwargs):
        raise RuntimeError("Esta herramienta no llama a Meta.")

    ads_library.requests.get = sin_red
    return ads_library.AdLibraryClient()


def corto(texto, ancho):
    return " ".join(str(texto or "").split())[:ancho]


def main():
    ap = argparse.ArgumentParser(description="Revisa los grupos de mensajes repetidos con la copia local de anuncios.")
    ap.add_argument("--limite", type=int, default=20, help="cuántos grupos imprimir (por defecto 20)")
    ap.add_argument("--todos", action="store_true", help="imprime todos los grupos")
    ap.add_argument("--aisladas", action="store_true", help="solo los grupos cuyas páginas no coinciden en ningún otro")
    ap.add_argument("--umbral", type=float, default=0.8, help="similitud mínima entre textos (por defecto 0.8)")
    ap.add_argument("--provincia", default=None, help="solo los anuncios que llegan a esa provincia (por defecto, todo el país)")
    ap.add_argument("--con-cne", action="store_true", help="incluye los anuncios del Consejo Nacional Electoral (por defecto se excluyen)")
    ap.add_argument("--ancho", type=int, default=260, help="caracteres del texto que se imprimen de cada grupo")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cliente = cargar_cliente()
    ads, estado = cliente.obtener_nacional()
    if not ads or not estado.get("desde_copia"):
        print("No hay una copia local utilizable (backend/data/ads_snapshot.json): arranca el backend una vez para que descargue los anuncios.")
        return 1
    r = cliente.textos_duplicados(args.provincia, 1_000_000, umbral=args.umbral, sin_cne=not args.con_cne)
    grupos = r["grupos"]
    aisladas = sum(1 for g in grupos if g["coincidencias"] == 1)
    recurrentes = sum(1 for g in grupos if g["coincidencias"] >= 3)
    print(f"{len(ads)} anuncios en la copia (guardada {estado.get('actualizado')}) | {r['analizados']} comparables | umbral {args.umbral}")
    print(f"{len(grupos)} grupos entre páginas distintas: {recurrentes} con páginas que coinciden en ≥ 3 mensajes, {aisladas} coincidencias aisladas")
    print(f"se mantuvieron aparte {r['plantillas_separadas']} textos que solo cambian un nombre o una cifra | "
          f"{r['textos_muy_extendidos']['textos']} textos en {r['textos_muy_extendidos']['paginas_minimas']}+ páginas omitidos | "
          f"{r['retirados_por_meta']['anuncios']} anuncios retirados por Meta excluidos")
    if r["textos_muy_extendidos"]["ejemplos"]:
        for e in r["textos_muy_extendidos"]["ejemplos"]:
            print(f"   omitido: {e['paginas']} páginas, {e['anuncios']} anuncios: {corto(e['texto'], 100)}")

    seleccion = [g for g in grupos if not args.aisladas or g["coincidencias"] == 1]
    if not args.todos:
        seleccion = seleccion[:max(1, args.limite)]
    print()
    for i, g in enumerate(seleccion, 1):
        paginas = "; ".join(
            f"{p['page_name'].strip()} ×{p['anuncios']}" + (f" [{p['afiliacion'].get('partido') or p['afiliacion'].get('afiliacion')}"
                                                           f"{'' if p['afiliacion'].get('verificado') else ', sin verificar'}]" if p["afiliacion"] else "")
            for p in g["paginas"][:8]) + (" …" if len(g["paginas"]) > 8 else "")
        dias = "?" if g["dias"] is None else ("el mismo día" if g["dias"] == 0 else f"{g['dias']} días")
        print(f"#{i}  {g['n_paginas']} páginas · {g['anuncios']} anuncios · textos {g['n_textos']} · similitud ≥ {g['similitud_minima']} · "
              f"coincidencias {g['coincidencias']} · {g['primer_anuncio']} → {g['ultimo_anuncio']} ({dias})"
              + (f" · mismo partido: {g['mismo_partido']}" if g["mismo_partido"] else ""))
        print(f"    páginas: {paginas}")
        print(f"    texto:   {corto(g['texto'], args.ancho)}")
    if not args.todos and len(grupos) > len(seleccion) and not args.aisladas:
        print(f"\n… y {len(grupos) - len(seleccion)} grupos más (--todos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
