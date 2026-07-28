"""
La puerta de calidad · pureza e INVARIANTES sobre el dato vivo
==============================================================

Dos bloques:

  1. **La puerta es pura.** Se prueba con filas inventadas, sin ningún fichero y
     con la red apagada. Si para probar la puerta hiciera falta un Excel (o
     Drive), la puerta estaría mal puesta.

  2. **Invariantes sobre el dato que se va a servir.** Corren contra el parquet
     que acaba de dejar la ingesta — es decir, contra los datos de Google Drive
     de hoy. No fijan ningún número: fijan REGLAS que deben cumplirse con
     cualquier dato, venga lo que venga de Drive.

El número de oro (9.766.883 €) NO está aquí: está en test_referencia.py, contra
el Excel congelado. Un número fijo contra un dato que cambia cada día sería un
test que falla por hacer bien su trabajo.

docker-compose ejecuta todo esto ANTES de arrancar la API. Si algo falla, la app
no levanta.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.calidad import (PASA, diagnosticar, hoy_por_defecto, limpiar,
                          normaliza_cliente)
from core.datos import RUTA_LIMPIO, cargar_ventas


def _base(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.sospechoso] if "sospechoso" in df.columns else df


# ════════════════════════════════════════════════════════════════════════
# 1 · LA PUERTA ES PURA. Sin ficheros, sin red, con filas inventadas.
# ════════════════════════════════════════════════════════════════════════
def _sucio_inventado() -> pd.DataFrame:
    """Tres filas inventadas, una duplicada. Ni Excel, ni Drive, ni disco."""
    filas = [
        dict(pedido_id="P1", fecha="2025-03-10", comercial="Marta Ibáñez",
             zona="Barcelona", cliente="Ferretería López", tipo_cliente="Retail",
             producto="Downlight LED 18W", familia="Iluminación",
             cantidad=10, precio_unitario=11.20, importe=112.00),
        dict(pedido_id="P2", fecha="2025-04-02", comercial="Xavier Puig",
             zona="Girona", cliente="  FERRETERIA LOPEZ ", tipo_cliente="Retail",
             producto="Downlight LED 18W", familia="Iluminación",
             cantidad=-2, precio_unitario=11.20, importe=-22.40),
        dict(pedido_id="P1", fecha="2025-03-10", comercial="Marta Ibáñez",
             zona="Barcelona", cliente="ferreteria lopez", tipo_cliente="Retail",
             producto="Downlight LED 18W", familia="Iluminación",
             cantidad=10, precio_unitario=11.20, importe=112.00),
    ]
    return pd.DataFrame(filas)


def test_la_puerta_es_pura_sin_ficheros():
    """limpiar() se prueba sin abrir un solo fichero y sin tocar la red."""
    sucio = _sucio_inventado()
    limpio, inc = limpiar(sucio)

    assert len(sucio) == 3                       # el de entrada no se muta
    assert limpio.cliente.nunique() == 1         # las 3 grafias colapsan a 1
    assert not limpio.duplicated(subset=["pedido_id"]).any()
    assert set(limpio.pedido_id) == {"P1", "P2"}
    assert limpio.es_devolucion.sum() == 1       # la devolucion se marca

    assert isinstance(inc, list) and len(inc) >= 1
    assert all({"regla", "filas", "accion"} <= set(i) for i in inc)


def test_idempotencia_sin_ficheros():
    """limpiar() dos veces == una vez. Sin idempotencia no se puede reintentar."""
    una, _ = limpiar(_sucio_inventado())
    dos, _ = limpiar(una)
    pd.testing.assert_frame_equal(una, dos)


def test_las_devoluciones_restan_sin_ficheros():
    limpio, _ = limpiar(_sucio_inventado())
    bruta = limpio[~limpio.es_devolucion].importe.sum()
    neta = limpio.importe.sum()
    assert neta < bruta


# ════════════════════════════════════════════════════════════════════════
# 2 · INVARIANTES sobre el dato que se va a servir (el de Drive, hoy).
#     Ni un numero fijo: solo reglas validas para cualquier dato.
# ════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def servido() -> pd.DataFrame:
    """El parquet que acaba de dejar la ingesta. Lo que la API va a servir."""
    if not RUTA_LIMPIO.exists():
        pytest.skip("No hay parquet: ejecuta antes `python -m pipeline.ingesta`")
    return cargar_ventas()


def test_hay_datos(servido):
    assert len(servido) > 0
    assert len(_base(servido)) > 0


def test_no_quedan_pedidos_duplicados(servido):
    assert not servido.duplicated(subset=["pedido_id"]).any()


def test_no_quedan_fechas_futuras(servido):
    """Contra HOY DE VERDAD, no contra una constante congelada."""
    assert (servido.fecha <= hoy_por_defecto()).all()


def test_no_quedan_importes_que_no_cuadran(servido):
    desc = (servido.importe - servido.cantidad * servido.precio_unitario).abs() > 0.02
    assert not desc.any()


def test_no_quedan_importes_a_cero(servido):
    assert (servido.importe != 0).all()


def test_no_quedan_dos_grafias_del_mismo_cliente(servido):
    """La generalizacion de «quedan 15 clientes» que vale para cualquier dato.

    No fijamos cuantos clientes hay (manana puede haber uno mas y seria
    legitimo). Fijamos que no queden DOS formas de escribir el mismo: si
    «Ferreteria Lopez» y «FERRETERIA LOPEZ» sobrevivieran juntos, el top
    clientes repartiria su facturacion entre dos fantasmas. Y no daria error.
    """
    nombres = servido.cliente.dropna().unique()
    claves = {normaliza_cliente(n) for n in nombres}
    assert len(claves) == len(nombres), (
        "hay clientes que normalizan a la misma clave: "
        f"{len(nombres)} grafias -> {len(claves)} claves"
    )


def test_los_nombres_estan_limpios(servido):
    """Sin espacios de sobra a los lados: el asesino silencioso."""
    nombres = pd.Series(servido.cliente.dropna().unique())
    assert (nombres == nombres.str.strip()).all()


def test_huecos_etiquetados_no_escondidos(servido):
    """Los huecos se etiquetan «(sin informar)», no se rellenan ni se ocultan."""
    for c in ["comercial", "tipo_cliente", "familia"]:
        if c in servido.columns:
            assert servido[c].isna().sum() == 0


def test_las_devoluciones_restan(servido):
    base = _base(servido)
    if base.es_devolucion.sum() == 0:
        pytest.skip("este dato no trae devoluciones")
    bruta = base[~base.es_devolucion].importe.sum()
    neta = base.importe.sum()
    assert neta < bruta


def test_idempotencia_sobre_el_dato_servido(servido):
    """Volver a pasar la puerta sobre el dato ya limpio no cambia nada."""
    otra_vez, _ = limpiar(servido)
    pd.testing.assert_frame_equal(servido, otra_vez)


# ════════════════════════════════════════════════════════════════════════
# 3 · REGRESIONES. Dos bugs que aparecieron al meter datos de verdad.
# ════════════════════════════════════════════════════════════════════════
def test_un_pedido_de_hoy_pasa_la_puerta():
    """REGRESION: la fecha de corte estaba congelada en 2026-07-14.

    Con la constante fija, a partir del dia siguiente TODO pedido nuevo se
    habria descartado por «fecha posterior a hoy», en una app cuya razon de ser
    es justamente enseñar los pedidos nuevos. El corte tiene que moverse con el
    calendario.
    """
    sucio = _sucio_inventado()
    hoy = pd.Timestamp.now().normalize()
    sucio.loc[0, "fecha"] = hoy
    limpio, _ = limpiar(sucio)
    assert hoy in set(limpio.fecha), "un pedido de hoy NO puede caerse"


def test_un_pedido_de_hoy_CON_HORA_pasa_la_puerta():
    """REGRESION: «los de antes de hoy si los coge, los de hoy no».

    El corte era hoy A MEDIANOCHE, pero la comparacion se hacia contra el
    INSTANTE del pedido. Si la hoja trae la fecha con hora (2026-07-15 10:30),
    entonces `10:30 > 00:00` era cierto y el pedido de HOY se descartaba como
    «fecha posterior a hoy». Los de ayer pasaban; los de hoy, no. Exactamente
    ese sintoma.

    Un pedido de hoy a las 10:30 no es un pedido de manana: se compara por DIA.
    """
    sucio = _sucio_inventado()
    sucio.loc[0, "fecha"] = pd.Timestamp.now().normalize() + pd.Timedelta(hours=10, minutes=30)
    limpio, _ = limpiar(sucio)
    assert "P1" in set(limpio.pedido_id), "un pedido de hoy a las 10:30 NO es el futuro"


def test_un_pedido_de_hoy_a_las_23_59_pasa_la_puerta():
    """El limite del dia. Sigue siendo hoy."""
    sucio = _sucio_inventado()
    sucio.loc[0, "fecha"] = (pd.Timestamp.now().normalize()
                             + pd.Timedelta(hours=23, minutes=59, seconds=59))
    limpio, _ = limpiar(sucio)
    assert "P1" in set(limpio.pedido_id)


def test_el_veredicto_usa_el_mismo_criterio_de_dia():
    """Si el diagnostico y la puerta discreparan, el diagnostico mentiria."""
    sucio = _sucio_inventado()
    sucio.loc[0, "fecha"] = pd.Timestamp.now().normalize() + pd.Timedelta(hours=10, minutes=30)
    limpio, _ = limpiar(sucio)
    d = diagnosticar(sucio)
    assert set(d[d.veredicto == PASA].pedido_id) == set(limpio.pedido_id)


def test_un_pedido_de_manana_se_descarta():
    """La otra cara: el futuro sigue siendo un dedazo."""
    sucio = _sucio_inventado()
    manana = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    sucio.loc[0, "fecha"] = manana
    limpio, inc = limpiar(sucio)
    assert manana not in set(limpio.fecha)
    assert "Fechas posteriores a hoy" in {i["regla"] for i in inc}


def test_la_fecha_vacia_no_desaparece_en_silencio():
    """REGRESION: una fila sin fecha se caia SIN aparecer en las incidencias.

    El filtro `fecha <= hoy` tira los NaT, pero el contador solo miraba
    `fecha > hoy`. Resultado: la fila se esfumaba sin dejar rastro. Un dato
    descartado en silencio es un dato perdido.
    """
    sucio = _sucio_inventado()
    sucio.loc[1, "fecha"] = None
    limpio, inc = limpiar(sucio)
    reglas = {i["regla"] for i in inc}
    assert "Fecha vacía o ilegible" in reglas, "se ha caido sin decir por que"
    n = sum(i["filas"] for i in inc if i["regla"] == "Fecha vacía o ilegible")
    assert n == 1


def test_una_fecha_ilegible_no_revienta_la_ingesta():
    """Una celda mal escrita no puede tumbar las 10.000 filas restantes."""
    sucio = _sucio_inventado()
    sucio.loc[1, "fecha"] = "el martes que viene"
    limpio, inc = limpiar(sucio)                      # no debe lanzar
    assert "Fecha vacía o ilegible" in {i["regla"] for i in inc}
    assert len(limpio) >= 1


def test_las_incidencias_explican_todas_las_bajas():
    """Ninguna fila puede desaparecer sin una incidencia que lo justifique.

    Este es el test que hace de red: cuenta las filas que entran, las que salen,
    y exige que la diferencia este explicada por las reglas de descarte.
    """
    sucio = _sucio_inventado()
    sucio.loc[1, "fecha"] = None                     # una sin fecha
    limpio, inc = limpiar(sucio)

    descartes = {"Pedidos duplicados", "Fecha vacía o ilegible",
                 "Fechas posteriores a hoy", "Importe ≠ cantidad × precio",
                 "Importe a cero"}
    caidas = sum(i["filas"] for i in inc if i["regla"] in descartes)
    assert len(sucio) - len(limpio) == caidas


# ════════════════════════════════════════════════════════════════════════
# 4 · EL VEREDICTO fila a fila. «He añadido un pedido y no lo veo.»
# ════════════════════════════════════════════════════════════════════════
def test_diagnosticar_dice_cual_pasa_y_cual_no():
    d = diagnosticar(_sucio_inventado())
    assert "veredicto" in d.columns
    assert len(d) == 3                                # no tira ninguna fila
    assert d.veredicto.iloc[0] == PASA


def test_diagnosticar_señala_el_duplicado():
    d = diagnosticar(_sucio_inventado())
    assert "repetido" in d.veredicto.iloc[2]          # P1 otra vez


def test_diagnosticar_explica_el_importe_que_no_cuadra():
    """El caso tipico de quien escribe una fila a mano."""
    sucio = _sucio_inventado()
    sucio.loc[0, "importe"] = 112.50                  # deberia ser 112.00
    d = diagnosticar(sucio)
    assert "importe" in d.veredicto.iloc[0]


def test_diagnosticar_usa_las_mismas_reglas_que_la_puerta():
    """Si el veredicto y la puerta no coincidieran, el diagnostico mentiria."""
    sucio = _sucio_inventado()
    sucio.loc[1, "fecha"] = None
    limpio, _ = limpiar(sucio)
    d = diagnosticar(sucio)
    assert set(d[d.veredicto == PASA].pedido_id) == set(limpio.pedido_id)
