"""
Convierte el token de corta duración de Meta (~1 hora) en uno de larga duración (~60 días).

Uso (desde la carpeta backend/):
    1. En el Explorador de la Graph API genera un token NUEVO (el vencido no se puede renovar).
    2. Pégalo en backend/.env.local como META_AD_LIBRARY_TOKEN=...
    3. Agrega también META_APP_ID=... y META_APP_SECRET=... (de tu app en developers.facebook.com).
    4. Ejecuta:  .\\venv\\Scripts\\python.exe tools\\renovar_token_meta.py
    5. Reinicia el backend.

El script reescribe META_AD_LIBRARY_TOKEN en .env.local. Nunca imprime el token ni el secreto de la app.
El archivo .env.local está fuera de git; no lo subas ni lo compartas.
"""
import os
import re
import sys

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, ".env.local")


def leer_env(ruta):
    valores = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", linea)
            if m and not linea.lstrip().startswith("#"):
                valores[m.group(1)] = m.group(2)
    return valores


def escribir_token(ruta, nuevo):
    with open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    salida, hecho = [], False
    for linea in lineas:
        if re.match(r"^\s*META_AD_LIBRARY_TOKEN\s*=", linea):
            salida.append(f"META_AD_LIBRARY_TOKEN={nuevo}")
            hecho = True
        else:
            salida.append(linea)
    if not hecho:
        salida.append(f"META_AD_LIBRARY_TOKEN={nuevo}")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")


def main():
    if not os.path.exists(RUTA):
        print(f"No existe {RUTA}.")
        return 1
    env = leer_env(RUTA)
    faltan = [k for k in ("META_APP_ID", "META_APP_SECRET", "META_AD_LIBRARY_TOKEN") if not env.get(k)]
    if faltan:
        print("Faltan en backend/.env.local: " + ", ".join(faltan))
        return 1

    version = env.get("META_GRAPH_VERSION", "v23.0")
    try:
        r = requests.get(
            f"https://graph.facebook.com/{version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": env["META_APP_ID"],
                "client_secret": env["META_APP_SECRET"],
                "fb_exchange_token": env["META_AD_LIBRARY_TOKEN"],
            },
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"Error de red: {type(e).__name__}")
        return 1

    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    if r.status_code != 200 or "access_token" not in cuerpo:
        error = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
        mensaje = str(error.get("message", f"HTTP {r.status_code}"))
        for secreto in (env["META_AD_LIBRARY_TOKEN"], env["META_APP_SECRET"]):
            mensaje = mensaje.replace(secreto, "***")
        print(f"Meta rechazó el intercambio (código {error.get('code')}): {mensaje}")
        if error.get("code") == 190:
            print("El token ya venció: genera uno nuevo en el Explorador de la Graph API y vuelve a ejecutar esto enseguida.")
        return 1

    escribir_token(RUTA, cuerpo["access_token"])
    dias = round(int(cuerpo.get("expires_in", 0)) / 86400) if cuerpo.get("expires_in") else "?"
    print(f"Listo: token de larga duración guardado en .env.local (vence en unos {dias} días). Reinicia el backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
