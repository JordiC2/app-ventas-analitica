"""
La puerta de calidad · LÓGICA PURA
===================================

Aquí está el trabajo. Todo lo demás son gráficos.

`limpiar(df)` recibe un DataFrame SUCIO y devuelve `(df_limpio, incidencias)`.

Es una función PURA:
  - No abre ningún fichero.
  - No sabe que existe un Excel ni Google Drive.
  - No sabe que existe Supabase.
  - No toca la red ni el disco.

Tiene que funcionar con la red apagada y SIN NINGÚN FICHERO:

    import pandas as pd
    from core.calidad import limpiar
    sucio = pd.DataFrame([... tres filas inventadas, una duplicada ...])
    limpio, inc = limpiar(sucio)

Si para probar la puerta hace falta un Excel, la puerta está mal puesta.

Las tres reglas de negocio (tal cual, sin "mejorarlas"):

  1. Las cantidades negativas son DEVOLUCIONES. Restan, no se borran.
  2. Los importes que no cuadran con cantidad x precio SE DESCARTAN, no se
     corrigen: no sabemos cuál de los tres campos miente.
  3. El pedido anómalo (~973.000 €) SE SEÑALA, no se borra. Sigue en los datos
     con su marca `sospechoso`. Esa decisión la toma un humano.

Y una regla de oro sobre las incidencias:

  > Un dato descartado en silencio es un dato perdido. Un dato descartado con su
  > motivo escrito es una decisión.

Por eso `limpiar` DEVUELVE la lista de incidencias como parte de la respuesta.
No es un log: es parte del resultado, y la API la sirve tal cual.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd

# La fecha de corte del NOTEBOOK. Un pedido posterior a "hoy" es un dedazo.
#
# Ojo con esta constante: en el notebook estaba congelada porque el dataset era
# congelado, y así los números eran reproducibles. En una app VIVA, que lee la
# hoja de Drive cada día, congelarla es un bug con fecha de caducidad: a partir
# del día siguiente, TODO pedido nuevo se descartaría por "fecha posterior a hoy".
#
# Por eso `limpiar()` usa por defecto la fecha de HOY DE VERDAD, y esta constante
# se queda solo para el test de referencia, que necesita fijarla para que el
# número de oro (9.766.883 €) siga siendo comprobable.
HOY_NOTEBOOK = pd.Timestamp("2026-07-14")

# VERSIÓN DE LA PUERTA. Súbela cuando cambien las REGLAS.
#
# El dato limpio es función de dos cosas: los datos de entrada y las reglas que
# los filtran. La ingesta solo miraba la huella de los datos, así que arreglar
# un bug de la puerta no reprocesaba nada: seguías viendo el parquet viejo,
# calculado con las reglas rotas, y parecía que el arreglo no había servido.
#
#   1 · versión inicial (reglas del notebook)
#   2 · la fecha de corte deja de estar congelada: es hoy de verdad
#   3 · las fechas vacías o ilegibles se descartan CON su incidencia, no en silencio
#   4 · el corte se compara por DÍA: un pedido de hoy a las 10:30 no es mañana
#   5 · se conserva `fila_origen`: el orden en que se registraron los pedidos
VERSION_PUERTA = 5

# Alias retrocompatible. Úsese HOY_NOTEBOOK si lo que se quiere es la del notebook.
HOY = HOY_NOTEBOOK

# Columnas de texto que pueden venir con huecos: se etiquetan, no se rellenan
# a ciegas ni se esconden.
_COLUMNAS_HUECO = ["comercial", "tipo_cliente", "familia"]


def hoy_por_defecto() -> pd.Timestamp:
    """La fecha de corte real: hoy, a medianoche. Se evalúa en cada llamada."""
    return pd.Timestamp.now().normalize()


def normaliza_cliente(s: Any) -> Any:
    """Nombre de cliente -> clave canónica.

    El error más caro y el que menos se ve: el mismo cliente escrito de cinco
    maneras (mayúsculas, minúsculas, espacios de más, `S.L.` vs `SL`, sin el
    punt volat). Cuatro clientes distintos para pandas; un `top clientes` sobre
    el crudo reparte su facturación entre fantasmas, y no da error.
    """
    if pd.isna(s):
        return s
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()  # fuera acentos
    s = s.replace(".", "").replace("·", "")
    return " ".join(s.split()).upper()                                        # fuera espacios dobles


def limpiar(df: pd.DataFrame,
            hoy: pd.Timestamp | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Entra un DataFrame sucio, salen un DataFrame limpio y las incidencias.

    `hoy` es la fecha de corte. Por defecto, HOY DE VERDAD (no una constante
    congelada): en una app viva, el corte se mueve con el calendario. Los tests
    de referencia la fijan a HOY_NOTEBOOK para poder comprobar el número de oro.

    Pura: no abre ficheros, no toca red ni disco. El DataFrame de entrada NO se
    muta (se trabaja sobre una copia).

    El DataFrame de salida:
      - Columna `fila_origen`: la posición que ocupaba en la hoja, que es
        el único rastro del orden en que se registraron los pedidos.
      - Cliente normalizado a su nombre canónico.
      - Sin duplicados de `pedido_id`, sin fechas ilegibles, sin fechas futuras,
        sin importes que no cuadran, sin importes a cero.
      - Columna `es_devolucion` (bool): las cantidades negativas, marcadas.
      - Columna `sospechoso` (bool): el pedido anómalo, SEÑALADO pero presente.
      - Huecos de texto etiquetados «(sin informar)».
      - Ordenado por fecha, índice reseteado.

    `incidencias` es una lista de dicts {regla, filas, accion}: qué se encontró,
    cuántas filas, y qué se hizo con ellas y por qué.
    """
    hoy = hoy if hoy is not None else hoy_por_defecto()

    d = df.copy()

    # El ORDEN EN QUE LLEGARON LAS FILAS ES INFORMACIÓN, y hasta ahora la
    # tirábamos. Quien añade un pedido a mano lo escribe AL FINAL de la hoja:
    # esa posición es lo más parecido a un «registrado el» que tenemos, porque
    # la hoja no trae ninguna marca de tiempo. Sin ella, «la última venta
    # registrada» sería indistinguible de cualquier otra del mismo día.
    #
    # Si ya viene puesta (segunda pasada de la puerta), se respeta tal cual: si
    # la recalculáramos, limpiar() dejaría de ser idempotente.
    if "fila_origen" not in d.columns:
        d.insert(0, "fila_origen", range(len(d)))

    # errors="coerce": una fecha que no se entiende se vuelve NaT y se DESCARTA
    # con su motivo escrito, unas líneas más abajo. Sin el coerce, pandas
    # reventaría con toda la ingesta por una sola celda mal escrita.
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")

    incidencias: list[dict] = []

    def anota(regla: str, n: int, accion: str) -> None:
        # Solo se anota lo que realmente pasó (n > 0), como en el notebook.
        if n:
            incidencias.append(dict(regla=regla, filas=int(n), accion=accion))

    # ── EL NOMBRE DEL CLIENTE. Lo primero, porque contamina todo lo demás. ──
    antes = d.cliente.nunique()
    d["_k"] = d.cliente.map(normaliza_cliente)
    anota(
        "Cliente escrito de N maneras",
        antes - d._k.nunique(),
        f"unificados: {antes} grafías → {d._k.nunique()} clientes reales",
    )
    # El nombre bonito de cada grupo: el que más veces aparece bien escrito.
    d["cliente"] = d._k.map(
        d.groupby("_k").cliente.agg(lambda s: s.str.strip().mode().iat[0])
    )
    d = d.drop(columns="_k")

    # ── Duplicados ──────────────────────────────────────────────────────────
    n = d.duplicated(subset=["pedido_id"]).sum()
    d = d.drop_duplicates(subset=["pedido_id"], keep="first")
    anota("Pedidos duplicados", n, "descartados (se queda el primero)")

    # ── Fechas ilegibles ────────────────────────────────────────────────────
    # Esto ANTES iba en silencio: el filtro `fecha <= hoy` tira los NaT, pero el
    # contador solo miraba `fecha > hoy`, así que una fecha vacía o mal escrita
    # desaparecía sin dejar rastro. Un dato descartado en silencio es un dato
    # perdido. Ahora tiene su línea en el informe.
    n = int(d.fecha.isna().sum())
    d = d[d.fecha.notna()]
    anota("Fecha vacía o ilegible", n,
          "descartadas: sin fecha no se puede situar el pedido en el tiempo")

    # ── Fechas imposibles ───────────────────────────────────────────────────
    # Se compara POR DÍA, no por instante. Si la hoja trae la fecha con hora
    # (2026-07-15 10:30) y el corte es hoy a medianoche (2026-07-15 00:00),
    # entonces `fecha > hoy` es CIERTO y el pedido de HOY se descartaría como
    # «futuro»: los de ayer pasarían y los de hoy no. Un pedido de hoy a las
    # 10:30 no es un pedido de mañana.
    futuras = d.fecha.dt.normalize() > hoy.normalize()
    n = int(futuras.sum())
    d = d[~futuras]
    anota("Fechas posteriores a hoy", n,
          f"descartadas: un pedido con fecha futura ({hoy.date()}) no existe")

    # ── El importe no cuadra. NO se corrige: no sabemos cuál campo miente. ──
    mal = (d.importe - d.cantidad * d.precio_unitario).abs() > 0.02
    n = int(mal.sum())
    d = d[~mal]
    anota("Importe ≠ cantidad × precio", n,
          "descartadas: no sabemos cuál de los 3 campos miente")

    # ── Importes a cero ─────────────────────────────────────────────────────
    n = int((d.importe == 0).sum())
    d = d[d.importe != 0]
    anota("Importe a cero", n, "descartadas (¿muestras? ¿filas sin acabar?)")

    # ── Negativos: son DEVOLUCIONES. Restan, no se tiran. ───────────────────
    d["es_devolucion"] = d.cantidad < 0
    anota("Cantidades negativas", int(d.es_devolucion.sum()),
          "MARCADAS como devolución — restan de la facturación, no se borran")

    # ── El outlier. Se SEÑALA. La decisión es de un humano. ─────────────────
    if (~d.es_devolucion).any():
        p999 = d[~d.es_devolucion].importe.quantile(0.999)
    else:
        p999 = 0.0
    d["sospechoso"] = (~d.es_devolucion) & (d.importe > p999 * 5)
    anota("Pedidos anómalos (>5× el percentil 99,9)", int(d.sospechoso.sum()),
          "SEÑALADOS, no borrados — que lo mire un humano")

    # ── Huecos: se etiquetan, no se rellenan ni se esconden. ────────────────
    for c in _COLUMNAS_HUECO:
        if c in d.columns:
            n = int(d[c].isna().sum())
            d[c] = d[c].fillna("(sin informar)")
            anota(f"Huecos en «{c}»", n,
                  "etiquetados «(sin informar)» — se ven en el gráfico")

    # Orden determinista: por fecha y, para las de la misma fecha, por pedido_id
    # (único tras deduplicar). Sin el desempate, dos ejecuciones sobre el mismo
    # dato podrían ordenar distinto las filas empatadas y romper la idempotencia.
    d = d.sort_values(["fecha", "pedido_id"], kind="stable").reset_index(drop=True)
    return d, incidencias


