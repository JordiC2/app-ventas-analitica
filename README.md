# Electro Ponent · Cuadro de mando comercial

El notebook `Ventas_01_dashboard.ipynb` era una **foto**: un HTML con los datos
congelados dentro. Esto es la **app**: la misma pantalla, pero los datos salen de
una **hoja de Google Drive**, pasan por la puerta de calidad, y los KPI se
calculan al vuelo en cada petición.

## Arrancar

En Windows, doble clic:

| Fichero | Qué hace |
|---|---|
| `arrancar.bat` | Levanta todo y abre el dashboard en el navegador. |
| `actualizar.bat` | Reconstruye tras tocar código, y fuerza una relectura de Drive. |
| `parar.bat` | Para el contenedor y libera el puerto 8000. |
| `diagnostico.bat` | «He añadido un pedido y no lo veo»: te dice qué le pasó. |

O a mano, en cualquier sistema:

```bash
docker compose up
```

Sin configuración extra, porque la hoja es pública:

1. **Ingesta** — baja la hoja de Drive y la pasa por la puerta de calidad.
2. **pytest** — el número de oro + los invariantes. **Si fallan, la API no arranca.**
3. **API** — FastAPI en `http://localhost:8000`.

### Actualizar los datos: el botón

Los comerciales editan la hoja en Drive. Tú pulsas **Actualizar dashboard**
(arriba a la derecha) y el dashboard se repinta sin recargar la página. No hace
falta reiniciar nada.

El botón hace tres cosas, en este orden:

1. Baja la hoja de Drive.
2. **Compara la huella de los DATOS** con la del dato que ya teníamos.
3. Si es la misma, dice «Sin cambios en Drive» y no reprocesa nada. Si cambió,
   la pasa por la puerta y te dice cuántos pedidos y cuántos euros ha cambiado.

## De dónde vienen los datos

La hoja es de **Google Sheets nativa** y está compartida como «cualquiera con el
enlace, lector». Por eso no hacen falta credenciales:

```
https://docs.google.com/spreadsheets/d/<ID>/export?format=xlsx
```

Para apuntar a otra hoja, cambia `VENTAS_DRIVE_ID` en `docker-compose.yml`. Nada más.

### La huella es de los DATOS, no del fichero

Google **regenera el .xlsx en cada exportación**: el zip lleva timestamps dentro,
así que los bytes cambian aunque los datos sean idénticos. Si detectáramos
cambios hasheando el fichero, el botón diría «datos nuevos» cada vez que lo
pulsaras, y sería mentira.

Por eso `pipeline/drive.huella_datos()` hashea la tabla ya parseada. Misma tabla
→ misma huella, la exporte Google cuando la exporte.

### Tres orígenes, y la pantalla siempre dice cuál

| Origen | Cuándo | Qué ves |
|---|---|---|
| `drive` | Lo normal. | Nada especial. |
| `cache` | Drive no responde. | Banner ámbar: «Drive no responde, estás viendo el dato del …». |
| `referencia` | Ni Drive ni caché (primer arranque sin internet). | Banner ámbar fuerte: «son datos de ejemplo, NO los pedidos reales». |

Un dashboard que enseña datos viejos sin avisar es peor que uno que no arranca.

## La forma del proyecto

```
core/          LÓGICA PURA. Ni Excel, ni Drive, ni red, ni base de datos.
  calidad.py   LA PUERTA. limpiar(df) -> (df_limpio, incidencias). No abre ficheros.
  negocio.py   Productos, perfiles, y las definiciones de los KPI.
  metricas.py  KPIs, series, desgloses y el explorador. Funciones puras.
  datos.py     cargar_ventas() y guardar_ventas(). Una función cada una.
pipeline/
  drive.py     EL ÚNICO módulo que sabe que existe la red.
  ingesta.py   Baja de Drive, llama a core/calidad, guarda el resultado.
  diagnostico.py  Veredicto fila a fila: por qué tu pedido no sale.
api/
  main.py      FastAPI. Lee /data, llama a /core, sirve /static.
static/
  index.html   El dashboard, consumiendo la API con fetch() + botón Actualizar.
  nuevo.html   Alta de venta: el formulario de Apps Script, embebido.
data/
  referencia/  El Excel congelado del notebook. FIXTURE: no se toca.
  cache/       Lo último que bajó de Drive, para cuando Drive no responda.
tests/
  test_calidad.py     Pureza + invariantes sobre el dato vivo.
  test_referencia.py  Los 7 chequeos del notebook, contra el fixture.
  test_explorador.py  Orden, filtros, paginación y el señalado visible.
```

