@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Electro Ponent - Arrancar

echo.
echo  ELECTRO PONENT - Cuadro de mando comercial
echo  ==========================================
echo.

rem ---------------------------------------------------------------- Docker vivo?
docker version >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker no responde.
  echo.
  echo  Abre Docker Desktop, espera a que ponga "Engine running",
  echo  y vuelve a ejecutar este fichero.
  echo.
  pause
  exit /b 1
)

echo  Arrancando en este orden:
echo    1. ingesta  - el Excel sucio pasa por la puerta de calidad
echo    2. pytest   - los chequeos del notebook
echo    3. API      - solo si los chequeos pasan
echo.
echo  Si un chequeo falla, la API NO levanta. Es a proposito.
echo.
echo  La primera vez tarda un par de minutos (construye la imagen).
echo.

docker compose up -d --build
if errorlevel 1 (
  echo.
  echo  [ERROR] No se ha podido construir o arrancar el contenedor.
  echo.
  pause
  exit /b 1
)

echo.
echo  Esperando a que la API responda...

set n=0
:espera
set /a n+=1

rem ¿Sigue vivo el contenedor? Si los tests fallaron, se habra parado.
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
echo  ============================================
echo   LISTO - Dashboard en http://localhost:8000
echo  ============================================
echo.
start "" http://localhost:8000
echo  Ver los logs en vivo : docker compose logs -f
echo  Actualizar los datos : actualizar.bat
echo  Parar                : parar.bat
echo.
pause
exit /b 0

rem ---------------------------------------------------------------- Tests KO
:caido
del "%TEMP%\ep_run.txt" >nul 2>&1
echo.
echo  ============================================
echo   LA APP NO HA LEVANTADO
echo  ============================================
echo.
echo  El contenedor se ha parado. Lo mas probable: un chequeo ha fallado,
echo  y por eso la API no ha arrancado. Esto es el comportamiento correcto:
echo  un pipeline que no se puede verificar no se despliega.
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
echo  [AVISO] La API tarda mas de lo normal en responder. Ultimos logs:
echo.
docker compose logs --tail 25
echo.
echo  Prueba a abrir http://localhost:8000 a mano.
echo.
pause
exit /b 1
