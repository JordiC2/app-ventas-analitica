# Paso 1 · Preparar la app para GitHub

## 1. Crear la configuración local

Duplica `.env.example` y renómbralo como `.env`.

En Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

En macOS o Linux:

```bash
cp .env.example .env
```

Completa como mínimo:

- `VENTAS_DRIVE_ID`
- `VENTAS_FORM_URL`

El archivo `.env` está ignorado por Git y no se subirá a GitHub.

## 2. Arrancar y validar

```bash
docker compose up --build
```

El contenedor ejecuta, en este orden:

1. Descarga e ingesta de Google Sheets.
2. Tests automáticos.
3. Arranque de FastAPI.

La API solo se publica si la ingesta y los tests terminan correctamente.

Abre:

- Dashboard: http://localhost:8000
- Estado: http://localhost:8000/api/estado
- Documentación API: http://localhost:8000/docs

## 3. Detener

```bash
docker compose down
```

## 4. Crear el repositorio

```bash
git init
git add .
git commit -m "Preparar app de ventas para despliegue"
```

Después crea un repositorio vacío en GitHub y sigue las instrucciones que muestra GitHub para conectar y hacer `git push`.

## Qué no debe subirse

- `.env`
- caché descargada de Google Drive
- Parquet generado
- manifiestos e informes generados
- carpetas de caché de Python y pytest

El fichero `data/referencia/ventas_electro.xlsx` sí se conserva porque es el fixture de los tests de regresión.