### Dónde está el trabajo de verdad: `core/calidad.py`

La puerta de calidad es `core/`, **no** `pipeline/`. `limpiar(df)` es una función
**pura**: recibe un DataFrame sucio, devuelve uno limpio y la lista de
incidencias. No abre ficheros, no sabe que existe Drive, no sabe que existe
Supabase. Se prueba con la red apagada y sin ningún fichero:

```python
import pandas as pd
from core.calidad import limpiar

sucio = pd.DataFrame([...])   # tres filas inventadas, una duplicada
limpio, incidencias = limpiar(sucio)
```

Si para probar la puerta hiciera falta un Excel, la puerta estaría mal puesta.

### Las tres reglas de negocio (tal cual, sin "mejorarlas")

- **Las cantidades negativas son devoluciones.** Restan, no se borran.
- **Los importes que no cuadran se descartan, no se corrigen:** no sabemos cuál
  de los tres campos (cantidad, precio, importe) miente.
- **El pedido anómalo (~973.000 €) se señala, no se borra.** Sigue en los datos
  con su marca `sospechoso`. Esa decisión la toma un humano; mientras tanto, no
  cuenta para los KPI.

> Un dato descartado en silencio es un dato perdido. Un dato descartado con su
> motivo escrito es una decisión. Por eso las incidencias son **parte de la
> respuesta** (`/api/calidad`), no un log, y el dashboard las pinta abajo del todo.

### Los KPI no se guardan: se calculan

No hay `ventas_payload.json`. Los KPI, las series y los desgloses se calculan al
vuelo en `core/metricas`. Son ~10.000 filas: es instantáneo. Guardarlos
significaría que cambiar la definición de «ticket medio» obligaría a reejecutar
el pipeline entero.

> Guarda lo que cuesta obtener. Calcula lo que cuesta poco.

(El informe de calidad **sí** se persiste, porque no se puede recalcular: las
filas descartadas ya no están en el parquet. Es el acta de una ejecución, no un KPI.)

## Añadir una venta

Botón verde **«+ Añadir venta»** arriba a la derecha → página `/nuevo`, con el
formulario de Google Apps Script embebido. Al guardar, el pedido se escribe en la
misma hoja de Drive que lee la app; el botón **«Actualizar y ver el pedido»**
cierra el ciclo y te devuelve al dashboard con el dato ya dentro.

Para cambiar de formulario, cambia `VENTAS_FORM_URL` en `docker-compose.yml`.
No se toca ni el HTML ni el código.

### Por qué el alta NO la hace esta app

Podríamos haber montado un formulario propio que escribiera en la hoja. No se ha
hecho, y es deliberado: **esta app lee y juzga; no escribe**. La hoja es de los
comerciales. Si la app también escribiera, habría dos plumas sobre el mismo papel
y dejaría de estar claro cuál es la fuente de verdad.

Por eso el alta vive en el formulario de Drive, y aquí solo se enmarca.

### Si el formulario sale en blanco

Los web apps de Apps Script mandan `X-Frame-Options` por defecto, y eso **impide
embeberlos** desde otro dominio. Si el marco sale vacío, el script tiene que
desplegarse con:

```js
return HtmlService.createHtmlOutput(...)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
```

