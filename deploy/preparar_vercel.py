"""
Arma el proyecto que se publica en Vercel (showcase público, plan Hobby gratuito).

    python deploy/preparar_vercel.py [--snapshot RUTA/ads_snapshot.json] [--salida dist-vercel]

Resultado:
    public/        el frontend estático (sin las páginas internas del equipo)
    api/index.py   el backend FastAPI como función Python, servido en el mismo dominio (/api/*)
    backend/       el código del backend y la copia de anuncios (no se publica como archivo: solo la lee la función)
Nunca copia .env, .env.local ni credenciales.
"""
import argparse
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
FRONTEND = RAIZ / "frontend"
PLANTILLA = Path(__file__).resolve().parent / "vercel"
# La copia más reciente suele estar en la versión de desarrollo; si no, en la de publicación.
CANDIDATAS = [RAIZ.parent / "NoAIVerdad-v06" / "backend" / "data" / "ads_snapshot.json",
              RAIZ.parent / "NoAIVerdad-release" / "backend" / "data" / "ads_snapshot.json",
              BACKEND / "data" / "ads_snapshot.json"]
ARCHIVOS_BACKEND = ["main.py", "ads_library.py", "archivo_meta.py", "blue_sky_service.py", "firebase_store.py", "meta_service.py",
                    "news_collector.py", "news_service.py", "twitter_service.py", "x_service.py",
                    "afiliaciones.json", "medios_locales.json", "mensajes_revisados.json"]
FUERA_DEL_FRONTEND = {"afiliaciones-check.html", "login.html", "Procfile", "package.json", "node_modules"}
# Dependencias que el showcase no usa (Firebase Admin no se configura) o que solo sirven al servidor local.
FUERA_DE_REQUISITOS = ("firebase-admin", "uvloop", "watchfiles")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot", type=Path, help="ads_snapshot.json a incluir (por defecto, el más reciente que encuentre)")
    p.add_argument("--salida", type=Path, default=RAIZ / "dist-vercel")
    a = p.parse_args()

    snapshot = a.snapshot or max((c for c in CANDIDATAS if c.exists()), key=lambda c: c.stat().st_mtime, default=None)
    if not snapshot or not snapshot.exists():
        raise SystemExit("No encontré ads_snapshot.json; indícalo con --snapshot.")

    salida = a.salida.resolve()
    vercel_local = salida / ".vercel"                       # conserva el enlace con el proyecto de Vercel entre ejecuciones
    guardado = None
    if vercel_local.exists():
        guardado = RAIZ / ".vercel-enlace-tmp"
        shutil.rmtree(guardado, ignore_errors=True)
        shutil.move(str(vercel_local), guardado)
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    if guardado:
        shutil.move(str(guardado), vercel_local)

    shutil.copytree(FRONTEND, salida / "public", ignore=lambda d, nombres: [n for n in nombres if n in FUERA_DEL_FRONTEND or n.startswith("prototipo")])
    (salida / "backend" / "data").mkdir(parents=True)
    for nombre in ARCHIVOS_BACKEND:
        if (BACKEND / nombre).exists():
            shutil.copy2(BACKEND / nombre, salida / "backend" / nombre)
    shutil.copy2(snapshot, salida / "backend" / "data" / "ads_snapshot.json")
    shutil.copytree(PLANTILLA / "api", salida / "api")
    shutil.copy2(PLANTILLA / "vercel.json", salida / "vercel.json")
    requisitos = [l for l in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.lower().startswith(FUERA_DE_REQUISITOS)]
    (salida / "requirements.txt").write_text("\n".join(requisitos) + "\n", encoding="utf-8")
    (salida / ".python-version").write_text("3.12\n", encoding="utf-8")

    tam = snapshot.stat().st_size / 1e6
    print(f"Listo: {salida}\n  copia de anuncios: {snapshot} ({tam:.1f} MB)")
    print(f'Publica con:  cd "{salida}"  y  npx vercel@latest deploy --prod')


if __name__ == "__main__":
    main()
