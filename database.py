"""
Capa de datos: productos (catálogo editable), y cada venta (carrito +
cobro híbrido) en SQLite local, con el detalle de los productos y los
pagos que la componen, para poder consultarla luego en el historial.

Modelo de cobro híbrido — PROPORCIONAL (ver app.py para el detalle):
- Cada producto tiene un precio en divisa y un recargo % para cuando
  se paga en bolívares (precio_bs = precio_divisa * (1 + recargo/100)).
- El carrito tiene dos totales de referencia: total_divisa (si todo se
  paga en divisa) y total_bs_usd_equiv (si todo se paga en bolívares,
  con el recargo de cada producto incluido).
- Cada pago cubre una fracción del total: un pago en divisa se mide
  como monto/total_divisa; un pago en bolívares se mide como
  (monto_bs/tasa)/total_bs_usd_equiv. La suma de fracciones de todos
  los pagos da el % cubierto.
- Lo que falta o sobra se expresa como fracción_restante × total_divisa
  (en divisa) y fracción_restante × total_bs_usd_equiv × tasa (en
  bolívares) — así el recargo de cada producto también se refleja en el
  saldo pendiente, no solo en el total inicial.
"""

import os
import sqlite3
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mezclilla.db")


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            precio_divisa REAL NOT NULL,
            recargo_pct REAL NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            tasa_bcv REAL NOT NULL,
            tasa_fuente TEXT,
            total_divisa REAL NOT NULL,
            total_bs_usd_equiv REAL NOT NULL,
            total_bs REAL NOT NULL,
            fraccion_pagada REAL NOT NULL,
            diferencia_divisa REAL NOT NULL,
            diferencia_bs REAL NOT NULL,
            estado TEXT NOT NULL,
            nota TEXT
        );

        CREATE TABLE IF NOT EXISTS venta_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto TEXT NOT NULL,
            cantidad REAL NOT NULL,
            precio_unit_divisa REAL NOT NULL,
            precio_unit_bs_usd_equiv REAL NOT NULL,
            subtotal_divisa REAL NOT NULL,
            subtotal_bs_usd_equiv REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            metodo TEXT NOT NULL,
            moneda TEXT NOT NULL,
            monto_ingresado REAL NOT NULL,
            monto_usd_equiv REAL NOT NULL,
            fraccion_cubierta REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS presupuestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero INTEGER NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            validez_dias INTEGER NOT NULL,
            cliente_nombre TEXT,
            cliente_telefono TEXT,
            total_divisa REAL NOT NULL,
            total_bs REAL NOT NULL,
            tasa_bcv REAL NOT NULL,
            tasa_fuente TEXT,
            nota TEXT,
            archivo TEXT
        );

        CREATE TABLE IF NOT EXISTS presupuesto_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            presupuesto_id INTEGER NOT NULL,
            producto TEXT NOT NULL,
            cantidad REAL NOT NULL,
            precio_unit_divisa REAL NOT NULL,
            precio_unit_bs REAL NOT NULL,
            subtotal_divisa REAL NOT NULL,
            subtotal_bs REAL NOT NULL,
            FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()

    # Semilla inicial de productos de prueba, solo si la tabla está vacía
    # (para no pisar productos que el usuario ya haya creado/editado).
    count = conn.execute("SELECT COUNT(*) AS n FROM productos").fetchone()["n"]
    if count == 0:
        semilla = [
            ("Bloque de arcilla 15cm", 0.58, 12.07),
            ("Saco de arena cernida grande", 0.80, 25.0),
            ("Saco de arena lavada grande", 1.00, 30.0),
            ("Cemento 42kg", 10.00, 20.0),
            ("Saco de cal líquida", 1.00, 30.0),
            ("Saco de mezclilla grande", 1.00, 30.0),
        ]
        conn.executemany(
            "INSERT INTO productos (nombre, precio_divisa, recargo_pct, activo) "
            "VALUES (?, ?, ?, 1)",
            semilla,
        )
        conn.commit()

    conn.close()


# ------------------------------------------------------------ productos
def _precio_bs(precio_divisa, recargo_pct):
    return round(precio_divisa * (1 + recargo_pct / 100.0), 4)


def listar_productos(solo_activos=True):
    conn = get_connection()
    query = "SELECT * FROM productos"
    if solo_activos:
        query += " WHERE activo = 1"
    query += " ORDER BY nombre"
    rows = conn.execute(query).fetchall()
    conn.close()
    productos = []
    for r in rows:
        d = dict(r)
        d["precio_bs_usd_equiv"] = _precio_bs(d["precio_divisa"], d["recargo_pct"])
        productos.append(d)
    return productos


