"""
Diagnóstico · «he añadido un pedido y no lo veo en la app»
===========================================================

Baja la hoja de Google Drive TAL CUAL y le pide su veredicto a la puerta de
calidad, fila a fila. Sin tocar nada, sin guardar nada.

    python -m pipeline.diagnostico              # las 15 filas más nuevas de la hoja
    python -m pipeline.diagnostico P2034999     # ese pedido concreto
    python -m pipeline.diagnostico --caidas     # solo lo que la puerta descarta

Las incidencias del dashboard dicen CUÁNTAS filas cayó cada regla. Esto dice
CUÁLES, y por qué. Es la diferencia entre «se descartaron 53 filas» y «tu fila
P2034999 se cayó porque 10 x 11,20 son 112,00 y tú escribiste 112,50».
"""

from __future__ import annotations

import sys

import pandas as pd

from core.calidad import PASA, diagnosticar, hoy_por_defecto
from pipeline import drive

ANCHO = 100


def _cabecera(hoy: pd.Timestamp, total: int) -> None:
    print()
    print("DIAGNÓSTICO DE LA HOJA DE DRIVE")
    print("=" * ANCHO)
    print(f"Hoja      : {drive.FILE_ID}")
    print(f"Filas     : {total:,}")
    print(f"Fecha tope: {hoy.date()}  (todo pedido posterior se descarta)")
    print("=" * ANCHO)


def _pinta(d: pd.DataFrame) -> None:
    for r in d.itertuples():
        f = pd.Timestamp(r.fecha)
        fecha = "(vacía)" if pd.isna(f) else str(f.date())
        ok = r.veredicto == PASA
        print()
        print(f"  {'✓' if ok else '✗'} {r.pedido_id}   {fecha}   {r.cliente}")
        print(f"      {r.producto}  ·  {r.cantidad} ud × {r.precio_unitario} €"
              f"  =  {r.importe} €")
        print(f"      → {r.veredicto}")
        if "importe ≠" in str(r.veredicto):
            try:
                esperado = round(float(r.cantidad) * float(r.precio_unitario), 2)
                print(f"        cantidad × precio = {esperado} €, "
                      f"pero en la hoja pone {r.importe} €")
                print(f"        (diferencia: {round(float(r.importe) - esperado, 2)} €)")
                print("        La puerta NO lo corrige a propósito: no sabe cuál de los")
                print("        tres campos miente. Cuadra los números en la hoja.")
            except (TypeError, ValueError):
                pass


def main() -> None:
    args = [a for a in sys.argv[1:]]
    solo_caidas = "--caidas" in args
    args = [a for a in args if not a.startswith("--")]
    pedido = args[0] if args else None

    try:
        crudo = drive.leer(drive.descargar())
    except Exception as e:
        print(f"\nNo se ha podido leer la hoja de Drive: {e}\n")
        raise SystemExit(1)

    hoy = hoy_por_defecto()
    d = diagnosticar(crudo, hoy=hoy)
    _cabecera(hoy, len(d))

    # Resumen: cuántas caen por cada motivo.
    resumen = d.veredicto.value_counts()
    print("\nVEREDICTO DE TODA LA HOJA\n")
    for motivo, n in resumen.items():
        print(f"  {n:>6,}  {motivo}")

    if pedido:
        sel = d[d.pedido_id.astype(str).str.lower() == pedido.lower()]
        print("\n" + "-" * ANCHO)
        if sel.empty:
            print(f"\n  El pedido «{pedido}» NO ESTÁ en la hoja de Drive.")
            print("  Comprueba que lo escribiste en la pestaña correcta y que")
            print("  Google guardó el cambio.\n")
            return
        print(f"\nEL PEDIDO «{pedido}»")
        _pinta(sel)
        print()
        return

    filtro = d[d.veredicto != PASA] if solo_caidas else d
    titulo = "LAS 15 FILAS DESCARTADAS MÁS NUEVAS" if solo_caidas else "LAS 15 FILAS MÁS NUEVAS DE LA HOJA"
    print("\n" + "-" * ANCHO)
    print(f"\n{titulo}")
    if filtro.empty:
        print("\n  (ninguna)\n")
        return
    _pinta(filtro.sort_values("fecha", ascending=False, na_position="first").head(15))
    print()


if __name__ == "__main__":
    main()
