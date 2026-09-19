# Mezclilla San Miguel C.A — Control de Cobro Híbrido

Aplicación de escritorio sencilla para resolver el cobro combinado en
divisa y bolívares a tasa BCV: arma el carrito con los productos,
calcula el total en ambas monedas, permite registrar pagos parciales
en distintos métodos (efectivo USD, Zelle, efectivo Bs, Pago Móvil,
transferencia) y muestra en el momento si falta dinero por cobrar o
sobra vuelto. Guarda cada venta en un historial local para consultarla
después. Los productos y sus precios se administran directamente
desde la app (pestaña "Productos"), sin tocar código.

### Cómo se calcula el cobro híbrido (modelo proporcional)

Cada producto tiene un precio en divisa y su propio % de recargo para
cuando esa parte se paga en bolívares:

```
precio en Bs (equiv. US$) = precio en divisa × (1 + recargo% / 100)
```

Por ejemplo, el saco de mezclilla grande cuesta $1.00 en divisa y
tiene 30% de recargo → $1.30 equivalente si se paga en bolívares. Ese
$1.30 convertido a bolívares reales, a la tasa BCV del momento, es lo
que se muestra en la columna "Precio Bs" del carrito y junto al
producto seleccionado — así siempre se ve el precio base en divisa
**y** su equivalente real en bolívares uno junto al otro. Cada
producto puede tener un % distinto.

El carrito tiene dos totales: el **total en divisa** (si todo se paga
en divisa) y el **total en bolívares** (si todo se paga en bolívares,
con el recargo de cada producto ya incluido, a la tasa BCV del
momento).

Cuando el cliente combina métodos de pago, cada pago cubre una
**fracción del total**: lo que paga en divisa se compara contra el
total-en-divisa, y lo que paga en bolívares se compara contra el
total-en-bolívares. Así, sin importar el orden ni la combinación de
pagos, lo que falta o sobra queda calculado de forma justa en ambas
monedas — el recargo de cada producto se refleja también en el saldo
pendiente, no solo en el total inicial. Ejemplo: si el total es $5.80
en divisa / $6.50 en bolívares, y el cliente paga $3 en efectivo, esos
$3 cubren 3/5.80 = 51.7% del total; el 48.3% restante se cobra al
precio en bolívares: 48.3% de $6.50 ≈ $3.14 equivalente, convertido a
Bs a la tasa del día.

En la pestaña "Nueva venta", debajo de "Diferencia" hay un recuadro
**"Detalle del cálculo (para verificar que todo esté bien)"** que
muestra, paso a paso, cómo se llegó a ese número: los dos totales
(divisa y bolívares), qué fracción cubrió cada pago y cómo se sumaron,
y la cuenta exacta de la fracción restante multiplicada por cada
total. Se actualiza solo con cada producto o pago que agregues, para
que se pueda verificar a mano que el resultado es correcto.

### Presupuestos (cotizaciones) en PDF

Desde la pestaña **"Presupuesto"** puedes armar una cotización para un
cliente (sin que quede registrada como una venta cerrada): agregas los
productos con su cantidad igual que en "Nueva venta", opcionalmente
pones el nombre y teléfono del cliente, cuántos días es válido el
presupuesto (por defecto 3) y una nota adicional. Al presionar
**"Generar presupuesto (PDF)"** se crea un PDF completo, listo para
enviar o imprimir, que incluye:

- El logo y el nombre de Mezclilla San Miguel C.A, y el RIF
  `J-30659613-5`.
- Número de presupuesto correlativo, fecha de emisión y fecha hasta la
  que es válido.
- Los datos del cliente (si se ingresaron).
- Una tabla con cada producto: cantidad, precio unitario **solo en
  dólares** (US$) y su subtotal — el presupuesto no muestra precios en
  bolívares, porque esa conversión cambia con la tasa BCV del día y no
  tiene sentido "congelarla" en un documento que puede usarse varios
  días después.