def obtener_producto(producto_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["precio_bs_usd_equiv"] = _precio_bs(d["precio_divisa"], d["recargo_pct"])
    return d


def crear_producto(nombre, precio_divisa, recargo_pct):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO productos (nombre, precio_divisa, recargo_pct, activo) VALUES (?, ?, ?, 1)",
        (nombre.strip(), precio_divisa, recargo_pct),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def actualizar_producto(producto_id, nombre, precio_divisa, recargo_pct):
    conn = get_connection()
    conn.execute(
        "UPDATE productos SET nombre = ?, precio_divisa = ?, recargo_pct = ? WHERE id = ?",
        (nombre.strip(), precio_divisa, recargo_pct, producto_id),
    )
    conn.commit()
    conn.close()


def eliminar_producto(producto_id):
    """
    Baja lógica (activo = 0) en vez de borrar de verdad: así las ventas
    ya guardadas que usaron ese producto no pierden su referencia, y el
    producto simplemente deja de aparecer para nuevas ventas.
    """
    conn = get_connection()
    conn.execute("UPDATE productos SET activo = 0 WHERE id = ?", (producto_id,))
    conn.commit()
    conn.close()


def nombre_producto_existe(nombre, excluir_id=None):
    conn = get_connection()
    if excluir_id is not None:
        row = conn.execute(
            "SELECT id FROM productos WHERE nombre = ? AND id != ?", (nombre.strip(), excluir_id)
        ).fetchone()
    else:
        row = conn.execute("SELECT id FROM productos WHERE nombre = ?", (nombre.strip(),)).fetchone()
    conn.close()
    return row is not None


# --------------------------------------------------------------- ventas
def guardar_venta(carrito, tasa_bcv, tasa_fuente, pagos, nota=""):
    """
    carrito: lista de dicts {"producto", "cantidad", "precio_unit_divisa",
             "precio_unit_bs_usd_equiv"}
    pagos: lista de dicts {"metodo", "moneda", "monto_ingresado",
           "monto_usd_equiv", "fraccion_cubierta"}
    Devuelve el id de la venta creada.
    """
    total_divisa = round(sum(i["cantidad"] * i["precio_unit_divisa"] for i in carrito), 2)
    total_bs_usd_equiv = round(
        sum(i["cantidad"] * i["precio_unit_bs_usd_equiv"] for i in carrito), 2
    )
    total_bs = round(total_bs_usd_equiv * tasa_bcv, 2)

    fraccion_pagada = round(sum(p["fraccion_cubierta"] for p in pagos), 6)
    fraccion_restante = 1 - fraccion_pagada
    diferencia_divisa = round(fraccion_restante * total_divisa, 2)
    diferencia_bs = round(fraccion_restante * total_bs_usd_equiv * tasa_bcv, 2)

    if abs(fraccion_restante) <= 0.001:
        estado = "Pagado exacto"
    elif fraccion_restante > 0:
        estado = "Falta por cobrar"
    else:
        estado = "Vuelto a favor del cliente"

    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO ventas (fecha, tasa_bcv, tasa_fuente, total_divisa,
                             total_bs_usd_equiv, total_bs, fraccion_pagada,
                             diferencia_divisa, diferencia_bs, estado, nota)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            tasa_bcv,
            tasa_fuente,
            total_divisa,
            total_bs_usd_equiv,
            total_bs,
            fraccion_pagada,
            diferencia_divisa,
            diferencia_bs,
            estado,
            nota,
        ),
    )
    venta_id = cur.lastrowid

    for item in carrito:
        conn.execute(
            """
            INSERT INTO venta_items (venta_id, producto, cantidad, precio_unit_divisa,
                                      precio_unit_bs_usd_equiv, subtotal_divisa,
                                      subtotal_bs_usd_equiv)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                venta_id,
                item["producto"],
                item["cantidad"],
                item["precio_unit_divisa"],
                item["precio_unit_bs_usd_equiv"],
                round(item["cantidad"] * item["precio_unit_divisa"], 2),
                round(item["cantidad"] * item["precio_unit_bs_usd_equiv"], 2),
            ),
        )

    for p in pagos:
        conn.execute(
            """
            INSERT INTO pagos (venta_id, metodo, moneda, monto_ingresado, monto_usd_equiv,
                                fraccion_cubierta)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                venta_id, p["metodo"], p["moneda"], p["monto_ingresado"],
                p["monto_usd_equiv"], p["fraccion_cubierta"],
            ),
        )

    conn.commit()
    conn.close()
    return venta_id