Mientras tanto, la página siempre enseña el enlace **«¿No se ve el formulario?
Ábrelo en una pestaña»**: un cuadro blanco sin explicación es peor que un enlace.

### Las reglas, antes de escribir y no después

La página recuerda arriba las tres reglas que descartan un pedido (importe =
cantidad × precio, fecha no futura, fecha no vacía). Es el mismo informe que el
dashboard enseña abajo del todo, pero puesto **donde sirve**: delante de quien
está a punto de escribir la fila, no detrás.

## El explorador de ventas

Debajo de los gráficos, una tabla con **las últimas ventas registradas**, lo más
reciente arriba. Buscador (cliente, producto, comercial o nº de pedido), filtro
por comercial, y paginación de 25 en 25.

Va **paginado en el servidor**. Meter las ~10.000 filas en `/api/payload` sería
volver justo a lo que quitamos: un payload gordo y congelado.

### Aquí es donde se mira el pedido señalado

El desplegable de marcas tiene cuatro posiciones:

| Filtro | Qué enseña |
|---|---|
| Todas las ventas | Todo, con los señalados marcados en ámbar. |
| **Solo señaladas** | El pedido anómalo. **A un clic.** |
| Solo devoluciones | Las 22 devoluciones, en negativo. |
| Ocultar señaladas | Exactamente lo que ven los KPI. |

Ese filtro no es un adorno, y merece una explicación. La puerta de calidad
**señala** el pedido de ~973.000 € en vez de borrarlo, y dice «que lo mire un
humano». Los KPI lo excluyen. Pero el pedido es del **09/06/2025**: ordenando por
fecha está en la página 300, y si para mirarlo hay que llegar hasta ahí, no lo
mira nadie — y señalarlo acaba siendo lo mismo que borrarlo en silencio.

Con «Solo señaladas» está a un clic. Eso es lo que convierte el señalamiento en
una decisión de verdad y no en un gesto.

> `marca=sin_senalados` da **9.942 pedidos y 9.766.883 €**: exactamente las mismas
> cifras que el panel de calidad. Si algún día dejan de cuadrar, es que alguien ha
> tocado la definición de una de las dos cosas.

## Endpoints

| Método | Ruta | Qué devuelve |
|---|---|---|
| `GET` | `/` | El dashboard. |
| `GET` | `/nuevo` | Alta de venta: el formulario de Drive, embebido. |
| `GET` | `/api/payload` | KPIs, serie mensual y desgloses. |
| `GET` | `/api/calidad` | El informe de la puerta. |
| `GET` | `/api/kpi?desde=…&hasta=…` | KPIs **recalculados** para esa ventana. |
| `GET` | `/api/ventas?limite=&offset=&q=&comercial=&marca=` | El explorador: las últimas ventas, paginadas. |
| `GET` | `/api/estado` | De dónde salen los datos y de cuándo son. |
| `POST` | `/api/actualizar` | Vuelve a mirar Drive. Recarga si hay dato nuevo. |

`/api/kpi` demuestra que los números **no están guardados**: cambias las fechas y
cambian. Imposible con el HTML congelado.

```bash
curl "http://localhost:8000/api/kpi?desde=2025-01-01&hasta=2025-06-30"
curl "http://localhost:8000/api/kpi?desde=2026-01-01&hasta=2026-07-14"
```

## Los tests

```bash
pytest -q
```

**`test_referencia.py` — contra el Excel congelado (`data/referencia/`):**
los 7 chequeos de la celda 4 del notebook, incluido el número de oro:

- Tras normalizar quedan **exactamente 15 clientes** (no 63).
- No quedan duplicados, ni fechas futuras, ni importes que no cuadran.
- La facturación limpia es **9.766.883 € (± 1 €)**.
- Las devoluciones **restan**.
- **Idempotencia:** `limpiar()` dos veces == una vez.
- El pedido anómalo sigue en los datos, marcado.

