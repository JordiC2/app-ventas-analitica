"""
API · FastAPI
==============

Lee /data, llama a /core para calcular, y sirve /static.

Endpoints:

  GET  /                                    → sirve static/index.html
  GET  /nuevo                               → alta de venta (formulario de Drive)
  GET  /api/payload                         → todo lo que el dashboard necesita hoy
  GET  /api/calidad                         → el informe de la puerta de calidad
  GET  /api/kpi?desde=YYYY-MM-DD&hasta=...  → KPIs RECALCULADOS para esa ventana
  GET  /api/ventas?limite=&offset=&q=...    → el explorador: las últimas ventas
  GET  /api/estado                          → de dónde salen los datos y de cuándo son
  POST /api/actualizar                      → vuelve a mirar Drive y recarga si hay dato nuevo

`/api/kpi` demuestra que los KPI no están guardados: cambias las fechas y cambian
los números. Imposible con el HTML congelado.

`/api/actualizar` es el botón del dashboard. Baja la hoja de Drive, compara la
huella de los DATOS con la que ya teníamos, y solo reprocesa si de verdad cambió.
Si no cambió, lo dice y no toca nada.

La API no limpia datos: eso lo hace el pipeline. Aquí se carga el dataset limpio
en memoria y se calcula al vuelo sobre él en cada petición.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import datos, metricas
from pipeline import ingesta

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

app = FastAPI(title="Electro Ponent · Cuadro de mando comercial")

# El formulario de alta (web app de Google Apps Script). Va por entorno para que
# cambiar de formulario no obligue a tocar ni el HTML ni el código.
FORM_URL = os.environ.get("VENTAS_FORM_URL", "").strip()

# Dataset limpio en memoria. Son ~10.000 filas: cabe de sobra.
_DF = None


def _df():
    """Carga perezosa y cacheada del dataset limpio."""
    global _DF
    if _DF is None:
        if not datos.RUTA_LIMPIO.exists():
            raise HTTPException(
                503,
                "No hay datos cargados: falta ejecutar el pipeline "
                "(python -m pipeline.ingesta)",
            )
        _DF = datos.cargar_ventas()
    return _DF


def _recargar():
    """Tira el dataset en memoria para que la próxima petición lea el nuevo."""
    global _DF
    _DF = None


@app.get("/")
def index():
    """El dashboard. Ya no lleva los datos dentro: los pide con fetch()."""
    return FileResponse(STATIC / "index.html")


@app.get("/nuevo")
def nuevo():
    """La página de alta: el formulario de Drive, embebido.

    El alta NO la hace esta app: la hace el formulario, que escribe en la hoja de
    Google. Aquí solo se enmarca y se ofrece el botón de actualizar, porque
    guardar en Drive y no volver a mirar es quedarse a medias — el pedido estaría
    en la hoja pero no en la pantalla.

    Y hay una razón de fondo para no montar el alta aquí: si esta app escribiera
    en la hoja, dejaría de ser un lector y se convertiría en la segunda fuente de
    verdad. La hoja es de los comerciales; nosotros la leemos y la juzgamos.
    """
    return FileResponse(STATIC / "nuevo.html")


@app.get("/api/payload")
def api_payload():
    """Agregados que el navegador no puede recalcular por su cuenta."""
    return JSONResponse(metricas.payload(_df()))


@app.get("/api/calidad")
def api_calidad():
    """El acta de la puerta: qué llevaba el Excel y qué se hizo con cada cosa.

    Las incidencias son parte de la respuesta, no un log: la puerta las devolvió
    al limpiar, el pipeline las guardó, y aquí se sirven tal cual.
    """
    if not ingesta.RUTA_CALIDAD.exists():
        raise HTTPException(
            503, "Informe de calidad no disponible: falta ejecutar el pipeline"
        )
    return JSONResponse(json.loads(ingesta.RUTA_CALIDAD.read_text(encoding="utf-8")))


@app.get("/api/kpi")
def api_kpi(
    desde: str | None = Query(None, description="Inicio de ventana, YYYY-MM-DD"),
    hasta: str | None = Query(None, description="Fin de ventana, YYYY-MM-DD"),
):
    """KPIs recalculados para la ventana pedida. Cambia las fechas → cambian los números."""
    try:
        return JSONResponse(metricas.kpis(_df(), desde=desde, hasta=hasta))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Fechas inválidas: {e}")


@app.get("/api/ventas")
def api_ventas(
    limite: int = Query(25, ge=1, le=200, description="Filas por página (máx. 200)"),
    offset: int = Query(0, ge=0, description="Desde qué fila"),
    q: str | None = Query(None, description="Busca en cliente, producto, pedido y comercial"),
    comercial: str | None = Query(None, description="Filtra por comercial exacto"),
    desde: str | None = Query(None, description="Fecha mínima, YYYY-MM-DD"),
    hasta: str | None = Query(None, description="Fecha máxima, YYYY-MM-DD"),
    marca: str | None = Query(None, description="senalados | devoluciones | sin_senalados"),
    orden: str = Query("fecha", description="fecha | registro"),
):
    """El explorador: las últimas ventas registradas, paginadas.

    `marca=senalados` deja el pedido anómalo a un clic: los KPI lo excluyen,
    y esta es la pantalla donde un humano lo mira y decide.

    Va paginado a propósito. Meter las ~10.000 filas en /api/payload sería
    volver justo a lo que quitamos: un payload gordo y congelado. Aquí se sirven
    de 25 en 25, ordenadas por fecha descendente, y se filtran en el servidor.

    Los pedidos señalados salen por defecto, marcados. Esta es la pantalla donde
    un humano los mira.
    """
    try:
        return JSONResponse(metricas.ventas(
            _df(), limite=limite, offset=offset, q=q, comercial=comercial,
            desde=desde, hasta=hasta, marca=marca, orden=orden,
        ))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Parámetros inválidos: {e}")


@app.get("/api/estado")
def api_estado():
    """De dónde salen los datos que estás viendo, y de cuándo son.

    No toca la red: solo lee el manifiesto que dejó la última ingesta. El
    dashboard lo usa para avisar cuando está sirviendo caché en vez de Drive.
    """
    est = ingesta.estado()
    est["form_url"] = FORM_URL or None      # la página de alta lo lee de aquí
    return JSONResponse(est)


@app.post("/api/actualizar")
def api_actualizar(
    forzar: bool = Query(False, description="Reprocesa aunque no haya cambios"),
):
    """Vuelve a mirar Drive. Si hay dato nuevo, lo pasa por la puerta y recarga.

    Este es el botón «Actualizar dashboard». Devuelve el informe: si hubo cambio,
    de qué origen viene el dato, y el delta contra lo que había antes.
    """
    try:
        informe = ingesta.ejecutar(forzar=forzar)
    except Exception as e:
        raise HTTPException(503, f"No se ha podido actualizar: {e}")
    if informe["cambio"]:
        _recargar()
    return JSONResponse(informe)


# /static por si el HTML pide algún recurso adicional en el futuro.
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
