"""
Métricas · KPIs, series, desgloses y el explorador
==================================================

Funciones PURAS sobre un DataFrame limpio. Ni Excel, ni Drive, ni red, ni base
de datos.

Los KPI NO se guardan. SE CALCULAN. Son ~10.000 filas: es instantáneo. Si los
guardáramos, cambiar la definición de «ticket medio» obligaría a reejecutar el
pipeline entero. Aquí solo hay cálculo; el almacenamiento vive en core/datos.py.

    Guarda lo que cuesta obtener. Calcula lo que cuesta poco.

Sobre el pedido señalado: el DataFrame limpio LO CONTIENE (con `sospechoso=True`),
pero las MÉTRICAS lo excluyen. Sigue en los datos para que un humano lo mire; no
infla la facturación mientras nadie lo aprueba.

El EXPLORADOR, en cambio, sí lo enseña (marcado). Es el único sitio donde ese
pedido se puede ver: de nada sirve señalar algo para que lo revise un humano si
luego no hay ninguna pantalla donde el humano pueda verlo.
"""

from __future__ import annotations

import pandas as pd

from . import negocio

# Columna real sobre la que se agrega cada desglose del dashboard.
_COL_DESGLOSE = {
    "familia":   "familia",
    "producto":  "producto",
    "comercial": "comercial",
    "zona":      "zona",
    "tipo":      "tipo_cliente",
    "clientes":  "cliente",
}

# Columnas donde busca el cuadro de búsqueda del explorador.
_COL_BUSQUEDA = ["cliente", "producto", "pedido_id", "comercial"]


def _base(df: pd.DataFrame) -> pd.DataFrame:
    """Filas que cuentan para las métricas: las NO señaladas como sospechosas.

    Las devoluciones SÍ cuentan (restan, importe negativo). El pedido anómalo NO,
    porque aún no lo ha aprobado un humano.
    """
    if "sospechoso" in df.columns:
        return df[~df.sospechoso]
    return df


def top(df: pd.DataFrame, clave: str, n: int | None = None) -> dict:
    """Ranking por importe facturado (no por unidades) de la columna `clave`."""
    col = _COL_DESGLOSE.get(clave, clave)
    if n is None:
        n = negocio.DESGLOSES.get(clave, 8)
    t = _base(df).groupby(col).importe.sum().nlargest(n)
    return dict(k=list(t.index), v=[round(float(x)) for x in t.values])


def serie_mensual(df: pd.DataFrame) -> dict:
    """Importe y número de pedidos por mes. La base del gráfico de evolución."""
    b = _base(df)
    mes = (b.groupby(b.fecha.dt.to_period("M"))
             .agg(imp=("importe", "sum"), ped=("pedido_id", "count"))
             .reset_index())
    mes["m"] = mes.fecha.astype(str)
    return dict(
        m=list(mes.m),
        imp=[round(float(x)) for x in mes.imp],
        ped=[int(x) for x in mes.ped],
    )


def kpis(df: pd.DataFrame,
         desde: str | pd.Timestamp | None = None,
         hasta: str | pd.Timestamp | None = None) -> dict:
    """KPIs RECALCULADOS para la ventana [desde, hasta].

    Este es el cálculo que demuestra que los números no están guardados: cambias
    las fechas y los números cambian. Imposible con un HTML congelado.
    """
    b = _base(df)
    if b.empty:
        return dict(facturacion=0, var_pct=None, pedidos=0, ticket=0,
                    clientes=0, devoluciones=0, dev_pct=0.0,
                    desde=None, hasta=None)

    hasta = pd.Timestamp(hasta) if hasta is not None else b.fecha.max()
    desde = pd.Timestamp(desde) if desde is not None else hasta - pd.DateOffset(months=12)

    win = b[(b.fecha >= desde) & (b.fecha <= hasta)]

    # Ventana anterior de igual longitud, para la variación honesta.
    dur = hasta - desde
    prev = b[(b.fecha >= desde - dur) & (b.fecha < desde)]
    var_pct = None
    if len(prev) and prev.importe.sum() != 0:
        var_pct = round(float((win.importe.sum() / prev.importe.sum() - 1) * 100), 1)

    ventas_ = win[~win.es_devolucion]
    dev = -win[win.es_devolucion].importe.sum()
    bru = ventas_.importe.sum()

    return dict(
        facturacion=round(float(win.importe.sum())),
        var_pct=var_pct,
        pedidos=int(len(win)),
        ticket=round(float(ventas_.importe.mean())) if len(ventas_) else 0,
        clientes=int(win.cliente.nunique()),
        devoluciones=round(float(dev)),
        dev_pct=round(float(dev / bru * 100), 1) if bru else 0.0,
        desde=str(desde.date()),
        hasta=str(hasta.date()),
    )