Ese número no es una verdad sobre el negocio: es una verdad sobre **ese** dataset
pasado por **esta** puerta. Por eso corre contra un fixture que no cambia nunca.
Si alguien toca `core/calidad.py` y la cifra se mueve, la puerta ha cambiado de
criterio, y el test lo caza.

**`test_explorador.py` — la función pura del explorador:**
lo último arriba, la paginación no pierde ni repite filas, los filtros filtran y
se combinan, las devoluciones salen en negativo, el importe del pie es el de lo
filtrado (no el de la página), el límite tiene techo (200), y **el pedido
señalado se ve y está a un clic**.

**`test_calidad.py` — contra el dato vivo de Drive:**
ningún número fijo, solo reglas que valen con cualquier dato: la puerta es pura,
no quedan duplicados ni fechas futuras ni importes descuadrados, **no quedan dos
grafías del mismo cliente** (la generalización de «15 clientes»), los huecos están
etiquetados, las devoluciones restan, y sigue siendo idempotente.

`docker compose up` corre todo esto **antes** de arrancar la API. Si falla, la app
no levanta.

## «He añadido un pedido y no lo veo»

Doble clic en **`diagnostico.bat`**, escribe el número de pedido, y te dice qué
ha hecho la puerta con esa fila exacta:

```
  ✗ NUEVO-DESCUADRE   2026-07-14   Ferretería López
      Downlight LED 18W  ·  10 ud × 11.2 €  =  112.5 €
      → DESCARTADA · importe ≠ cantidad × precio
        cantidad × precio = 112.0 €, pero en la hoja pone 112.5 €
        (diferencia: 0.5 €)
```

Las incidencias del dashboard dicen **cuántas** filas cayó cada regla. Esto dice
**cuáles**, y por qué. Es la diferencia entre «se descartaron 53 filas» y «tu
fila se cayó porque 10 × 11,20 son 112,00 y escribiste 112,50».

Los tres motivos por los que una fila escrita a mano no aparece:

| Motivo | Cómo se arregla |
|---|---|
| `importe ≠ cantidad × precio` | Cuadra los tres números en la hoja. La puerta **no los corrige**: no sabe cuál miente. |
| `fecha posterior a hoy` | Un pedido de mañana no existe. Pon la fecha real. |
| `fecha vacía o ilegible` | Sin fecha no se puede situar el pedido en el tiempo. |

Y si el diagnóstico dice `PASA la puerta` pero sigues sin verlo: pulsa
**Actualizar dashboard**. La app no sondea Drive sola.

### Dos bugs que salieron de aquí

**La fecha de corte estaba congelada.** El notebook fijaba `HOY = 2026-07-14`
porque su dataset era congelado y así los números eran reproducibles. En una app
viva eso es un bug con fecha de caducidad: a partir del día siguiente, **todo
pedido nuevo se habría descartado** por «fecha posterior a hoy» — en una app cuya
razón de ser es enseñar los pedidos nuevos. Ahora el corte se mueve con el
calendario (`hoy_por_defecto()`), y `HOY_NOTEBOOK` se queda solo para el test de
referencia, que necesita fijarlo para que 9.766.883 € siga siendo comprobable.

**Una fecha vacía se descartaba en silencio.** El filtro `fecha <= hoy` tira los
`NaT`, pero el contador solo miraba `fecha > hoy`: la fila desaparecía sin
aparecer en ninguna incidencia. Justo lo que este proyecto dice que no se hace.
Ahora tiene su línea en el informe, y hay un test que cuenta las filas que entran,
las que salen, y exige que la diferencia esté explicada.

## De aquí a Supabase (v2)

El corte sigue siendo **una sola función**, `core/datos.cargar_ventas()`:

```python
def cargar_ventas():
    return pd.read_parquet(RUTA_LIMPIO)                       # v1, parquet
    return supabase.table("ventas").select("*").execute()    # v2, vivo
```

Si migrar obliga a tocar algo más que eso, es que la frontera estaba mal puesta.
