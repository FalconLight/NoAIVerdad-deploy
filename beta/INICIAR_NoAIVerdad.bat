@echo off
setlocal EnableExtensions
title NoAIVerdad (beta)
cd /d "%~dp0app"

echo.
echo  ==================================================
echo    NoAIVerdad (beta)
echo  ==================================================
echo.

rem --- Buscar Python 3.10 a 3.13
set "PYCMD="
for %%V in (3.13 3.12 3.11 3.10) do (
  if not defined PYCMD (
    py -%%V -c "import sys" >nul 2>nul && set "PYCMD=py -%%V"
  )
)
if not defined PYCMD (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD goto :sinpython

rem --- Primera vez: entorno propio dentro de la carpeta app
if not exist ".venv\Scripts\python.exe" (
  echo  Preparando NoAIVerdad por primera vez.
  echo  Esto tarda de 1 a 3 minutos y necesita internet. No cierres esta ventana.
  echo.
  %PYCMD% -m venv .venv
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, requests, dotenv, pydantic" >nul 2>nul
if errorlevel 1 (
  echo  Instalando componentes...
  echo.
  ".venv\Scripts\python.exe" instalar.py
  if errorlevel 1 goto :error
  echo.
)

".venv\Scripts\python.exe" launcher.py
if errorlevel 1 goto :error
exit /b 0

:sinpython
echo  No se encontro Python 3.10 a 3.13 en este equipo.
echo.
where winget >nul 2>nul
if errorlevel 1 goto :manual
choice /c SN /m "  Instalar Python 3.12 ahora con winget (necesita internet)"
if errorlevel 2 goto :manual
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo  Cuando termine, cierra esta ventana y vuelve a abrir "INICIAR NoAIVerdad.bat".
pause
exit /b 0

:manual
echo  Instala Python 3.12 desde https://www.python.org/downloads/
echo  (marca la casilla "Add python.exe to PATH" al instalar) y vuelve a abrir este archivo.
echo.
pause
exit /b 1

:error
echo.
echo  Algo fallo. Revisa los mensajes de arriba. Causas habituales:
echo    - No hay conexion a internet (la primera vez se descargan componentes).
echo    - Un antivirus o la carpeta del zip protegida: descomprime el zip completo en el escritorio.
echo    - Los puertos 8000 o 3000 estan ocupados por otro programa.
echo  Si no puedes resolverlo, toma una captura de esta ventana y enviala al equipo de NoAIVerdad.
echo.
pause
exit /b 1
