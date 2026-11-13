@echo off
rem Igual que "INICIAR NoAIVerdad.bat", pero deja la app disponible para otros dispositivos conectados a la misma WiFi o red
rem (el celular, la tablet, otra computadora). La ventana muestra las direcciones para abrirla desde ellos.
rem La primera vez Windows pregunta si permite el acceso a Python: elige "Redes privadas" y pulsa Permitir.
set "NOAIVERDAD_RED=1"
call "%~dp0INICIAR NoAIVerdad.bat"
