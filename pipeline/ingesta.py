"""
Ingesta · el borde sucio del mundo
====================================

Orquesta, no decide. Su trabajo:

  1. Traer la hoja de Google Drive (pipeline/drive.py).
  2. Comparar con lo que ya teníamos (huella de los DATOS, no del fichero).
  3. Si hay cambios, pasarla por la puerta de calidad (core/calidad.limpiar) y
     guardar el resultado. Si no los hay, no reprocesa nada.
  4. Si Drive no responde, tirar de la caché y DECIRLO.

La puerta de calidad NO vive aquí: vive en core/, y es pura.

Tres orígenes posibles, y el dashboard siempre dice cuál está mirando:

  drive       · dato recién bajado. Lo normal.
  cache       · Drive no responde; se sirve el último dato bajado, con aviso.
  referencia  · ni Drive ni caché (primer arranque sin internet). Se sirve el
                Excel congelado del notebook, con aviso bien visible.

Un dashboard que enseña datos viejos sin avisar es peor que uno que no arranca.
Por eso el origen viaja hasta la pantalla.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.calidad import VERSION_PUERTA, limpiar
from core.datos import DATA_DIR, RUTA_LIMPIO, guardar_ventas
from pipeline import drive
from pipeline.drive import DatoIlegible, DriveNoDisponible

RUTA_CACHE = DATA_DIR / "cache" / "ventas_electro.xlsx"
RUTA_REFERENCIA = DATA_DIR / "referencia" / "ventas_electro.xlsx"
RUTA_CALIDAD = DATA_DIR / "calidad.json"
RUTA_MANIFIESTO = DATA_DIR / "manifiesto.json"

_CLAVES = ("crudas", "limpias", "fact_crudo", "fact_limpio")


def _ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _base(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.sospechoso] if "sospechoso" in df.columns else df


def _leer_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resumen(crudo: pd.DataFrame, limpio: pd.DataFrame) -> dict:
    base = _base(limpio)
    return dict(
        crudas=int(len(crudo)),
        limpias=int(len(base)),
        fact_crudo=round(float(crudo.importe.sum())),
        fact_limpio=round(float(base.importe.sum())),
    )


def _obtener():
    """Devuelve (df_crudo, bytes_o_None, huella, origen, aviso)."""
    # 1 · Drive, que es la fuente de verdad.
    try:
        b, df, h = drive.obtener()
        return df, b, h, "drive", None
    except (DriveNoDisponible, DatoIlegible) as e:
        motivo = str(e)

    # 2 · La caché: el último dato que sí bajamos.
    if RUTA_CACHE.exists():
        df = drive.leer(RUTA_CACHE.read_bytes())
        man = _leer_json(RUTA_MANIFIESTO) or {}
        cuando = man.get("dato_de", "fecha desconocida")
        aviso = (f"Drive no responde ({motivo}). Se muestra el último dato "
                 f"descargado ({cuando}). Puede haber pedidos más recientes "
                 f"sin reflejar.")
        return df, None, drive.huella_datos(df), "cache", aviso

    # 3 · Ni Drive ni caché: el Excel congelado del notebook, avisando fuerte.
    if RUTA_REFERENCIA.exists():
        df = pd.read_excel(RUTA_REFERENCIA, sheet_name="Pedidos")
        aviso = (f"Drive no responde ({motivo}) y no hay ninguna descarga "
                 f"previa. Se muestra el Excel DE REFERENCIA del notebook: son "
                 f"datos de ejemplo congelados, NO los pedidos reales.")
        return df, None, drive.huella_datos(df), "referencia", aviso

    raise DriveNoDisponible(
        f"{motivo}. Y no hay ni caché ni Excel de referencia: nada que servir."
    )


def ejecutar(forzar: bool = False) -> dict:
    """Trae el dato, lo compara con la caché y, si cambió, lo pasa por la puerta.

    Devuelve el informe: qué origen, si hubo cambio, y el delta contra lo previo.
    """
    df_crudo, b, huella, origen, aviso = _obtener()

    man = _leer_json(RUTA_MANIFIESTO)
    cal = _leer_json(RUTA_CALIDAD)

    # El parquet es función de DOS cosas: los datos y las reglas de la puerta.
    # Si cambia cualquiera de las dos, hay que rehacerlo. Mirar solo la huella
    # de los datos significaba que arreglar un bug de la puerta no reprocesaba
    # nada: seguías viendo el resultado viejo y el arreglo parecía no servir.
    intacto = (man is not None and cal is not None
               and man.get("huella") == huella
               and man.get("version_puerta") == VERSION_PUERTA
               and RUTA_LIMPIO.exists())

    # Sin cambios: no se reprocesa nada.
    if intacto and not forzar:
        man["comprobado_en"] = _ahora()
        man["origen"] = origen
        RUTA_MANIFIESTO.write_text(json.dumps(man, ensure_ascii=False),
                                   encoding="utf-8")
        return dict(
            cambio=False, origen=origen, aviso=aviso, huella=huella,
            dato_de=man.get("dato_de"), comprobado_en=man["comprobado_en"],
            antes=None, ahora={k: cal[k] for k in _CLAVES}, delta=None,
            mensaje="Sin cambios en Drive: el dato es el mismo que ya teníamos.",
        )

    # Hay dato nuevo (o se ha forzado): la puerta otra vez.
    antes = {k: cal[k] for k in _CLAVES} if cal is not None else None

    if origen == "drive" and b is not None:
        RUTA_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RUTA_CACHE.write_bytes(b)          # la caché, para cuando Drive no esté

    limpio, incidencias = limpiar(df_crudo)
    guardar_ventas(limpio)

    ahora = _resumen(df_crudo, limpio)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUTA_CALIDAD.write_text(
        json.dumps(dict(**ahora, incidencias=incidencias), ensure_ascii=False),
        encoding="utf-8")

    sello = _ahora()
    RUTA_MANIFIESTO.write_text(
        json.dumps(dict(huella=huella, version_puerta=VERSION_PUERTA,
                        origen=origen, dato_de=sello,
                        comprobado_en=sello, **ahora), ensure_ascii=False),
        encoding="utf-8")

    # Por qué se ha reprocesado: o cambió el dato, o cambiaron las reglas. Decirlo
    # bien importa: «Dato nuevo: +0 pedidos» ante un cambio de reglas es un
    # mensaje que no explica nada y encima suena a que algo va mal.
    version_vieja = man.get("version_puerta") if man is not None else None
    reglas_nuevas = man is not None and version_vieja != VERSION_PUERTA

    delta = None
    if antes is not None:
        delta = dict(
            crudas=ahora["crudas"] - antes["crudas"],
            limpias=ahora["limpias"] - antes["limpias"],
            fact_limpio=ahora["fact_limpio"] - antes["fact_limpio"],
        )
        if reglas_nuevas:
            msg = (f"Reglas de la puerta actualizadas (v{version_vieja} → "
                   f"v{VERSION_PUERTA}). Todo el dato vuelve a pasar por ella: "
                   f"{delta['limpias']:+,} pedidos, {delta['fact_limpio']:+,} €.")
        else:
            msg = (f"Dato nuevo: {delta['limpias']:+,} pedidos analizados, "
                   f"{delta['fact_limpio']:+,} € de facturación.")
    else:
        msg = f"Primer dato cargado: {ahora['limpias']:,} pedidos analizados."

    return dict(cambio=True, origen=origen, aviso=aviso, huella=huella,
                dato_de=sello, comprobado_en=sello,
                antes=antes, ahora=ahora, delta=delta, mensaje=msg)


def estado() -> dict:
    """Lo que hay ahora mismo en disco, sin tocar la red."""
    man = _leer_json(RUTA_MANIFIESTO) or {}
    return dict(
        origen=man.get("origen"),
        dato_de=man.get("dato_de"),
        comprobado_en=man.get("comprobado_en"),
        huella=man.get("huella"),
        limpias=man.get("limpias"),
        fact_limpio=man.get("fact_limpio"),
    )


_ORIGEN = {"drive": "Google Drive",
           "cache": "CACHÉ (Drive no responde)",
           "referencia": "REFERENCIA del notebook (Drive no responde)"}


def main() -> None:
    inf = ejecutar()
    print(f"Origen: {_ORIGEN.get(inf['origen'], inf['origen'])}")
    if inf["aviso"]:
        print(f"AVISO : {inf['aviso']}")
    print()
    print(inf["mensaje"])
    print()

    a = inf["ahora"]
    print(f"{a['crudas']:,} filas crudas -> {a['limpias']:,} tras la puerta")
    print(f"Facturación cruda : {a['fact_crudo']:>13,.0f} €")
    print(f"Facturación real  : {a['fact_limpio']:>13,.0f} €")
    dif = a["fact_crudo"] - a["fact_limpio"]
    if a["fact_crudo"]:
        pct = dif / a["fact_crudo"] * 100
        print(f"Diferencia        : {dif:>13,.0f} €  ({pct:.1f} %)")

    if inf["delta"]:
        d = inf["delta"]
        print(f"\nFrente al dato anterior: {d['limpias']:+,} pedidos · "
              f"{d['fact_limpio']:+,.0f} €")

    if inf["cambio"]:
        cal = _leer_json(RUTA_CALIDAD) or {}
        print("\nIncidencias:")
        for r in cal.get("incidencias", []):
            print(f"  {r['regla']:<45} {r['filas']:>4}  {r['accion']}")


if __name__ == "__main__":
    main()
