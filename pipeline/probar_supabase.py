"""Prueba mínima de conexión con Supabase.

Lee la fila de control `ventas` de public.sync_state usando las variables:

    SUPABASE_URL
    SUPABASE_SECRET_KEY

No modifica datos. Sirve para validar URL, clave, permisos y conectividad antes de
subir las ventas.
"""

from __future__ import annotations

import os
import sys

from supabase import Client, create_client


def _variable_obligatoria(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta la variable {nombre}. Añádela al archivo .env y vuelve a probar."
        )
    return valor


def main() -> None:
    url = _variable_obligatoria("SUPABASE_URL")
    secret_key = _variable_obligatoria("SUPABASE_SECRET_KEY")

    cliente: Client = create_client(url, secret_key)
    respuesta = (
        cliente.table("sync_state")
        .select("dataset_key,ultimo_estado,version_puerta,filas_crudas,filas_limpias")
        .eq("dataset_key", "ventas")
        .limit(1)
        .execute()
    )

    if not respuesta.data:
        raise RuntimeError(
            "La conexión funciona, pero no existe la fila dataset_key='ventas' "
            "en public.sync_state. Revisa la migración inicial."
        )

    estado = respuesta.data[0]
    print("Conexión con Supabase correcta.")
    print(f"Dataset       : {estado['dataset_key']}")
    print(f"Último estado : {estado['ultimo_estado']}")
    print(f"Versión puerta: {estado.get('version_puerta')}")
    print(f"Filas crudas  : {estado.get('filas_crudas')}")
    print(f"Filas limpias : {estado.get('filas_limpias')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
