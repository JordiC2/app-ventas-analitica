@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Electro Ponent - Actualizar

echo.
echo  ELECTRO PONENT - Actualizar
echo  ===========================
echo.
echo  NOTA: para actualizar solo los DATOS no hace falta esto.
echo        Pulsa "Actualizar dashboard" en la propia pantalla: vuelve a mirar
echo        Drive al momento y sin reiniciar nada.
echo.
echo  Este fichero es para:
echo    - reconstruir despues de tocar codigo (core, api, static...)
echo    - forzar una relectura completa de Drive desde cero
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker no responde. Abre Docker Desktop y repite.
  echo.
  pause
  exit /b 1
)

rem --- Cifra anterior, para comparar despues -------------------------------
set ANTES=
for /f "delims=" %%v in ('powershell -NoProfile -Command "try{(Invoke-RestMethod -TimeoutSec 3 http://localhost:8000/api/estado).fact_limpio}catch{}" 2^>nul') do set ANTES=%%v

echo  Reconstruyendo: Drive -^> puerta de calidad -^> pytest -^> API
echo.

docker compose up -d --build --force-recreate
if errorlevel 1 (
  echo.
  echo  [ERROR] Fallo al reconstruir el contenedor.
  echo.
  pause
  exit /b 1
)

echo.
echo  Esperando a que la API responda...

set n=0
:espera
set /a n+=1

docker compose ps -q --status=running dashboard > "%TEMP%\ep_run.txt" 2>nul
for %%A in ("%TEMP%\ep_run.txt") do if %%~zA EQU 0 goto caido

curl -s -o nul -m 2 http://localhost:8000/api/calidad
if not errorlevel 1 goto listo

if %n% GEQ 45 goto lento
timeout /t 2 /nobreak >nul
goto espera

rem ---------------------------------------------------------------- OK
:listo
del "%TEMP%\ep_run.txt" >nul 2>&1
echo.
echo  ------------------------- DE DONDE SALEN LOS DATOS -------------------------
powershell -NoProfile -Command ^
  "$e = Invoke-RestMethod http://localhost:8000/api/estado;" ^
  "$o = @{drive='Google Drive'; cache='CACHE (Drive no responde)'; referencia='REFERENCIA del notebook (Drive no responde)'};" ^
  "'{0,-24}{1}' -f 'Origen', $o[$e.origen];" ^
  "'{0,-24}{1}' -f 'Dato de', $e.dato_de"
echo.
echo  ---------------------------- LA PUERTA DE CALIDAD ---------------------------
powershell -NoProfile -Command ^
  "$q = Invoke-RestMethod http://localhost:8000/api/calidad;" ^
  "'{0,-24}{1,14:N0}' -f 'Filas en la hoja', $q.crudas;" ^
  "'{0,-24}{1,14:N0}' -f 'Filas analizadas', $q.limpias;" ^
  "'{0,-24}{1,14:N0} EUR' -f 'Facturacion cruda', $q.fact_crudo;" ^
  "'{0,-24}{1,14:N0} EUR' -f 'Facturacion real', $q.fact_limpio;" ^
  "'{0,-24}{1,14:N0} EUR' -f 'Diferencia', ($q.fact_crudo - $q.fact_limpio);" ^
  "'';" ^
  "'Incidencias:';" ^
  "$q.incidencias | ForEach-Object { '  {0,-45}{1,5}  {2}' -f $_.regla, $_.filas, $_.accion }"
echo  ----------------------------------------------------------------------------
echo.

if defined ANTES (
  echo  Facturacion antes de actualizar: %ANTES% EUR
  echo.
)

echo  ACTUALIZADO - http://localhost:8000
echo.
choice /c SN /n /m "  Abrir el dashboard? [S/N] "
if errorlevel 2 goto fin
start "" http://localhost:8000
:fin
echo.
exit /b 0

rem ---------------------------------------------------------------- Tests KO
:caido
del "%TEMP%\ep_run.txt" >nul 2>&1
echo.
echo  ============================================
echo   LA APP NO HA LEVANTADO
echo  ============================================
echo.
echo  Un chequeo ha fallado con los datos de Drive, y por eso la API no ha
echo  arrancado. El dato nuevo incumple alguna regla del negocio.
echo  Mira que chequeo ha reventado:
echo.
echo  ---------------------------- ultimos logs ----------------------------
docker compose logs --tail 45
echo  ----------------------------------------------------------------------
echo.
pause
exit /b 1

rem ---------------------------------------------------------------- Timeout
:lento
del "%TEMP%\ep_run.txt" >nul 2>&1
echo.
echo  [AVISO] La API tarda mas de lo normal. Ultimos logs:
echo.
docker compose logs --tail 25
echo.
pause
exit /b 1