- El total en divisa.
- Las condiciones: que los precios están en dólares y **sujetos a
  cambios sin previo aviso**, que si el cliente paga en bolívares el
  monto se convierte a la tasa BCV vigente el día del pago (se deja la
  tasa de referencia del día en que se emitió el presupuesto, solo
  como referencia), y la validez del presupuesto.

El PDF se guarda donde tú elijas (por defecto, en una carpeta
`presupuestos` dentro de esta misma carpeta de la app) y se abre
automáticamente para que lo revises. Cada presupuesto generado queda
además en la lista **"Presupuestos generados"**, donde puedes
buscarlo por cliente o nota, y volver a **abrirlo o imprimirlo**
cuando quieras (si el archivo PDF original ya no está donde se
guardó, la app lo regenera automáticamente a partir de los datos
guardados). "Imprimir" intenta enviarlo directo a la impresora
predeterminada; si el sistema no lo permite, abre el PDF para que lo
imprimas manualmente con Cmd+P (Mac) o Ctrl+P (Windows).

## Qué NO hace (por ahora)

No maneja inventario, no lleva clientes ni cuentas por cobrar, y el
presupuesto/recibo no es una factura fiscal (SENIAT) — son documentos
internos de la empresa.

## Probarla ahora en tu Mac

1. Instala Python 3.10 o superior si no lo tienes (`python3 --version`
   en la Terminal para verificar).
