# -*- coding: utf-8 -*-
"""Instala los componentes de NoAIVerdad mostrando una barra de progreso.

Lo ejecuta «INICIAR NoAIVerdad.bat» con el Python de app/.venv, solo la primera vez (o si falta algún componente).
Solo usa la biblioteca estándar. Llama a «pip install» y avanza la barra según los paquetes que pip va resolviendo
e instalando; si pip falla, muestra su salida completa y devuelve un código distinto de cero.
"""
import os
import re
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
REQ = os.path.join(AQUI, "backend", "requirements.txt")
ANCHO = 30


def contar_requisitos() -> int:
    try:
        with open(REQ, encoding="utf-8") as f:
            return max(1, sum(1 for l in f if l.strip() and not l.lstrip().startswith("#")))
    except OSError:
        return 30


def barra(frac: float, texto: str, inicio: float) -> None:
    frac = max(0.0, min(1.0, frac))
    llenos = int(round(frac * ANCHO))
    b = "█" * llenos + "░" * (ANCHO - llenos)
    t = int(time.time() - inicio)
    linea = f"  [{b}] {int(frac * 100):3d}%  {texto[:34]:<34} {t // 60}:{t % 60:02d}"
    sys.stdout.write("\r" + linea)
    sys.stdout.flush()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    total = contar_requisitos()
    inicio = time.time()
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off",
           "-r", REQ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env=env)
    salida, vistos, fase, frac = [], 0, "Buscando componentes", 0.0
    barra(0.0, fase, inicio)
    for linea in proc.stdout:
        salida.append(linea)
        m = re.match(r"\s*Collecting\s+([A-Za-z0-9_.\-]+)", linea)
        if m:
            vistos += 1
            fase = "Descargando " + m.group(1)
            # Las dependencias indirectas hacen que no se sepa el total: la barra se acerca al 85 % sin pasarlo.
            frac = max(frac, 0.85 * vistos / (vistos + total * 0.4))
        elif linea.startswith("Installing collected packages"):
            fase, frac = "Instalando (casi listo)", max(frac, 0.9)
        barra(frac, fase, inicio)
    codigo = proc.wait()
    if codigo != 0:
        sys.stdout.write("\n\n" + "".join(salida) + "\n")
        return codigo
    barra(1.0, "Listo", inicio)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
