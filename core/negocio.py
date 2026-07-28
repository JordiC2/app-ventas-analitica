"""
El negocio · Electro Ponent SL
================================

Antes de tocar un dato hay que saber QUÉ se vende y A QUIÉN. Si no, el análisis
sale de la estadística y no del negocio, y esos dos no son lo mismo.

Aquí viven las entidades estables (productos, comerciales, zonas, clientes,
perfiles de compra) y las definiciones de los KPI. Ni Excel, ni red, ni base de
datos: constantes puras que el resto del `core/` importa.

Tres cosas que hay que tener en la cabeza, porque los datos las reproducen:

- El distribuidor compra volumen y con descuento. El instalador, poco y a precio.
  Un ranking por unidades y otro por importe NO dan el mismo top.
- En agosto no se factura. La obra para. Un mes malo en agosto no es un mes malo.
- Las devoluciones son ventas que se deshacen. No son ruido: son un número del
  negocio.
"""

# ── Catálogo: producto -> (precio_base, familia) ────────────────────────────
PRODUCTOS = {
    "Cable RZ1-K 3x2.5":       (2.40,  "Cable"),
    "Cable H07V-K 1x6":        (1.15,  "Cable"),
    "Cuadro eléctrico 24 mód": (85.00, "Cuadros"),
    "Cuadro eléctrico 12 mód": (48.00, "Cuadros"),
    "Magnetotérmico 2P 25A":   (14.50, "Protección"),
    "Diferencial 2P 40A 30mA": (32.00, "Protección"),
    "Luminaria LED 40W":       (28.90, "Iluminación"),
    "Downlight LED 18W":       (11.20, "Iluminación"),
    "Tubo corrugado M20":      (0.45,  "Canalización"),
    "Bandeja rejilla 100mm":   (9.80,  "Canalización"),
}

# ── Equipo comercial y su zona (Barcelona lleva DOS) ────────────────────────
COMERCIALES = ["Marta Ibáñez", "Xavier Puig", "Lucía Ferrer", "Andreu Roca", "Nuria Sanz"]

ZONAS = {
    "Marta Ibáñez": "Barcelona",
    "Xavier Puig":  "Girona",
    "Lucía Ferrer": "Tarragona",
    "Andreu Roca":  "Lleida",
    "Nuria Sanz":   "Barcelona",
}

# ── Cartera de clientes: (nombre, tipo) ─────────────────────────────────────
CLIENTES = [
    ("Instal·lacions Vidal SL", "Instalador"),   ("Electro Ribas SA", "Distribuidor"),
    ("Muntatges Segarra", "Instalador"),          ("Ferretería López", "Retail"),
    ("Grup Elèctric Ponent", "Distribuidor"),     ("Tècnics Costa Brava", "Instalador"),
    ("Subministres Camp SL", "Distribuidor"),      ("Bricolatge Mestre", "Retail"),
    ("Enginyeria Molins", "Ingeniería"),           ("Instal·lacions Bages", "Instalador"),
    ("Comercial Delta SA", "Distribuidor"),        ("Electricitat Garrigues", "Instalador"),
    ("Obres i Serveis Vallès", "Constructora"),    ("Ferreteria Central", "Retail"),
    ("Projectes Tècnics BCN", "Ingeniería"),
]

# Número de clientes reales. La puerta de calidad tiene que dejar EXACTAMENTE
# estos, no las 63 grafías con las que llegan del Excel.
N_CLIENTES = len(CLIENTES)

# ── Perfil de compra por tipo de cliente. Esto ES el negocio ────────────────
# El distribuidor compra 15x más que la ingeniería, y con 6x más descuento.
# Por eso el ranking por UNIDADES y el ranking por IMPORTE no coinciden.
PERFIL = {
    "Distribuidor": dict(volumen=120, dto=0.18),
    "Constructora": dict(volumen=40,  dto=0.12),
    "Instalador":   dict(volumen=25,  dto=0.08),
    "Retail":       dict(volumen=15,  dto=0.05),
    "Ingeniería":   dict(volumen=8,   dto=0.03),
}

# ── Definiciones de los KPI (documentadas, no mágicas) ──────────────────────
# Se calculan al vuelo en core/metricas.py. Aquí solo se declara qué significan.
KPI = {
    "facturacion":  "Suma de importe de las filas NO señaladas. Las devoluciones "
                    "restan (importe negativo); el pedido anómalo no cuenta.",
    "pedidos":      "Número de líneas de pedido en la ventana.",
    "ticket":       "Importe medio por pedido, excluyendo devoluciones.",
    "clientes":     "Clientes distintos con al menos un pedido en la ventana.",
    "devoluciones": "Suma (en positivo) del importe de las devoluciones.",
    "dev_pct":      "Devoluciones sobre la facturación bruta (sin devoluciones).",
    "var_pct":      "Variación de facturación frente a la ventana anterior de "
                    "igual longitud.",
}

# La columna sobre la que se agrega cada desglose del dashboard, y cuántos
# elementos muestra. Cambiar aquí un top-8 por un top-10 no toca ningún dato.
DESGLOSES = {
    "familia":   8,
    "producto": 10,
    "comercial": 8,
    "zona":      8,
    "tipo":      8,   # se agrega por tipo_cliente
    "clientes": 10,   # se agrega por cliente
}