# ── El veredicto, fila a fila ───────────────────────────────────────────────
# «He añadido un pedido y no lo veo en la app.» Las incidencias dicen CUÁNTAS
# filas cayó cada regla, pero no CUÁLES. Para una persona que acaba de escribir
# una fila y no la encuentra, eso no sirve de nada.
#
# `diagnosticar()` aplica las mismas reglas, en el mismo orden, pero en vez de
# tirar filas le pone a cada una su veredicto. Pura, como todo lo de este módulo.

PASA = "PASA la puerta"


def diagnosticar(df: pd.DataFrame,
                 hoy: pd.Timestamp | None = None) -> pd.DataFrame:
    """Devuelve el DataFrame CRUDO con una columna `veredicto` por fila.

    Mismo orden de reglas que `limpiar()`: la primera que casa es la que manda,
    igual que en la puerta de verdad.
    """
    hoy = hoy if hoy is not None else hoy_por_defecto()

    d = df.copy()
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")
    v = pd.Series(PASA, index=d.index, dtype=object)

    def marca(cond, motivo: str) -> None:
        v[(v == PASA) & cond.fillna(False)] = motivo

    marca(d.duplicated(subset=["pedido_id"], keep="first"),
          "DESCARTADA · pedido_id repetido (ya existe una fila con ese número)")
    marca(d.fecha.isna(),
          "DESCARTADA · fecha vacía o ilegible")
    marca(d.fecha.dt.normalize() > hoy.normalize(),
          f"DESCARTADA · fecha posterior a hoy ({hoy.date()})")
    desc = (d.importe - d.cantidad * d.precio_unitario).abs() > 0.02
    marca(desc, "DESCARTADA · importe ≠ cantidad × precio")
    marca(d.importe == 0,
          "DESCARTADA · importe a cero")

    d["veredicto"] = v
    return d