def listar_ventas(desde=None, hasta=None, texto=None):
    conn = get_connection()
    query = "SELECT * FROM ventas WHERE 1=1"
    params = []
    if desde:
        query += " AND date(fecha) >= date(?)"
        params.append(desde)
    if hasta:
        query += " AND date(fecha) <= date(?)"
        params.append(hasta)
    if texto:
        query += " AND (nota LIKE ? OR estado LIKE ?)"
        like = f"%{texto}%"
        params.extend([like, like])
    query += " ORDER BY fecha DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_venta(venta_id):
    conn = get_connection()
    venta = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    items = conn.execute("SELECT * FROM venta_items WHERE venta_id = ?", (venta_id,)).fetchall()
    pagos = conn.execute("SELECT * FROM pagos WHERE venta_id = ?", (venta_id,)).fetchall()
    conn.close()
    if not venta:
        return None
    return {
        "venta": dict(venta),
        "items": [dict(i) for i in items],
        "pagos": [dict(p) for p in pagos],
    }


# ---------------------------------------------------------- presupuestos
def siguiente_numero_presupuesto():
    conn = get_connection()
    row = conn.execute("SELECT MAX(numero) AS n FROM presupuestos").fetchone()
    conn.close()
    return (row["n"] or 0) + 1


def guardar_presupuesto(numero, fecha_iso, validez_dias, cliente_nombre, cliente_telefono,
                         items, tasa_bcv, tasa_fuente, nota="", archivo=None):
    """
    items: lista de dicts {"producto", "cantidad", "precio_unit_divisa",
           "precio_unit_bs"}. precio_unit_divisa va en US$ y precio_unit_bs
           va en bolívares REALES (ya multiplicado por la tasa BCV del
           momento) — no en equivalente-US$ — para que sea consistente
           con total_bs y con lo que se muestra en el PDF.
    Devuelve el id del presupuesto creado.
    """
    total_divisa = round(sum(i["cantidad"] * i["precio_unit_divisa"] for i in items), 2)
    total_bs = round(sum(i["cantidad"] * i["precio_unit_bs"] for i in items), 2)

    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO presupuestos (numero, fecha, validez_dias, cliente_nombre,
                                   cliente_telefono, total_divisa, total_bs, tasa_bcv,
                                   tasa_fuente, nota, archivo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (numero, fecha_iso, validez_dias, cliente_nombre or "", cliente_telefono or "",
         total_divisa, total_bs, tasa_bcv, tasa_fuente, nota or "", archivo or ""),
    )
    presupuesto_id = cur.lastrowid

    for it in items:
        conn.execute(
            """
            INSERT INTO presupuesto_items (presupuesto_id, producto, cantidad,
                                            precio_unit_divisa, precio_unit_bs,
                                            subtotal_divisa, subtotal_bs)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                presupuesto_id, it["producto"], it["cantidad"],
                it["precio_unit_divisa"], it["precio_unit_bs"],
                round(it["cantidad"] * it["precio_unit_divisa"], 2),
                round(it["cantidad"] * it["precio_unit_bs"], 2),
            ),
        )

    conn.commit()
    conn.close()
    return presupuesto_id


def actualizar_archivo_presupuesto(presupuesto_id, archivo):
    conn = get_connection()
    conn.execute("UPDATE presupuestos SET archivo = ? WHERE id = ?", (archivo, presupuesto_id))
    conn.commit()
    conn.close()


def listar_presupuestos(desde=None, hasta=None, texto=None):
    conn = get_connection()
    query = "SELECT * FROM presupuestos WHERE 1=1"
    params = []
    if desde:
        query += " AND date(fecha) >= date(?)"
        params.append(desde)
    if hasta:
        query += " AND date(fecha) <= date(?)"
        params.append(hasta)
    if texto:
        query += " AND (cliente_nombre LIKE ? OR nota LIKE ?)"
        like = f"%{texto}%"
        params.extend([like, like])
    query += " ORDER BY numero DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_presupuesto(presupuesto_id):
    conn = get_connection()
    p = conn.execute("SELECT * FROM presupuestos WHERE id = ?", (presupuesto_id,)).fetchone()
    items = conn.execute(
        "SELECT * FROM presupuesto_items WHERE presupuesto_id = ?", (presupuesto_id,)
    ).fetchall()
    conn.close()
    if not p:
        return None
    return {"presupuesto": dict(p), "items": [dict(i) for i in items]}