2. En la Terminal, dentro de esta carpeta:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```

3. Se abre la ventana de la app, con el logo de Mezclilla San Miguel
   arriba. A su lado verás la tasa BCV (intenta traerla sola de
   internet; si no hay conexión, la ingresas a mano en el campo de la
   derecha y presionas "Usar").

**Si ya tenías la app corriendo de antes**, solo actualiza el código
(sobrescribe los archivos con los de este zip) y vuelve a correr
`pip install -r requirements.txt` una vez, porque se agregaron
librerías nuevas (`beautifulsoup4` para el respaldo de la tasa,
`Pillow` para el logo, y ahora `reportlab` para generar los PDF de
presupuesto). No hace falta rehacer el `.venv`.

### Cómo se usa

- **Nueva venta**: elige el producto y la cantidad, agrégalo al
  carrito (si repites un producto, suma la cantidad en vez de
  duplicar la fila). Debajo verás el total del carrito. Luego agrega
  cada pago que te vaya dando el cliente (elige el método, escribe el
  monto en la moneda de ese método). La app te dice en tiempo real si
  falta cobrar algo o si hay que dar vuelto, en divisa y en bolívares.
  Cuando el cobro está completo, presiona "Cerrar venta y guardar".
- **Productos**: crea, edita o elimina productos del catálogo. Puedes
  ingresar el precio en divisa y el % de recargo (y la app calcula el
  precio en Bs), **o** ingresar el precio en divisa y el precio en Bs
  directamente (y la app calcula el % de recargo solo) — lo que
  escribas al final es lo que manda, así que puedes ir y venir entre
  los dos campos hasta que quede como quieres. Eliminar un producto no
  afecta las ventas ya guardadas que lo usaron (solo deja de aparecer
  para ventas nuevas).
- **Historial**: todas las ventas cerradas quedan guardadas ahí, con
  filtro por fecha o por texto. Doble clic sobre una venta para ver el
  detalle de productos y pagos.

La tasa BCV, el catálogo de productos y el historial de ventas quedan
guardados en esta misma carpeta (`rate_cache.json` y `mezclilla.db`)
para que la próxima vez que abras la app siga teniendo esa
información.

### De dónde saca la tasa BCV

Intenta, en este orden, hasta que una funcione:

1. **dolarapi.com** — la API que indicaste.
2. **pydolarve.org** — API pública alternativa, como respaldo.
3. **bcv.org.ve** — si las dos anteriores fallan, lee directamente la
   página oficial del Banco Central (mismo enfoque que tu script de
   referencia en Node/cheerio, aquí adaptado a Python con
   `requests` + `BeautifulSoup`). Es el respaldo más robusto porque no
   depende de que un tercero mantenga su API activa, pero es más
   frágil ante cambios en el HTML del sitio del BCV.

Si las tres fallan (sin internet, por ejemplo), usa la última tasa
guardada, o la que ingreses manualmente.

La tasa siempre se redondea a **2 decimales** (como la publica el
propio BCV), venga de donde venga — automática, de la última guardada,
o la que escribas a mano — y ese es el valor que se usa en todos los
cálculos de la venta.

El botón **"Actualizar tasa"** consulta esas fuentes en internet, lo
que puede tardar unos segundos (o más si hay que caer al respaldo del
sitio del BCV). Mientras consulta, el botón se deshabilita y muestra
"Actualizando..." con una barra de progreso, para que quede claro que
la app está trabajando y no se congeló; el resto de la ventana sigue
respondiendo normalmente mientras tanto.

## Empacarla como programa de Windows (.exe)

Esto debe hacerse **en una PC con Windows** (no se puede generar un
.exe de Windows desde Mac ni desde Linux). Los pasos cambian según la
versión de Windows de la PC **donde va a correr la app** (no
necesariamente donde la compilas):

### Si esa PC tiene Windows 8.1, 10 u 11

1. Copia esta carpeta completa a la PC con Windows.
2. Instala Python normal (<https://www.python.org/downloads/>,
   marcando "Add Python to PATH" durante la instalación).
3. Haz doble clic en `build_windows.bat` (o ábrelo desde una consola
   CMD parado en esta carpeta) y responde "2" cuando pregunte la
   versión de Windows.
4. Al terminar, el programa queda en `dist\MezclillaPOS.exe`. Cópialo
   a cualquier PC con Windows 8.1+ y ábrelo con doble clic — no
   necesita tener Python instalado.

### Si esa PC tiene Windows 7 — leer con cuidado

Windows 7 necesita un Python más viejo, y una versión más vieja de la
herramienta que arma el `.exe` (PyInstaller), porque las versiones
actuales de ambos ya no funcionan ahí. Esto ya está resuelto en el
proyecto, pero hay que seguir los pasos exactos:

1. En la PC (idealmente la misma de Windows 7, para evitar sorpresas —
   ver nota abajo), instala **Python 3.8.10** — no una versión más
   nueva — desde
   <https://www.python.org/downloads/release/python-3810/>. Baja el
   instalador de 64 bits (`python-3.8.10-amd64.exe`) o el de 32 bits
   (`python-3.8.10.exe`) según corresponda: en esa misma PC, abre el
   Panel de control → Sistema y seguridad → Sistema, y busca "Tipo de
   sistema" (dice "Sistema operativo de 32 bits" o "de 64 bits"). En
   el instalador marca **"Add Python 3.8 to PATH"**.
2. Copia esta carpeta completa a la PC con Windows 7.
3. Haz doble clic en `build_windows.bat`, confirma que dice Python
   3.8.x cuando lo pregunte, y responde **"1"** cuando pregunte la
   versión de Windows. Esto instala las versiones fijadas en
   `requirements-win7.txt` (no las de `requirements.txt`, que ya son
   demasiado nuevas para Windows 7) y una versión vieja de PyInstaller
   (4.10) compatible.
4. El `.exe` queda en `dist\MezclillaPOS.exe`. **Pruébalo en la propia
   PC de Windows 7 antes de darlo por bueno** — aunque compiles en una
   PC más nueva, lo más seguro es compilar directamente en la de
   Windows 7 (o una igual de vieja), porque un `.exe` armado en
   Windows 10/11 a veces termina dependiendo de piezas del sistema que
   Windows 7 no tiene, aunque el Python usado sea el correcto.

**Por qué pasa esto**: Python dejó de dar soporte oficial a Windows 7
a partir de la versión 3.9 (versiones más nuevas simplemente no
arrancan ahí — falta un componente del sistema, "api-ms-win-core-path
-l1-1-0.dll"). Por la misma razón, varias de las librerías que usa
esta app (`ttkbootstrap`, `requests`, `Pillow`, `reportlab`) subieron
su versión mínima de Python a 3.9 o 3.10 en sus lanzamientos más
recientes — por eso `requirements-win7.txt` fija versiones específicas
más viejas de cada una, ya verificadas como compatibles con Python
3.8. Y PyInstaller, desde la versión 5, solo dice soportar "Windows 8
en adelante" — la 4.10 es la última que menciona que Windows 7
"debería funcionar" (sin garantía oficial, pero es lo mejor
disponible).

La consulta de la tasa BCV por internet (HTTPS) debería funcionar
igual en Windows 7 sin nada adicional, porque Python trae su propio
motor de conexión segura (no depende de que Windows 7 tenga
actualizado su propio soporte de TLS). Si de todos modos falla la
conexión en esa PC y en ninguna otra parte de esa red hay problemas de
internet, instalar el "Microsoft Visual C++ Redistributable" más
reciente y tener Windows 7 con el Service Pack 1 y las actualizaciones
al día suele resolverlo.

## Ajustes que probablemente quieras hacer después

- Cambiar la lista de métodos de pago (`METODOS_PAGO` en `app.py`) si
  agregan o quitan alguno.
- Si más adelante quieren llevar inventario, clientes o reportes de
  caja, se puede agregar sin rehacer lo que ya existe.

## Archivos del proyecto

- `app.py` — la interfaz y toda la lógica de la pantalla, incluyendo
  las pestañas de "Presupuesto" y "Productos".
- `presupuesto_pdf.py` — genera el PDF del presupuesto (logo, datos
  fiscales, tabla de productos, totales, tasa BCV y condiciones) con
  la librería `reportlab`.
- `bcv_rate.py` — obtiene la tasa BCV de internet (dolarapi.com →
  pydolarve.org → scraping a bcv.org.ve → respaldo manual/cache).
- `database.py` — guarda y consulta los productos, el historial de
  ventas y los presupuestos generados (SQLite, un solo archivo
  `mezclilla.db`, sin necesidad de instalar ninguna base de datos
  aparte).
- `resources/logo.png` — el logo de Mezclilla San Miguel usado en la
  ventana de la app y en los PDF de presupuesto.
- `resources/scrapper_bcv_reference.js` — el script de referencia que
  enviaste (Node/cheerio); se dejó guardado aquí como documentación,
  no lo usa la app (la lógica equivalente está en `bcv_rate.py`).
- `requirements.txt` — librerías necesarias (versiones normales, para
  Mac o Windows 8.1+).
- `requirements-win7.txt` — las mismas librerías, pero en versiones
  fijadas compatibles con Windows 7 + Python 3.8.10 (ver la sección
  "Empacarla como programa de Windows" más arriba).
- `build_windows.bat` — script para generar el .exe en Windows.
- `presupuestos/` — se crea sola la primera vez que generas un
  presupuesto; ahí se guardan los PDF por defecto.

## Nota sobre versiones anteriores

Si ya habías probado una versión anterior de la app y tienes un
archivo `mezclilla.db` de esa prueba en esta carpeta, bórralo antes de
abrir esta versión: el esquema de la base de datos cambió otra vez
(ahora incluye la tabla de productos editables) y no es compatible con
el archivo viejo. Al borrarlo y abrir la app, se vuelve a crear con
los 6 productos de prueba ya cargados (puedes editarlos o borrarlos
desde la pestaña "Productos").

**Si ya tenías la versión anterior con el catálogo de productos
editable** (la que agregó la pestaña "Productos"), esta actualización
sí es compatible: no necesitas borrar `mezclilla.db`. Solo se agregan
las tablas nuevas para guardar los presupuestos generados; tus
productos y tu historial de ventas quedan intactos.
