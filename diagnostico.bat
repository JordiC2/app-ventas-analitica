@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Electro Ponent - Diagnostico

echo.
echo  ELECTRO PONENT - Diagnostico
echo  ============================
echo.
echo  "He añadido un pedido y no lo veo en la app."
echo.
echo  Esto baja la hoja de Drive tal cual y le pregunta a la puerta de calidad
echo  que ha hecho con cada fila, y por que.
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker no responde. Abre Docker Desktop y repite.
  echo.
  pause
  exit /b 1
)

docker compose ps -q --status=running dashboard > "%TEMP%\ep_diag.txt" 2>nul
for %%A in ("%TEMP%\ep_diag.txt") do if %%~zA EQU 0 goto sinapp
del "%TEMP%\ep_diag.txt" >nul 2>&1

echo  Numero de pedido a investigar (deja vacio para ver las 15 mas nuevas):
set "PEDIDO="
set /p PEDIDO=^>
echo.

if "%PEDIDO%"=="" (
  docker compose exec -T dashboard python -m pipeline.diagnostico
) else (
  docker compose exec -T dashboard python -m pipeline.diagnostico %PEDIDO%
)

echo.
echo  ----------------------------------------------------------------------
echo  Si tu pedido pone DESCARTADA, el motivo esta ahi arriba. Corrigelo en la
echo  hoja de Drive y pulsa "Actualizar dashboard" en la app.
echo.
pause
exit /b 0

:sinapp
del "%TEMP%\ep_diag.txt" >nul 2>&1
echo  [ERROR] La app no esta arrancada. Ejecuta antes arrancar.bat
echo.
pause
exit /b 1