def ventas(df: pd.DataFrame,
           limite: int = 25,
           offset: int = 0,
           q: str | None = None,
           comercial: str | None = None,
           desde: str | pd.Timestamp | None = None,
           hasta: str | pd.Timestamp | None = None,
           marca: str | None = None,
           orden: str = "fecha") -> dict:
    """El explorador: las últimas ventas registradas, con filtros y paginación.

    `orden` decide qué significa «la última»:

        "fecha"     por fecha del pedido, de la más nueva a la más vieja.
        "registro"  por el orden de la hoja, de la última fila escrita hacia
                    arriba. Esto es «lo último que se ha REGISTRADO»: si acabas
                    de escribir una línea en Drive, sale la primera, tenga la
                    fecha que tenga.

    Los dos desempatan por `fila_origen` (la posición original en la hoja), así
    que el orden es determinista y, dentro de un mismo día, lo último escrito
    sale antes. Desempatar por `pedido_id` —como se hacía— era arbitrario: el
    número de pedido no dice nada sobre cuándo se escribió la fila.

    `marca` filtra por la etiqueta que puso la puerta de calidad:

        None / ""        todas las ventas (por defecto)
        "senalados"      SOLO los pedidos anómalos
        "devoluciones"   SOLO las devoluciones
        "sin_senalados"  todas menos los anómalos (lo que ven los KPI)

    El filtro «senalados» no es un adorno. Los KPI excluyen el pedido anómalo y
    la puerta dice «que lo mire un humano»; si para mirarlo hubiera que pasar
    300 páginas ordenadas por fecha, no lo miraría nadie y señalarlo sería lo
    mismo que borrarlo en silencio. Con este filtro está a un clic.

    Función pura: no toca red ni disco, no muta el DataFrame de entrada.
    """
    d = df
    if marca == "senalados":
        d = d[d.sospechoso] if "sospechoso" in d.columns else d.iloc[0:0]
    elif marca == "devoluciones":
        d = d[d.es_devolucion] if "es_devolucion" in d.columns else d.iloc[0:0]
    elif marca == "sin_senalados":
        d = _base(d)

    if desde is not None:
        d = d[d.fecha >= pd.Timestamp(desde)]
    if hasta is not None:
        d = d[d.fecha <= pd.Timestamp(hasta)]
    if comercial:
        d = d[d.comercial == comercial]
    if q and q.strip():
        ql = q.strip().lower()
        m = pd.Series(False, index=d.index)
        for c in _COL_BUSQUEDA:
            if c in d.columns:
                m |= d[c].astype(str).str.lower().str.contains(ql, regex=False, na=False)
        d = d[m]

    total = int(len(d))
    importe_filtrado = round(float(d.importe.sum())) if total else 0

    offset = max(0, int(offset))
    limite = max(1, min(int(limite), 200))          # techo: no servir 10.000 filas

    if "fila_origen" in d.columns:
        claves = ["fila_origen"] if orden == "registro" else ["fecha", "fila_origen"]
    else:                                            # datos viejos, sin la columna
        claves = ["fecha", "pedido_id"]
    pagina = d.sort_values(claves, ascending=False)
    pagina = pagina.iloc[offset:offset + limite]

    filas = [
        dict(
            pedido_id=str(r.pedido_id),
            fecha=str(pd.Timestamp(r.fecha).date()),
            comercial=str(r.comercial),
            zona=str(r.zona),
            cliente=str(r.cliente),
            tipo_cliente=str(r.tipo_cliente),
            producto=str(r.producto),
            familia=str(r.familia),
            cantidad=int(r.cantidad),
            precio=round(float(r.precio_unitario), 2),
            importe=round(float(r.importe), 2),
            devolucion=bool(getattr(r, "es_devolucion", False)),
            senalado=bool(getattr(r, "sospechoso", False)),
        )
        for r in pagina.itertuples()
    ]

    return dict(total=total, offset=offset, limite=limite, orden=orden,
                importe=importe_filtrado, filas=filas)


def payload(df: pd.DataFrame) -> dict:
    """Todo lo que el dashboard necesita hoy, calculado al vuelo.

    Ni un porcentaje, ni un ranking guardado: solo agregados que el navegador no
    puede recalcular por su cuenta (necesitaría los 10.000 pedidos). Todo lo
    derivado (%, variaciones, barras) lo hace el navegador.

    NO incluye el informe de calidad: eso lo sirve /api/calidad, porque las
    incidencias se fijan al limpiar y no se pueden recomputar a partir del
    dataset limpio (las filas descartadas ya no están).

    Tampoco incluye las filas del explorador: esas se piden aparte y paginadas
    a /api/ventas. Meter 10.000 filas aquí sería volver al payload congelado.
    """
    return dict(
        kpi=kpis(df),  # ventana por defecto: últimos 12 meses
        mes=serie_mensual(df),
        familia=top(df, "familia"),
        producto=top(df, "producto"),
        comercial=top(df, "comercial"),
        zona=top(df, "zona"),
        tipo=top(df, "tipo"),
        clientes=top(df, "clientes"),
        rango=[str(_base(df).fecha.min().date()), str(_base(df).fecha.max().date())],
        actualizado=str(pd.Timestamp.now().date()),
    )
