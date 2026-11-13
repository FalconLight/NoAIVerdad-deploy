"""
Arma el paquete de la beta: dist-beta/NoAIVerdad-Beta-v<versión>.zip (versión en beta/VERSION)

Contenido del zip (una carpeta NoAIVerdad-Beta-v<versión>/):
    INICIAR NoAIVerdad.bat      <- el único archivo que hay que abrir
    Guia-NoAIVerdad-Beta-v<versión>.pdf <- guía del probador (docs/, generada con beta/guia/build_guia.py)
    app/launcher.py, app/backend/ (con .env.local), app/frontend/

IMPORTANTE: el zip lleva backend/.env.local con las claves de API (Meta, GNews, Google Fact Check, X) porque la beta se
comparte así. Se OMITEN META_APP_ID y META_APP_SECRET (solo sirven para renovar el token de Meta; los probadores no
las necesitan) y los ajustes que solo valen en el equipo donde se desarrolla (rutas locales, caché congelada: SOLO_DESARROLLO). No subas el zip a git ni lo publiques: dist-*/ y .env* están en .gitignore.

Uso:   python beta/build_beta.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BETA = os.path.join(RAIZ, "beta")
SALIDA = os.path.join(RAIZ, "dist-beta")
with open(os.path.join(BETA, "VERSION"), encoding="utf-8") as _v:
    VERSION = _v.read().strip()
NOMBRE = f"NoAIVerdad-Beta-v{VERSION}"
GUIA = f"Guia-NoAIVerdad-Beta-v{VERSION}.pdf"
STAGE = os.path.join(tempfile.gettempdir(), "noaiverdad-build", NOMBRE)      # carpeta de trabajo temporal: así nunca choca con una beta abierta desde dist-beta
OMITIR_CLAVES = {"META_APP_ID", "META_APP_SECRET"}
# Ajustes del equipo de desarrollo que no deben viajar: una ruta local, una caché que nunca se renueva o un modo sin conexión a Meta
SOLO_DESARROLLO = {"AD_LIBRARY_CACHE_MIN", "AD_LIBRARY_ARCHIVO_DIR", "AD_LIBRARY_SNAPSHOT", "AD_LIBRARY_SOLO_COPIA", "AD_LIBRARY_ARCHIVAR", "AD_LIBRARY_SEGUNDO_PLANO"}
EXCLUIR_DIR = {"__pycache__", ".venv", "venv", "tests", ".pytest_cache", "node_modules", ".git"}


def copiar_arbol(origen: str, destino: str, solo_datos: bool = False) -> None:
    for dirpath, dirs, files in os.walk(origen):
        dirs[:] = [d for d in dirs if d not in EXCLUIR_DIR]
        rel = os.path.relpath(dirpath, origen)
        for f in files:
            if f.endswith((".pyc", ".log", ".tmp")) or f.startswith(".env") or f == "renovar_token_meta.py":
                continue
            if solo_datos and rel == "data" and f != "ads_snapshot.json":
                continue
            d = os.path.join(destino, rel) if rel != "." else destino
            os.makedirs(d, exist_ok=True)
            shutil.copy2(os.path.join(dirpath, f), os.path.join(d, f))


def env_sin_renovacion(origen: str, destino: str) -> list:
    """Copia .env.local sin las claves de renovación de Meta; devuelve los nombres de las claves incluidas."""
    incluidas, comentarios = [], []          # los comentarios se retienen hasta saber si la clave que explican se incluye
    with open(origen, encoding="utf-8") as f, open(destino, "w", encoding="utf-8", newline="\n") as out:
        for linea in f:
            if linea.lstrip().startswith("#"):
                comentarios.append(linea)
                continue
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=", linea)
            if m and m.group(1) in OMITIR_CLAVES | SOLO_DESARROLLO:
                comentarios = []                     # se va la clave y el comentario que la acompaña
                continue
            if m:
                incluidas.append(m.group(1))
            out.writelines(comentarios)
            comentarios = []
            out.write(linea)
        out.writelines(comentarios)
    return incluidas


def commit_actual() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, text=True).strip()
    except Exception:  # noqa: BLE001
        return "sin-git"


def main() -> int:
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    app = os.path.join(STAGE, "app")
    os.makedirs(app)

    copiar_arbol(os.path.join(RAIZ, "backend"), os.path.join(app, "backend"), solo_datos=True)
    copiar_arbol(os.path.join(RAIZ, "frontend"), os.path.join(app, "frontend"))
    shutil.copy2(os.path.join(BETA, "launcher.py"), os.path.join(app, "launcher.py"))
    shutil.copy2(os.path.join(BETA, "instalar.py"), os.path.join(app, "instalar.py"))

    # El .bat debe llevar saltos de línea de Windows
    with open(os.path.join(BETA, "INICIAR_NoAIVerdad.bat"), encoding="utf-8") as f:
        bat = f.read().replace("\r\n", "\n").replace("\n", "\r\n")
    with open(os.path.join(STAGE, "INICIAR NoAIVerdad.bat"), "w", encoding="utf-8", newline="") as f:
        f.write(bat)

    # Variante que abre la app a otros dispositivos de la red local
    with open(os.path.join(BETA, "INICIAR NoAIVerdad (red local).bat"), encoding="utf-8") as f:
        bat_red = f.read().replace("\r\n", "\n").replace("\n", "\r\n")
    with open(os.path.join(STAGE, "INICIAR NoAIVerdad (red local).bat"), "w", encoding="utf-8", newline="") as f:
        f.write(bat_red)

    env = os.path.join(RAIZ, "backend", ".env.local")
    claves = env_sin_renovacion(env, os.path.join(app, "backend", ".env.local")) if os.path.exists(env) else []
    if not claves:
        print("AVISO: no se encontró backend/.env.local; el paquete saldrá sin claves de API.")

    pdf = os.path.join(RAIZ, "docs", GUIA)
    if os.path.exists(pdf):
        shutil.copy2(pdf, os.path.join(STAGE, GUIA))
    else:
        print(f"AVISO: falta docs/{GUIA}; el zip saldrá sin la guía.")

    with open(os.path.join(app, "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(f"NoAIVerdad beta {VERSION} · {date.today().isoformat()} · {commit_actual()}\n")

    zip_ruta = os.path.join(SALIDA, f"{NOMBRE}.zip")
    if os.path.exists(zip_ruta):
        os.remove(zip_ruta)
    with zipfile.ZipFile(zip_ruta, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dirpath, _, files in os.walk(STAGE):
            for f in files:
                ruta = os.path.join(dirpath, f)
                z.write(ruta, os.path.join(NOMBRE, os.path.relpath(ruta, STAGE)))

    n = sum(len(fs) for _, _, fs in os.walk(STAGE))
    shutil.rmtree(STAGE, ignore_errors=True)
    print(f"\nListo: {zip_ruta}")
    print(f"  {n} archivos, {os.path.getsize(zip_ruta) / 1024 / 1024:.1f} MB")
    print(f"  Claves de API incluidas (solo nombres): {', '.join(claves) or 'ninguna'}")
    print(f"  Omitidas a propósito: {', '.join(sorted(OMITIR_CLAVES))}; y los ajustes de desarrollo, si estaban")
    print("  Recuerda: este zip contiene claves. No lo subas a git ni lo publiques.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
