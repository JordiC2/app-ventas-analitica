"""
Datos · el único sitio que sabe DÓNDE viven los datos
======================================================

Dos funciones, una cada una: `cargar_ventas()` y `guardar_ventas()`.

El corte entre la v1 (parquet congelado) y la v2 (Supabase vivo) es UNA sola
función. Si migrar a datos vivos te obliga a tocar algo más que esto, es que la
frontera estaba mal puesta:

    def cargar_ventas():
        return pd.read_parquet(RUTA_LIMPIO)                       # v1, congelado
        return supabase.table("ventas").select("*").execute()    # v2, vivo

`core/` es lógica pura y NO abre ficheros — salvo aquí, que es precisamente el
módulo cuyo trabajo es la persistencia. calidad.py y metricas.py no importan de
aquí; es al revés.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Carpeta de datos, configurable por entorno (Docker la sobreescribe).
DATA_DIR = Path(os.environ.get("VENTAS_DATA_DIR", "data"))
RUTA_LIMPIO = DATA_DIR / "ventas_limpio.parquet"


def cargar_ventas(ruta: str | Path | None = None) -> pd.DataFrame:
    """Devuelve el DataFrame de ventas limpio (incluye la fila señalada, marcada).

    v1: lee el parquet que dejó el pipeline. v2: cambiaría el cuerpo por una
    consulta a Supabase, y nada más.
    """
    ruta = Path(ruta) if ruta is not None else RUTA_LIMPIO
    df = pd.read_parquet(ruta)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def guardar_ventas(df: pd.DataFrame, ruta: str | Path | None = None) -> Path:
    """Persiste el DataFrame limpio en parquet. Devuelve la ruta escrita."""
    ruta = Path(ruta) if ruta is not None else RUTA_LIMPIO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ruta, index=False)
    return ruta
