@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Electro Ponent - Parar

echo.
echo  ELECTRO PONENT - Parar
echo  ======================
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo  Docker no responde, asi que la app ya no esta corriendo.
  echo.
  pause
  exit /b 0
)

echo  Parando el contenedor...
echo.

docker compose down
if errorlevel 1 (
  echo.
  echo  [ERROR] No se ha podido parar limpiamente.
  echo.
  pause
  exit /b 1
)

echo.
echo  PARADO. El puerto 8000 queda libre.
echo.
echo  Tus datos NO se han tocado: data\ventas_electro.xlsx sigue donde estaba,
echo  y el parquet se regenera solo en el proximo arranque.
echo.
echo  Volver a arrancar: arrancar.bat
echo.
pause
exit /b 0
