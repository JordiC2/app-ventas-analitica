"""Crea un usuario confirmado en Supabase Auth para acceder al dashboard privado.

El email y la contraseña se piden de forma interactiva y no se guardan en archivos.
Requiere SUPABASE_URL y SUPABASE_SECRET_KEY en el entorno.
"""

from __future__ import annotations

import getpass
import os
import sys

from supabase import create_client


def _variable_obligatoria(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta la variable {nombre}. Añádela al archivo .env y vuelve a probar."
        )
    return valor


def main() -> None:
    email = input("Email del usuario: ").strip().lower()
    if "@" not in email:
        raise ValueError("El email no parece válido.")

    nombre = input("Nombre visible [Administrador]: ").strip() or "Administrador"
    password = getpass.getpass("Contraseña: ")
    password_2 = getpass.getpass("Repite la contraseña: ")

    if password != password_2:
        raise ValueError("Las contraseñas no coinciden.")
    if len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")

    cliente = create_client(
        _variable_obligatoria("SUPABASE_URL"),
        _variable_obligatoria("SUPABASE_SECRET_KEY"),
    )

    respuesta = cliente.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"nombre": nombre},
        }
    )

    usuario = respuesta.user
    print("Usuario creado y confirmado correctamente.")
    print(f"Email : {usuario.email}")
    print(f"ID    : {usuario.id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
