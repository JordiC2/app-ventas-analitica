"""
Los chequeos de la celda 4 del notebook · CONTRA EL FIXTURE CONGELADO
=====================================================================

Aquí viven los SIETE chequeos originales, incluido el número de oro:
**9.766.883 €**.

Y corren contra `data/referencia/ventas_electro.xlsx`, que es el Excel que generó
el notebook y que **no cambia nunca**. Ese es justo el punto.

Por qué separados de los datos de Drive:

  El número 9.766.883 € no es una verdad sobre el negocio: es una verdad sobre
  ESTE dataset pasado por ESTA puerta. Los datos de Drive cambian cada día — esa
  es la gracia de la app. Si atáramos el número de oro al dato vivo, el test
  fallaría mañana por hacer bien su trabajo, y acabaríamos borrándolo.

  Fixture congelado + número fijo = detector de regresiones. Si alguien toca
  core/calidad.py y la facturación de ESTE Excel deja de dar 9.766.883 €, es que
  la puerta ha cambiado de criterio. Eso es exactamente lo que queremos cazar.

Los invariantes que SÍ deben cumplirse con cualquier dato (incluido el de Drive)
están en test_calidad.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.calidad import HOY_NOTEBOOK, limpiar
from core.negocio import N_CLIENTES
from pipeline.ingesta import RUTA_REFERENCIA

FACTURACION_ESPERADA = 9_766_883   # € · el número comprobable del notebook
CRUDAS_ESPERADAS = 10_058          # filas del Excel de referencia


def _base(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.sospechoso] if "sospechoso" in df.columns else df


@pytest.fixture(scope="module")
def ref():
    """El Excel congelado del notebook, pasado por la puerta."""
    if not RUTA_REFERENCIA.exists():
        pytest.skip(f"Falta el fixture de referencia en {RUTA_REFERENCIA}")
    crudo = pd.read_excel(RUTA_REFERENCIA, sheet_name="Pedidos")
    # La fecha de corte se FIJA a la del notebook. El fixture esta congelado,
    # asi que su corte tambien: si usara "hoy de verdad", el numero de oro
    # cambiaria solo con que pasara el tiempo, y el test fallaria sin que
    # nadie hubiera tocado nada.
    limpio, incidencias = limpiar(crudo, hoy=HOY_NOTEBOOK)
    return crudo, limpio, incidencias


def test_el_fixture_no_ha_cambiado(ref):
    """Si esto falla, alguien ha tocado el Excel de referencia. No se toca."""
    crudo, _, _ = ref
    assert len(crudo) == CRUDAS_ESPERADAS


def test_quedan_exactamente_15_clientes(ref):
    """Tras normalizar quedan EXACTAMENTE 15 clientes, no las 63 grafías."""
    _, limpio, _ = ref
    assert _base(limpio).cliente.nunique() == N_CLIENTES == 15


def test_no_quedan_pedidos_duplicados(ref):
    _, limpio, _ = ref
    assert not limpio.duplicated(subset=["pedido_id"]).any()


def test_no_quedan_fechas_futuras(ref):
    _, limpio, _ = ref
    assert (limpio.fecha <= HOY_NOTEBOOK).all()


def test_no_quedan_importes_que_no_cuadran(ref):
    _, limpio, _ = ref
    desc = (limpio.importe - limpio.cantidad * limpio.precio_unitario).abs() > 0.02
    assert not desc.any()


def test_facturacion_limpia_9_766_883(ref):
    """EL NÚMERO. Si esto se mueve, la puerta ha cambiado de criterio."""
    _, limpio, _ = ref
    fact = _base(limpio).importe.sum()
    assert abs(fact - FACTURACION_ESPERADA) <= 1, f"facturación = {fact:,.2f} €"


def test_las_devoluciones_restan(ref):
    """Facturación neta (con devoluciones) < facturación bruta (sin ellas)."""
    _, limpio, _ = ref
    base = _base(limpio)
    bruta = base[~base.es_devolucion].importe.sum()
    neta = base.importe.sum()
    assert neta < bruta
    assert base.es_devolucion.sum() > 0


def test_idempotencia(ref):
    """limpiar() dos veces == limpiar() una vez."""
    _, limpio, _ = ref
    otra_vez, _ = limpiar(limpio, hoy=HOY_NOTEBOOK)
    pd.testing.assert_frame_equal(limpio, otra_vez)


def test_el_pedido_anomalo_sigue_en_los_datos(ref):
    """Se SEÑALA, no se borra. La decisión la toma un humano."""
    _, limpio, incidencias = ref
    assert limpio.sospechoso.sum() == 1
    # Y no cuenta para la facturación mientras nadie lo apruebe.
    assert _base(limpio).sospechoso.sum() == 0
    reglas = {i["regla"] for i in incidencias}
    assert any("anómalos" in r for r in reglas)
