"""
Drive · el único módulo que sabe que existe la red
===================================================

`core/` no toca la red ni sabe de dónde vienen los datos. Aquí sí: esto baja el
Excel de Google Drive y lo convierte en un DataFrame crudo. Nada más.

El fichero es una **hoja nativa de Google** (`application/vnd.google-apps.spreadsheet`),
no un .xlsx subido. Dos consecuencias:

1. La URL de descarga es `/export?format=xlsx`, no `uc?export=download`.
2. Google **genera el .xlsx en cada exportación**. El zip lleva timestamps dentro,
   así que los bytes cambian aunque los datos sean idénticos.

Por (2), la huella para detectar cambios se calcula sobre **los datos parseados**,
no sobre los bytes del fichero. Si la hiciéramos sobre los bytes, el dashboard
diría «datos nuevos» cada vez que pulsaras Actualizar, y sería mentira.

Requiere que el enlace sea público («cualquiera con el enlace, lector»). Lo es,
así que no hacen falta credenciales y `docker compose up` sigue funcionando sin
configuración extra.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import time
import urllib.request

import pandas as pd

# Hoja nativa de Google. Se puede cambiar por entorno sin tocar el código.
FILE_ID = os.environ.get("VENTAS_DRIVE_ID", "1IGr-yTjfXOnlghJeaO0ymVhlKO0uP9r2HCVN5B9u2D4")
URL = os.environ.get(
    "VENTAS_DRIVE_URL",
    f"https://docs.google.com/spreadsheets/d/{FILE_ID}/export?format=xlsx",
)

# La exportación de una hoja grande puede tardar más de 30 segundos, sobre todo
# desde un runner o un contenedor recién arrancado. El timeout y los reintentos
# son configurables para no convertir una lentitud puntual de Google en un fallo.
TIMEOUT = int(os.environ.get("VENTAS_DRIVE_TIMEOUT", "120"))
REINTENTOS = int(os.environ.get("VENTAS_DRIVE_RETRIES", "3"))
ESPERA_REINTENTO = int(os.environ.get("VENTAS_DRIVE_RETRY_WAIT", "5"))

# La pestaña que escribió el notebook. Si no está, se coge la primera.
HOJA = os.environ.get("VENTAS_DRIVE_HOJA", "Pedidos")

COLUMNAS_MINIMAS = {
    "pedido_id", "fecha", "cliente", "producto",
    "cantidad", "precio_unitario", "importe",
}


class DriveNoDisponible(RuntimeError):
    """No se ha podido traer el dato de Drive. La app cae a la caché."""


class DatoIlegible(RuntimeError):
    """Ha llegado algo, pero no es la hoja de pedidos que esperamos."""


def descargar(
    url: str | None = None,
    timeout: int | None = None,
    reintentos: int | None = None,
    espera: int | None = None,
) -> bytes:
    """Baja la hoja exportada a .xlsx con reintentos ante fallos de red."""
    url = url or URL
    timeout = TIMEOUT if timeout is None else int(timeout)
    reintentos = REINTENTOS if reintentos is None else max(1, int(reintentos))
    espera = ESPERA_REINTENTO if espera is None else max(0, int(espera))

    ultimo_error: Exception | None = None

    for intento in range(1, reintentos + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ElectroPonent/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as respuesta:
                b = respuesta.read()

            # Un .xlsx es un zip: empieza por 'PK'. Si llega HTML, el enlace ha
            # dejado de ser público o el ID ya no existe. Reintentar no lo arregla.
            if b[:2] != b"PK":
                raise DriveNoDisponible(
                    "Drive no ha devuelto un .xlsx. Lo más probable: el enlace ha "
                    "dejado de ser público, o el ID del fichero ya no existe."
                )
            return b

        except DriveNoDisponible:
            raise
        except Exception as exc:  # red, DNS, 404, timeout...
            ultimo_error = exc
            if intento < reintentos:
                pausa = espera * intento
                print(
                    f"Drive no responde (intento {intento}/{reintentos}: {exc}). "
                    f"Nuevo intento en {pausa} s...",
                    file=sys.stderr,
                )
                time.sleep(pausa)

    raise DriveNoDisponible(
        f"Drive no responde tras {reintentos} intentos "
        f"(timeout {timeout} s): {ultimo_error}"
    ) from ultimo_error


def leer(b: bytes) -> pd.DataFrame:
    """Bytes de .xlsx → DataFrame CRUDO (sucio, tal cual lo rellenan)."""
    hojas = pd.read_excel(io.BytesIO(b), sheet_name=None)
    if not hojas:
        raise DatoIlegible("El fichero de Drive no tiene ninguna hoja.")

    # Preferimos la pestaña 'Pedidos'; si no está, la primera.
    df = hojas.get(HOJA)
    if df is None:
        df = next(iter(hojas.values()))

    faltan = COLUMNAS_MINIMAS - set(df.columns)
    if faltan:
        raise DatoIlegible(
            f"A la hoja de Drive le faltan columnas: {sorted(faltan)}. "
            f"Tiene: {sorted(df.columns)}"
        )
    return df


def huella_datos(df: pd.DataFrame) -> str:
    """Huella del CONTENIDO, no del fichero.

    Google regenera el .xlsx en cada exportación, así que hashear los bytes daría
    una huella distinta cada vez y todo parecería un cambio. Hasheamos los datos
    ya parseados: misma tabla → misma huella, la exporte Google cuando la exporte.
    """
    m = hashlib.sha256()
    m.update("|".join(map(str, df.columns)).encode("utf-8"))
    filas = pd.util.hash_pandas_object(df.astype(str), index=False)
    m.update(filas.values.tobytes())
    return m.hexdigest()


def obtener() -> tuple[bytes, pd.DataFrame, str]:
    """Baja, parsea y devuelve (bytes, df_crudo, huella_de_los_datos)."""
    b = descargar()
    df = leer(b)
    return b, df, huella_datos(df)
