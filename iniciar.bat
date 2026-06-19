@echo off
title Ad-Spy
cd /d "%~dp0"
echo Iniciando Ad-Spy en http://localhost:8000 ...
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo.
echo El servidor se detuvo. Cierra esta ventana.
pause
