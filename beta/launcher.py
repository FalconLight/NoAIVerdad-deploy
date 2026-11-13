"""
Arranca NoAIVerdad en el equipo del probador: el backend (puerto 8000) y el frontend (puerto 3000),
y abre el navegador. Lo ejecuta «INICIAR NoAIVerdad.bat» con el Python de la carpeta app/.venv.
Cerrar esta ventana (o Ctrl+C) detiene todo.

Red local: con `NOAIVERDAD_RED=1` (lo pone «INICIAR NoAIVerdad (red local).bat») o con `--red`, los dos servidores escuchan en todas las
interfaces en vez de solo en este equipo, y se imprimen las direcciones para abrir la app desde otro dispositivo de la misma WiFi o red.
Sin eso, nada sale de este equipo. Desde otros dispositivos la app es de solo lectura: editar afiliaciones sigue pidiendo estar en este equipo.
"""
import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(BASE, "backend")
FRONTEND = os.path.join(BASE, "frontend")
PUERTO_API, PUERTO_WEB = 8000, 3000
URL_WEB = f"http://localhost:{PUERTO_WEB}/?debug=1"   # ?debug=1: en localhost entra sin crear cuenta (solo durante la beta)
RED_LOCAL = os.environ.get("NOAIVERDAD_RED", "").strip().lower() in ("1", "true", "si", "sí", "yes") or "--red" in sys.argv[1:]
HOST = "0.0.0.0" if RED_LOCAL else "127.0.0.1"          # 0.0.0.0: escuchar en todas las interfaces (visible para la red local)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def puerto_ocupado(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def es_noaiverdad(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/", timeout=3) as r:
            return "NoAIVerdad" in json.load(r).get("sistema", "")
    except Exception:  # noqa: BLE001
        return False


def es_web_noaiverdad(puerto: int) -> bool:
    """¿Lo que atiende ese puerto es la página de NoAIVerdad (otra ventana ya abierta) y no otro programa?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/", timeout=2) as r:
            return "NoAIVerdad" in r.read(6000).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return False


def ips_de_la_red() -> list:
    """
    Direcciones IPv4 de este equipo en la red local (WiFi o cable), sin las de loopback ni las automáticas (169.254.x.x). La primera es la de la
    conexión que el sistema usa para salir a la red, que casi siempre es la que sirve desde otro dispositivo.
    """
    candidatas = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))      # UDP: no envía nada, solo averigua por qué interfaz saldría
            candidatas.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        candidatas += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    ips = []
    for ip in candidatas:
        if ip and not ip.startswith(("127.", "169.254.", "0.")) and ip not in ips:
            ips.append(ip)
    return ips


def responde_en(ip: str, puerto: int) -> bool:
    """¿Se puede abrir una conexión a esa dirección de la red (y no solo a 127.0.0.1)? Así se sabe si el servidor escucha fuera de este equipo."""
    try:
        with socket.create_connection((ip, puerto), timeout=1.5):
            return True
    except OSError:
        return False


class Manejador(http.server.SimpleHTTPRequestHandler):
    """Sirve la carpeta frontend/ sin guardar en caché (así las actualizaciones de la beta se ven al recargar)."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):  # silencia el registro de cada petición
        pass


# Avisos de Firebase que no afectan a la beta (el colector en la nube está desactivado a propósito)
RUIDO = ("firebase_store", "[Firebase collector]")


def mostrar_salida(proc) -> None:
    """Muestra la salida del servidor sin los avisos de Firebase, para no confundir al probador."""
    for linea in proc.stdout:
        if not any(r in linea for r in RUIDO):
            print("  [servidor] " + linea.rstrip(), flush=True)


