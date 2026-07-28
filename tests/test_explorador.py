"""
El explorador de ventas · core.metricas.ventas()
=================================================

Funcion pura: se prueba con filas inventadas, sin ficheros y sin red.

Ojo con el fixture: `ventas()` recibe un DataFrame YA LIMPIO, asi que aqui se
construye con las marcas (`es_devolucion`, `sospechoso`) puestas a mano, sin
pasar por `limpiar()`. No es un atajo, es lo correcto: el trabajo de la puerta
ya esta probado en test_referencia.py, y ademas la regla del outlier
(`importe > percentil_99,9 x 5`) necesita miles de filas para tener sentido —
con seis, el percentil 99,9 ES el propio pedidazo y no se marcaria nada.

Lo que se fija aqui no son numeros, son REGLAS:
  - lo ultimo, arriba (orden por fecha descendente, determinista);
  - la paginacion no pierde ni repite filas;
  - los filtros filtran;
  - las devoluciones se ven, marcadas y en negativo;
  - EL PEDIDO SEÑALADO SE VE, Y ESTA A UN CLIC. Los KPI lo excluyen; si aqui
    hubiera que pasar 300 paginas para dar con el, señalarlo seria lo mismo que
    borrarlo en silencio.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.metricas import ventas


def _limpio() -> pd.DataFrame:
    """Seis pedidos ya pasados por la puerta, con sus marcas puestas."""
    filas = [
        dict(pedido_id="P1", fecha="2025-01-10", comercial="Marta Ibáñez",
             zona="Barcelona", cliente="Electro Ribas SA", tipo_cliente="Distribuidor",
             producto="Cable RZ1-K 3x2.5", familia="Cable",
             cantidad=100, precio_unitario=2.00, importe=200.00,
             es_devolucion=False, sospechoso=False),
        dict(pedido_id="P2", fecha="2026-06-01", comercial="Xavier Puig",
             zona="Girona", cliente="Ferretería López", tipo_cliente="Retail",
             producto="Downlight LED 18W", familia="Iluminación",
             cantidad=10, precio_unitario=11.20, importe=112.00,
             es_devolucion=False, sospechoso=False),
        dict(pedido_id="P3", fecha="2026-07-01", comercial="Marta Ibáñez",
             zona="Barcelona", cliente="Electro Ribas SA", tipo_cliente="Distribuidor",
             producto="Luminaria LED 40W", familia="Iluminación",
             cantidad=-5, precio_unitario=28.90, importe=-144.50,
             es_devolucion=True, sospechoso=False),          # devolucion
        dict(pedido_id="P4", fecha="2026-07-02", comercial="Nuria Sanz",
             zona="Barcelona", cliente="Bricolatge Mestre", tipo_cliente="Retail",
             producto="Tubo corrugado M20", familia="Canalización",
             cantidad=50, precio_unitario=0.50, importe=25.00,
             es_devolucion=False, sospechoso=False),
        dict(pedido_id="P5", fecha="2026-07-03", comercial="Xavier Puig",
             zona="Girona", cliente="Comercial Delta SA", tipo_cliente="Distribuidor",
             producto="Cuadro eléctrico 24 mód", familia="Cuadros",
             cantidad=20, precio_unitario=80.00, importe=1600.00,
             es_devolucion=False, sospechoso=False),
        dict(pedido_id="P6", fecha="2025-03-05", comercial="Andreu Roca",
             zona="Lleida", cliente="Grup Elèctric Ponent", tipo_cliente="Distribuidor",
             producto="Cuadro eléctrico 24 mód", familia="Cuadros",
             cantidad=99999, precio_unitario=80.00, importe=7999920.00,
             es_devolucion=False, sospechoso=True),          # el pedidazo, señalado
    ]
    df = pd.DataFrame(filas)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df.sort_values(["fecha", "pedido_id"]).reset_index(drop=True)


@pytest.fixture(scope="module")
def d():
    return _limpio()


def test_lo_ultimo_arriba(d):
    """Orden por fecha descendente: para eso es un explorador de «las ultimas»."""
    v = ventas(d)
    fechas = [f["fecha"] for f in v["filas"]]
    assert fechas == sorted(fechas, reverse=True)
    assert v["filas"][0]["pedido_id"] == "P5"     # 2026-07-03, la mas reciente


def test_por_defecto_salen_todas_incluido_el_senalado(d):
    v = ventas(d)
    assert v["total"] == 6
    assert sum(1 for f in v["filas"] if f["senalado"]) == 1


def test_el_pedido_senalado_esta_a_un_clic(d):
    """El filtro que hace util el señalamiento. Sin esto, esta enterrado."""
    v = ventas(d, marca="senalados")
    assert v["total"] == 1
    assert v["filas"][0]["pedido_id"] == "P6"
    assert v["filas"][0]["senalado"] is True
    # Y es antiguo (2025-03): por fecha estaria en la pagina 300 del dato real.
    assert v["filas"][0]["fecha"] == "2025-03-05"


def test_se_pueden_ocultar_los_senalados(d):
    """«sin_senalados» = exactamente lo que ven los KPI."""
    v = ventas(d, marca="sin_senalados")
    assert v["total"] == 5
    assert all(not f["senalado"] for f in v["filas"])


def test_solo_devoluciones(d):
    v = ventas(d, marca="devoluciones")
    assert v["total"] == 1
    f = v["filas"][0]
    assert f["pedido_id"] == "P3"
    assert f["devolucion"] is True
    assert f["importe"] < 0 and f["cantidad"] < 0


def test_la_devolucion_se_ve_marcada_en_la_lista_general(d):
    v = ventas(d)
    dev = [f for f in v["filas"] if f["devolucion"]]
    assert len(dev) == 1 and dev[0]["importe"] < 0


def test_la_paginacion_no_pierde_ni_repite(d):
    """Dos paginas de 3 tienen que dar el total exacto, sin solapes."""
    total = ventas(d)["total"]
    p1 = ventas(d, limite=3, offset=0)
    p2 = ventas(d, limite=3, offset=3)
    ids1 = [f["pedido_id"] for f in p1["filas"]]
    ids2 = [f["pedido_id"] for f in p2["filas"]]
    assert len(ids1) == 3 and len(ids2) == 3
    assert not set(ids1) & set(ids2)            # sin repetidos
    assert len(set(ids1) | set(ids2)) == total  # sin perdidos
    assert p1["total"] == p2["total"] == total


def test_el_buscador_busca_en_varias_columnas(d):
    assert ventas(d, q="ribas")["total"] == 2          # cliente
    assert ventas(d, q="downlight")["total"] == 1      # producto
    assert ventas(d, q="P5")["total"] == 1             # nº de pedido
    assert ventas(d, q="xavier")["total"] == 2         # comercial
    assert ventas(d, q="noexiste")["total"] == 0


def test_el_buscador_ignora_mayusculas(d):
    assert ventas(d, q="RIBAS")["total"] == ventas(d, q="ribas")["total"]


def test_filtro_por_comercial(d):
    v = ventas(d, comercial="Xavier Puig")
    assert v["total"] == 2
    assert all(f["comercial"] == "Xavier Puig" for f in v["filas"])


def test_filtro_por_fechas(d):
    v = ventas(d, desde="2026-07-01", hasta="2026-07-02")
    assert {f["pedido_id"] for f in v["filas"]} == {"P3", "P4"}


def test_los_filtros_se_combinan(d):
    v = ventas(d, comercial="Marta Ibáñez", marca="devoluciones")
    assert v["total"] == 1 and v["filas"][0]["pedido_id"] == "P3"


def test_el_importe_del_pie_es_el_de_lo_filtrado_no_el_de_la_pagina(d):
    v = ventas(d, comercial="Xavier Puig", limite=1)
    assert len(v["filas"]) == 1          # una fila en la pagina
    assert v["total"] == 2               # dos en el filtro
    assert v["importe"] == round(112.00 + 1600.00)


def test_el_limite_tiene_techo(d):
    """Nadie puede pedir 10.000 filas de un tiron."""
    assert ventas(d, limite=99999)["limite"] == 200


def test_no_muta_el_dataframe(d):
    antes = len(d)
    ventas(d, q="ribas", comercial="Marta Ibáñez", marca="senalados")
    assert len(d) == antes
