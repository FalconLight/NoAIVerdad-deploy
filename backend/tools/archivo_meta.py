"""
Archivo histórico de anuncios de Meta: capturar, revisar, mover y volver a cargar. Ver docs/archivo-meta.md y backend/archivo_meta.py.

Uso (desde la carpeta backend/, con el Python que tiene las dependencias):
    python tools\\archivo_meta.py capturar                       # baja todo lo que falte, mes a mes hacia atrás, y refresca los últimos 120 días
    python tools\\archivo_meta.py capturar --desde 2025-01-01    # solo hasta esa fecha
    python tools\\archivo_meta.py capturar --forzar              # vuelve a bajar también los meses ya completos
    python tools\\archivo_meta.py estado                         # cuántos anuncios hay y de qué meses
    python tools\\archivo_meta.py verificar                      # comprueba cada archivo contra el manifiesto (sha256 y cuentas)
    python tools\\archivo_meta.py exportar D:\\copias\\archivo-meta.zip
    python tools\\archivo_meta.py importar D:\\copias\\archivo-meta.zip      # fusiona: no borra nada de lo que ya hay
    python tools\\archivo_meta.py snapshot --salida data\\ads_historico.json --desde 2026-01-01
        # copia en el formato de la app; se carga con AD_LIBRARY_SNAPSHOT=<esa ruta> y AD_LIBRARY_SOLO_COPIA=true
    python tools\\archivo_meta.py sqlite D:\\copias\\anuncios-meta.sqlite            # base de datos SQLite (estándar: DB Browser, DBeaver, Python, R, Power BI por ODBC)
    python tools\\archivo_meta.py csv D:\\copias\\anuncios-meta-csv                  # las mismas tablas en CSV (Excel, Power BI)

La carpeta del archivo es AD_LIBRARY_ARCHIVO_DIR (en backend/.env.local) o, si no está, backend/data/archivo. `--carpeta` la cambia.
`capturar` usa el token de Meta de backend/.env.local; el resto no llama a Meta. Si la captura se corta (límite de ritmo, red, token), se
vuelve a ejecutar el mismo comando: continúa donde quedó.
"""
import argparse
import json
import os
import sys
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _preparar():
    sys.path.insert(0, RAIZ)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(RAIZ, ".env"))
        load_dotenv(os.path.join(RAIZ, ".env.local"), override=True)
    except ImportError:
        pass
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def _cliente(sin_red: bool):
    import ads_library
    if sin_red:
        os.environ.setdefault("META_AD_LIBRARY_TOKEN", "sin-red")

        def bloqueada(*_a, **_k):
            raise RuntimeError("Este comando no llama a Meta.")

        ads_library.requests.get = bloqueada
    os.environ["AD_LIBRARY_ARCHIVAR"] = "false"            # la herramienta escribe en el archivo por su cuenta
    return ads_library.AdLibraryClient()


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Archivo histórico de anuncios de Meta.")
    ap.add_argument("--carpeta", default=None, help="carpeta del archivo (por defecto AD_LIBRARY_ARCHIVO_DIR o backend/data/archivo)")
    sub = ap.add_subparsers(dest="orden", required=True)
    c = sub.add_parser("capturar", help="baja de Meta lo que falte y lo fusiona en el archivo")
    c.add_argument("--desde", type=date.fromisoformat, default=None, help="fecha más antigua (AAAA-MM-DD); por defecto, hace 7 años")
    c.add_argument("--hasta", type=date.fromisoformat, default=None, help="fecha más reciente; por defecto, hoy")
    c.add_argument("--forzar", action="store_true", help="vuelve a bajar los meses ya completos")
    c.add_argument("--pausa", type=float, default=1.5, help="segundos entre consultas (por defecto 1.5)")
    c.add_argument("--limite", type=int, default=None, help="anuncios por consulta (por defecto el de la app, 500)")
    sub.add_parser("estado", help="resumen del archivo")
    sub.add_parser("verificar", help="comprueba la integridad del archivo")
    e = sub.add_parser("exportar", help="empaqueta el archivo en un .zip")
    e.add_argument("ruta")
    i = sub.add_parser("importar", help="fusiona un .zip (o carpeta) de archivo con este")
    i.add_argument("ruta")
    s = sub.add_parser("snapshot", help="escribe una copia en el formato de la app a partir del archivo")
    s.add_argument("--salida", required=True)
    s.add_argument("--desde", default=None, help="AAAA-MM-DD (inicio del anuncio)")
    s.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    s.add_argument("--dias", type=int, default=None, help="en lugar de --desde: los últimos N días")
    q = sub.add_parser("sqlite", help="exporta el archivo a una base de datos SQLite")
    q.add_argument("ruta")
    q.add_argument("--sin-raw", action="store_true", help="no incluir la respuesta original de Meta en cada fila (archivo más pequeño)")
    v = sub.add_parser("csv", help="exporta el archivo a tablas CSV (una carpeta)")
    v.add_argument("carpeta_csv")
    for p in (q, v):
        p.add_argument("--desde", default=None, help="AAAA-MM-DD (inicio del anuncio)")
        p.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    args = ap.parse_args()

    _preparar()
    import archivo_meta
    cliente = _cliente(sin_red=args.orden != "capturar")
    carpeta = args.carpeta or os.getenv("AD_LIBRARY_ARCHIVO_DIR", "").strip() or os.path.join(RAIZ, "data", "archivo")
    archivo = archivo_meta.ArchivoMeta(carpeta, pais=cliente.country)

    if args.orden == "capturar":
        print(f"Archivo: {archivo.carpeta}")
        cliente.timeout = max(cliente.timeout, 120.0)      # los meses con anuncios pesados tardan: mejor esperar que partir la página
        r = archivo_meta.capturar(cliente, archivo, desde=args.desde, hasta=args.hasta, forzar=args.forzar, pausa=args.pausa, limite=args.limite)
        est = archivo.estado()
        print(f"\nCaptura: {r['ventanas']} meses bajados, {r['saltadas']} ya completos, {r['recibidos']} anuncios recibidos "
              f"({r['nuevos']} nuevos, {r['actualizados']} actualizados) en {r['consultas']} consultas. Campos: {r['campos']}.")
        print(f"Archivo: {est['total']} anuncios, de {est['primer_mes']} a {est['ultimo_mes']} ({_mb(est['bytes'])}).")
        if r.get("campos_reducidos"):
            print(f"{r['campos_reducidos']} anuncios se guardaron sin su reparto por edad o por región (Meta no los entrega enteros); "
                  "sus ids están en manifest.json, en la ventana de su mes.")
        if r["detenido"]:
            print(f"\nDETENIDO: {r['detenido']}\nVuelve a ejecutar el mismo comando para continuar donde quedó.")
            return 2
        return 0

    if args.orden == "estado":
        est = archivo.estado()
        print(f"Archivo: {est['carpeta']}")
        print(f"{est['total']} anuncios en {est['meses']} meses, de {est['primer_mes']} a {est['ultimo_mes']} ({_mb(est['bytes'])}); "
              f"{est['sin_fecha']} sin fecha. Actualizado: {est['actualizado'] or '—'}.")
        print(f"Meses capturados completos: {est['ventanas_completas']} (el más antiguo: {est['primera_ventana_completa']}). "
              f"Incompletos: {', '.join(est['ventanas_incompletas']) or 'ninguno'}.")
        for mes, n in est["por_mes"].items():
            print(f"  {mes}  {n:>8}")
        return 0

    if args.orden == "verificar":
        v = archivo.verificar()
        print(f"{'CORRECTO' if v['ok'] else 'CON PROBLEMAS'}: {v['anuncios']} anuncios en {v['meses']} meses.")
        for p in v["problemas"]:
            print(f"  - {p}")
        return 0 if v["ok"] else 1

    if args.orden == "exportar":
        r = archivo.exportar(args.ruta)
        print(f"Exportado: {r['ruta']} ({_mb(r['bytes'])}; {r['anuncios']} anuncios, {r['meses']} meses).")
        return 0

    if args.orden == "importar":
        r = archivo.importar(args.ruta)
        print(f"Importado: {r['recibidos']} anuncios leídos ({r['nuevos']} nuevos, {r['actualizados']} actualizados, {r['sin_cambios']} sin cambios).")
        return 0

    if args.orden == "sqlite":
        import ads_library
        r = archivo_meta.exportar_sqlite(archivo, args.ruta, desde=args.desde, hasta=args.hasta, con_raw=not args.sin_raw, retirado=ads_library._retirado_por_meta)
        print(f"Base de datos SQLite: {r['ruta']} ({_mb(r['bytes'])}). {r['anuncios']} anuncios (inicio de {r['primer_inicio']} a {r['ultimo_inicio']}), "
              f"{r['regiones']} filas de regiones, {r['demografia']} de demografía, {r['versiones']} versiones de texto.")
        return 0

    if args.orden == "csv":
        import ads_library
        r = archivo_meta.exportar_csv(archivo, args.carpeta_csv, desde=args.desde, hasta=args.hasta, retirado=ads_library._retirado_por_meta)
        print(f"CSV en {r['carpeta']} ({_mb(r['bytes'])}): anuncios.csv ({r['anuncios']}), anuncio_regiones.csv ({r['anuncio_regiones']}), "
              f"anuncio_demografia.csv ({r['anuncio_demografia']}), anuncio_versiones.csv ({r['anuncio_versiones']}).")
        return 0

    if args.orden == "snapshot":
        r = archivo_meta.escribir_snapshot(archivo, cliente, args.salida, desde=args.desde, hasta=args.hasta, dias=args.dias)
        print(json.dumps(r, ensure_ascii=False))
        print(f"Para cargarla: AD_LIBRARY_SNAPSHOT={r['ruta']} y AD_LIBRARY_SOLO_COPIA=true (no hace falta token).")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