def main() -> int:
    print("=" * 60)
    print("  NoAIVerdad (beta)" + ("  ·  red local" if RED_LOCAL else ""))
    print("=" * 60)

    for carpeta in (BACKEND, FRONTEND):
        if not os.path.isdir(carpeta):
            print(f"\n  Falta la carpeta {carpeta}. Vuelve a descomprimir el paquete completo.")
            return 1

    proc = None
    if puerto_ocupado(PUERTO_API):
        if es_noaiverdad(PUERTO_API):
            print("\n  El servidor de NoAIVerdad ya está en marcha en este equipo; se reutiliza.")
        else:
            print(f"\n  El puerto {PUERTO_API} está ocupado por otro programa. Ciérralo y vuelve a intentar.")
            return 1
    else:
        print("\n  Iniciando el servidor de datos...")
        env = dict(os.environ, PYTHONUTF8="1")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST, "--port", str(PUERTO_API), "--log-level", "warning"],
            cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=mostrar_salida, args=(proc,), daemon=True).start()

    if puerto_ocupado(PUERTO_WEB):
        if es_web_noaiverdad(PUERTO_WEB):
            print(f"\n  NoAIVerdad ya está abierto en otra ventana de este equipo (usa el puerto {PUERTO_WEB}).")
            print("  Cierra esa ventana y vuelve a abrir este archivo" + (" para activar la red local." if RED_LOCAL else "."))
        else:
            print(f"\n  El puerto {PUERTO_WEB} está ocupado por otro programa. Ciérralo y vuelve a intentar.")
        if proc:
            proc.terminate()
        return 1
    servidor = http.server.ThreadingHTTPServer((HOST, PUERTO_WEB), functools.partial(Manejador, directory=FRONTEND))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    # Esperar a que el backend responda
    print("  Esperando al servidor", end="", flush=True)
    listo = False
    for _ in range(90):
        if proc and proc.poll() is not None:
            print("\n\n  El servidor se cerró al arrancar. Revisa los mensajes de arriba.")
            return 1
        if es_noaiverdad(PUERTO_API):
            listo = True
            break
        print(".", end="", flush=True)
        time.sleep(1)
    print()
    if not listo:
        print("  El servidor tardó demasiado en responder.")
        if proc:
            proc.terminate()
        return 1

    # Aviso útil si Meta no responde (por ejemplo, token vencido)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO_API}/api/ads/diagnostico", timeout=60) as r:
            d = json.load(r)
        if d.get("ok"):
            print("  Datos de Meta (Biblioteca de Anuncios): conectados.")
        else:
            print("  AVISO: no se pudo consultar a Meta: " + (d.get("mensaje") or "sin detalle") + "\n         La app abrirá, pero sin anuncios nuevos.")
    except Exception:  # noqa: BLE001
        print("  (No se pudo comprobar la conexión con Meta.)")

    if RED_LOCAL:
        ips = ips_de_la_red()
        print("\n  RED LOCAL: desde otro dispositivo conectado a la misma WiFi o red, abre una de estas direcciones:")
        for ip in ips:
            print(f"      http://{ip}:{PUERTO_WEB}/?debug=1")
        if not ips:
            print("      (no se encontró la dirección de este equipo en la red: comprueba que estés conectado a la WiFi o al cable)")
        elif proc is None and not responde_en(ips[0], PUERTO_API):
            print(f"\n  AVISO: el servidor de datos ya estaba en marcha solo para este equipo y los otros dispositivos no podrán usarlo.\n"
                  f"         Ciérralo (o cierra la otra ventana de NoAIVerdad) y vuelve a abrir este archivo.")
        print("  La primera vez, Windows preguntará si permite el acceso a Python: elige «Redes privadas» y pulsa Permitir.")
        print("  Los otros dispositivos solo pueden mirar; las afiliaciones se editan desde este equipo.")
    print(f"\n  Abriendo {URL_WEB}")
    print("  Si el navegador no se abre, copia esa dirección en Chrome o Edge.")
    print("\n  Deja esta ventana abierta mientras uses NoAIVerdad.")
    print("  Para terminar, ciérrala (o pulsa Ctrl+C).\n")
    if not os.environ.get("NOAIVERDAD_NO_ABRIR"):   # para pruebas automáticas
        webbrowser.open(URL_WEB)

    try:
        while True:
            if proc and proc.poll() is not None:
                print("  El servidor se detuvo.")
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        servidor.shutdown()
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
