"""Sincroniza Google Sheets con Supabase de forma segura.

Flujo:
1. Descarga la hoja desde Google Drive.
2. Calcula la huella del contenido.
3. Aplica la puerta de calidad de ``core.calidad``.
4. Carga datos crudos y limpios en tablas staging, por lotes.
5. Publica ambas tablas en una única transacción mediante ``publicar_sync``.
6. Registra el resultado en ``calidad_runs`` y ``sync_state``.

La app local con Parquet sigue funcionando igual. Este módulo es un proceso aparte
para la copia pública alojada en Supabase.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from core.calidad import VERSION_PUERTA, limpiar
from pipeline import drive

DATASET_KEY = "ventas"
TAMANO_LOTE = 500

COLUMNAS_RAW = (
    "pedido_id",
    "fecha",
    "comercial",
    "zona",
    "cliente",
    "tipo_cliente",
    "producto",
    "familia",
    "cantidad",
    "precio_unitario",
    "importe",
)

COLUMNAS_CLEAN = (
    "pedido_id",
    "fecha",
    "comercial",
    "zona",
    "cliente",
    "tipo_cliente",
    "producto",
    "familia",
    "cantidad",
    "precio_unitario",
    "importe",
    "fila_origen",
    "es_devolucion",
    "sospechoso",
)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _variable_obligatoria(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta la variable {nombre}. Añádela al archivo .env y vuelve a probar."
        )
    return valor


def _crear_cliente():
    from supabase import create_client

    return create_client(
        _variable_obligatoria("SUPABASE_URL"),
        _variable_obligatoria("SUPABASE_SECRET_KEY"),
    )


def _es_nulo(valor: Any) -> bool:
    try:
        resultado = pd.isna(valor)
        return bool(resultado) if not hasattr(resultado, "__len__") else False
    except (TypeError, ValueError):
        return False


def _json_valor(valor: Any) -> Any:
    """Convierte escalares de pandas/numpy en valores serializables como JSON."""
    if _es_nulo(valor):
        return None
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.isoformat()
    if hasattr(valor, "item"):
        try:
            return valor.item()
        except (ValueError, TypeError):
            pass
    return valor


def _texto(valor: Any) -> str | None:
    valor = _json_valor(valor)
    return None if valor is None else str(valor)


def _numero(valor: Any) -> int | float:
    valor = _json_valor(valor)
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"Se esperaba un número y llegó {valor!r}")
    if isinstance(valor, int):
        return valor
    return float(valor)


def _con_fila_origen(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "fila_origen" not in d.columns:
        d.insert(0, "fila_origen", range(len(d)))
    return d


def preparar_raw(df_crudo: pd.DataFrame, sync_id: str) -> list[dict[str, Any]]:
    d = _con_fila_origen(df_crudo)
    registros: list[dict[str, Any]] = []

    for fila in d.to_dict(orient="records"):
        payload = {
            str(clave): _json_valor(valor)
            for clave, valor in fila.items()
            if clave != "fila_origen"
        }

        registro: dict[str, Any] = {
            "sync_id": sync_id,
            "fila_origen": int(fila["fila_origen"]),
            "raw_payload": payload,
        }
        for columna in COLUMNAS_RAW:
            registro[columna] = _texto(fila.get(columna))
        registros.append(registro)

    return registros


def preparar_clean(df_limpio: pd.DataFrame, sync_id: str) -> list[dict[str, Any]]:
    faltan = set(COLUMNAS_CLEAN) - set(df_limpio.columns)
    if faltan:
        raise RuntimeError(
            f"Al dato limpio le faltan columnas necesarias: {sorted(faltan)}"
        )

    registros: list[dict[str, Any]] = []
    for fila in df_limpio.to_dict(orient="records"):
        registros.append(
            {
                "sync_id": sync_id,
                "pedido_id": str(fila["pedido_id"]),
                "fecha": pd.Timestamp(fila["fecha"]).date().isoformat(),
                "comercial": _texto(fila["comercial"]) or "(sin informar)",
                "zona": _texto(fila["zona"]),
                "cliente": str(fila["cliente"]),
                "tipo_cliente": _texto(fila["tipo_cliente"]) or "(sin informar)",
                "producto": str(fila["producto"]),
                "familia": _texto(fila["familia"]) or "(sin informar)",
                "cantidad": _numero(fila["cantidad"]),
                "precio_unitario": float(_numero(fila["precio_unitario"])),
                "importe": float(_numero(fila["importe"])),
                "fila_origen": int(_numero(fila["fila_origen"])),
                "es_devolucion": bool(fila["es_devolucion"]),
                "sospechoso": bool(fila["sospechoso"]),
            }
        )
    return registros


def _lotes(registros: list[dict[str, Any]], tamano: int = TAMANO_LOTE):
    for inicio in range(0, len(registros), tamano):
        yield registros[inicio : inicio + tamano]


def _insertar_lotes(cliente, tabla: str, registros: list[dict[str, Any]]) -> None:
    total = len(registros)
    for numero, lote in enumerate(_lotes(registros), start=1):
        cliente.table(tabla).insert(lote).execute()
        cargadas = min(numero * TAMANO_LOTE, total)
        print(f"  {tabla}: {cargadas:,}/{total:,} filas")


def _estado_actual(cliente) -> dict[str, Any]:
    respuesta = (
        cliente.table("sync_state")
        .select(
            "dataset_key,ultima_huella,ultimo_estado,version_puerta,"
            "filas_crudas,filas_limpias"
        )
        .eq("dataset_key", DATASET_KEY)
        .limit(1)
        .execute()
    )
    if not respuesta.data:
        raise RuntimeError(
            "No existe dataset_key='ventas' en sync_state. "
            "Ejecuta la migración inicial de Supabase."
        )
    return respuesta.data[0]


def _actualizar_estado(cliente, valores: dict[str, Any]) -> None:
    (
        cliente.table("sync_state")
        .update(valores)
        .eq("dataset_key", DATASET_KEY)
        .execute()
    )


def _resumen(df_crudo: pd.DataFrame, df_limpio: pd.DataFrame) -> dict[str, Any]:
    base = (
        df_limpio[~df_limpio["sospechoso"]]
        if "sospechoso" in df_limpio.columns
        else df_limpio
    )
    importe_crudo = pd.to_numeric(df_crudo["importe"], errors="coerce").sum()

    return {
        "filas_crudas": int(len(df_crudo)),
        # Mantiene la definición de la app actual: el señalado no entra en KPI.
        "filas_limpias": int(len(base)),
        "filas_publicadas": int(len(df_limpio)),
        "facturacion_cruda": round(float(importe_crudo), 2),
        "facturacion_limpia": round(float(base["importe"].sum()), 2),
    }


def sincronizar(*, forzar: bool = False, origen: str = "manual") -> dict[str, Any]:
    cliente = _crear_cliente()
    sync_id = str(uuid.uuid4())
    run_registrado = False

    try:
        cliente.table("calidad_runs").insert(
            {
                "id": sync_id,
                "origen": origen,
                "estado": "running",
                "version_puerta": VERSION_PUERTA,
                "mensaje": "Sincronización iniciada.",
            }
        ).execute()
        run_registrado = True

        # Leemos el estado anterior ANTES de marcar esta ejecución como running.
        # Así no perdemos si el último resultado real fue ok, unchanged o error.
        estado_anterior = _estado_actual(cliente)

        _actualizar_estado(
            cliente,
            {
                "ultima_ejecucion_id": sync_id,
                "ultima_comprobacion": _ahora(),
                "ultimo_estado": "running",
                "ultimo_error": None,
                "version_puerta": VERSION_PUERTA,
            },
        )

        print("Descargando Google Sheets...")
        _, df_crudo_original, huella = drive.obtener()
        df_crudo = _con_fila_origen(df_crudo_original)

        intacto = (
            estado_anterior.get("ultima_huella") == huella
            and estado_anterior.get("version_puerta") == VERSION_PUERTA
            and estado_anterior.get("ultimo_estado") in {"ok", "unchanged"}
            and estado_anterior.get("filas_limpias") is not None
        )

        if intacto and not forzar:
            mensaje = "Sin cambios: la huella y la versión de la puerta coinciden."
            terminado = _ahora()

            cliente.table("calidad_runs").update(
                {
                    "finished_at": terminado,
                    "huella": huella,
                    "filas_crudas": estado_anterior.get("filas_crudas") or 0,
                    "filas_limpias": estado_anterior.get("filas_limpias") or 0,
                    "estado": "unchanged",
                    "mensaje": mensaje,
                }
            ).eq("id", sync_id).execute()

            _actualizar_estado(
                cliente,
                {
                    "ultima_ejecucion_id": sync_id,
                    "ultima_comprobacion": terminado,
                    "ultimo_estado": "unchanged",
                    "ultimo_error": None,
                    "version_puerta": VERSION_PUERTA,
                },
            )

            print(mensaje)
            return {
                "sync_id": sync_id,
                "estado": "unchanged",
                "huella": huella,
            }

        print("Aplicando la puerta de calidad...")
        df_limpio, incidencias = limpiar(df_crudo)
        resumen = _resumen(df_crudo, df_limpio)

        cliente.table("calidad_runs").update(
            {
                "huella": huella,
                "filas_crudas": resumen["filas_crudas"],
                "filas_limpias": resumen["filas_limpias"],
                "facturacion_cruda": resumen["facturacion_cruda"],
                "facturacion_limpia": resumen["facturacion_limpia"],
                "incidencias": incidencias,
                "mensaje": "Puerta de calidad superada; preparando publicación.",
            }
        ).eq("id", sync_id).execute()

        print("Preparando registros...")
        raw = preparar_raw(df_crudo, sync_id)
        clean = preparar_clean(df_limpio, sync_id)

        print("Cargando tablas temporales...")
        _insertar_lotes(cliente, "ventas_raw_staging", raw)
        _insertar_lotes(cliente, "ventas_clean_staging", clean)

        print("Publicando el dataset de forma atómica...")
        cliente.rpc("publicar_sync", {"p_sync_id": sync_id}).execute()

        terminado = _ahora()
        mensaje = (
            f"Sincronización completada: {resumen['filas_crudas']:,} filas crudas, "
            f"{resumen['filas_publicadas']:,} filas publicadas y "
            f"{resumen['filas_limpias']:,} incluidas en KPI."
        )

        cliente.table("calidad_runs").update(
            {
                "finished_at": terminado,
                "estado": "ok",
                "mensaje": mensaje,
            }
        ).eq("id", sync_id).execute()

        _actualizar_estado(
            cliente,
            {
                "ultima_huella": huella,
                "ultima_ejecucion_id": sync_id,
                "ultima_sincronizacion": terminado,
                "ultima_comprobacion": terminado,
                "ultimo_estado": "ok",
                "ultimo_error": None,
                "version_puerta": VERSION_PUERTA,
                "filas_crudas": resumen["filas_crudas"],
                "filas_limpias": resumen["filas_limpias"],
            },
        )

        print(mensaje)
        return {
            "sync_id": sync_id,
            "estado": "ok",
            "huella": huella,
            **resumen,
        }

    except Exception as exc:
        mensaje_error = f"{type(exc).__name__}: {exc}"
        terminado = _ahora()

        # No deben quedar filas staging de una carga fallida.
        for tabla in ("ventas_raw_staging", "ventas_clean_staging"):
            try:
                cliente.table(tabla).delete().eq("sync_id", sync_id).execute()
            except Exception:
                pass

        if run_registrado:
            try:
                cliente.table("calidad_runs").update(
                    {
                        "finished_at": terminado,
                        "estado": "error",
                        "mensaje": mensaje_error,
                    }
                ).eq("id", sync_id).execute()
            except Exception:
                pass

        try:
            _actualizar_estado(
                cliente,
                {
                    "ultima_ejecucion_id": sync_id,
                    "ultima_comprobacion": terminado,
                    "ultimo_estado": "error",
                    "ultimo_error": mensaje_error[:2000],
                    "version_puerta": VERSION_PUERTA,
                },
            )
        except Exception:
            pass

        raise RuntimeError(
            f"La sincronización ha fallado. Supabase conserva el dataset anterior. "
            f"Detalle: {mensaje_error}"
        ) from exc


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga Google Sheets, limpia y publica las ventas en Supabase."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocesa y publica aunque la huella no haya cambiado.",
    )
    parser.add_argument(
        "--origen",
        default="manual",
        choices=("manual", "github_actions", "apps_script", "docker"),
        help="Origen que se guardará en calidad_runs.",
    )
    return parser.parse_args()


def main() -> None:
    args = _argumentos()
    resultado = sincronizar(forzar=args.force, origen=args.origen)
    print(f"Sync ID: {resultado['sync_id']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
