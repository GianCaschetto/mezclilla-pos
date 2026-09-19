"""
Mezclilla San Miguel - Control de Cobro Híbrido (USD / Bs a tasa BCV)

Aplicación de escritorio sencilla para resolver el problema de cobrar
combinando divisa (efectivo USD, Zelle) y bolívares (efectivo, Pago
Móvil, transferencia) en un mismo cobro, usando la tasa BCV del día.

Cómo se calcula el cobro híbrido (modelo proporcional)
--------------------------------------------------------
Cada producto tiene un precio en divisa y un recargo % propio para
cuando esa parte se paga en bolívares (precio_bs = precio_divisa ×
(1 + recargo/100) — cada producto puede tener un recargo distinto).

El carrito tiene dos totales: total en divisa (si todo se paga en
divisa) y total en bolívares (si todo se paga en bolívares, ya con el
recargo de cada producto incluido, a la tasa BCV del momento).

Cuando el cliente combina métodos de pago, cada pago cubre una
fracción del total: lo pagado en divisa se compara contra el
total-en-divisa, y lo pagado en bolívares se compara contra el
total-en-bolívares. Así, sin importar el orden ni la combinación de
pagos, lo que falta o sobra queda calculado de forma justa en ambas
monedas — el recargo de cada producto se refleja también en el saldo
pendiente, no solo en el total inicial.

Ejecutar:
    python app.py

Requiere: ttkbootstrap, requests, beautifulsoup4, Pillow (ver
requirements.txt)
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

import ttkbootstrap as tb
from ttkbootstrap.constants import *

import bcv_rate
import database
import presupuesto_pdf

METODOS_PAGO = {
    "Efectivo USD": "USD",
    "Zelle": "USD",
    "Efectivo Bs": "Bs",
    "Pago Móvil": "Bs",
    "Transferencia": "Bs",
}

EPS = 0.01  # margen (en US$) para considerar "pagado exacto"

def _base_dir():
    """Carpeta donde viven los datos de la app (BD, cache, PDFs, logo).

    Al empaquetar con PyInstaller --onefile, sys.executable apunta al
    .exe real, pero __file__ apunta a una carpeta temporal que se borra
    al cerrar el programa (_MEIPASS) — si usáramos __file__ aquí, la
    base de datos, el cache de la tasa y los presupuestos generados se
    perderían cada vez que se cierra la app. Por eso: si está "frozen"
    (empaquetado), se usa la carpeta del .exe; si no, la del script.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
LOGO_PATH = os.path.join(BASE_DIR, "resources", "logo.png")
PRESUPUESTOS_DIR = os.path.join(BASE_DIR, "presupuestos")


def fmt_usd(v):
    return f"$ {v:,.2f}"


def fmt_bs(v):
    return f"Bs {v:,.2f}"


def abrir_archivo(path):
    """Abre un archivo con el visor/aplicación predeterminada del sistema."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(path)  # solo existe/corre en Windows
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


def imprimir_archivo(path):
    """
    Intenta enviar el archivo directo a la impresora predeterminada del
    sistema. Si no se puede (o el sistema no lo soporta bien, como suele
    pasar en Mac con PDFs), devuelve False para que quien llame decida
    abrir el archivo y avisar al usuario que imprima manualmente
    (Cmd+P / Ctrl+P) desde el visor.
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(path, "print")  # noqa: solo corre en Windows
            return True
        elif sys.platform == "darwin" or sys.platform.startswith("linux"):
            subprocess.run(["lpr", path], check=True)
            return True
    except Exception:
        return False
    return False


class MezclillaApp(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly")
        self.title("Mezclilla San Miguel C.A - Control de Cobro")
        self.geometry("1060x820")
        self.minsize(940, 700)
        self._set_icon()

        database.init_db()

        self.tasa_actual = None
        self.tasa_fuente = None
        self.tasa_es_manual = False
        self.productos = []  # cache en memoria de database.listar_productos()
        self.carrito = []
        self.pagos_actuales = []

        self._build_header()
        self._build_tabs()

        self._cargar_productos()
        self._cargar_tasa_inicial()

    # -------------------------------------------------------------- icono/logo
    def _set_icon(self):
        if os.path.exists(LOGO_PATH):
            try:
                self._icon_img = tk.PhotoImage(file=LOGO_PATH)
                self.iconphoto(True, self._icon_img)
            except Exception:
                pass

    def _build_header(self):
        header = tb.Frame(self, padding=(10, 6), bootstyle="secondary")
        header.pack(fill=X, side=TOP)

        if os.path.exists(LOGO_PATH):
            try:
                from PIL import Image, ImageTk
                img = Image.open(LOGO_PATH).resize((44, 44))
                self._logo_img = ImageTk.PhotoImage(img)
                tb.Label(header, image=self._logo_img, bootstyle="inverse-secondary").pack(
                    side=LEFT, padx=(2, 10))
            except Exception:
                pass

        tb.Label(header, text="Mezclilla San Miguel C.A", font=("Segoe UI", 13, "bold"),
                  bootstyle="inverse-secondary").pack(side=LEFT, padx=(0, 20))

        self._build_barra_tasa(header)

    # ---------------------------------------------------------------- tasa
    def _build_barra_tasa(self, barra):
        tb.Label(barra, text="Tasa BCV:", font=("Segoe UI", 11, "bold"),
                  bootstyle="inverse-secondary").pack(side=LEFT, padx=(4, 6))

        self.lbl_tasa = tb.Label(barra, text="—", font=("Segoe UI", 13, "bold"),
                                  bootstyle="inverse-secondary")
        self.lbl_tasa.pack(side=LEFT)

        self.lbl_tasa_info = tb.Label(barra, text="", bootstyle="inverse-secondary")
        self.lbl_tasa_info.pack(side=LEFT, padx=12)

        self.pb_tasa = tb.Progressbar(barra, mode="indeterminate", bootstyle="light",
                                       length=90)
        # No se empaqueta todavía: solo se muestra mientras se consulta la tasa.

        self.btn_actualizar_tasa = tb.Button(
            barra, text="Actualizar tasa", command=self._refrescar_tasa,
            bootstyle="light-outline")
        self.btn_actualizar_tasa.pack(side=RIGHT, padx=4)

        tb.Label(barra, text="Corregir manualmente:",
                  bootstyle="inverse-secondary").pack(side=RIGHT, padx=(10, 4))
        self.var_tasa_manual = tk.StringVar()
        entry = tb.Entry(barra, textvariable=self.var_tasa_manual, width=10)
        entry.pack(side=RIGHT)
        entry.bind("<Return>", lambda e: self._usar_tasa_manual())
        tb.Button(barra, text="Usar", command=self._usar_tasa_manual,
                   bootstyle="warning").pack(side=RIGHT, padx=(4, 4))

    def _cargar_tasa_inicial(self):
        self.lbl_tasa.config(text="Consultando...")
        self.update_idletasks()
        info = bcv_rate.obtener_tasa_inicial()
        self._aplicar_tasa(info["tasa"], info["fuente"], automatica=info["automatica"],
                            actualizado=info["actualizado"])
        if info["tasa"] is None:
            messagebox.showwarning(
                "Sin tasa disponible",
                "No se pudo obtener la tasa BCV automáticamente (probé dolarapi.com, "
                "pydolarve.org y el sitio del BCV) y no hay una tasa guardada. "
                "Ingrésala manualmente arriba a la derecha antes de registrar una venta."
            )

    def _refrescar_tasa(self):
        """
        Consulta la tasa BCV en un hilo aparte (dolarapi.com/pydolarve.org/
        bcv.org.ve pueden tardar varios segundos, o agotar el timeout) para
        no congelar la ventana; mientras tanto se muestra un loader
        (botón deshabilitado + barra de progreso indeterminada) en el botón
        "Actualizar tasa".

        Importante: Tkinter no es thread-safe, así que el hilo NUNCA toca
        widgets ni llama a `self.after` directamente — solo deja el
        resultado en una `queue.Queue`, y el hilo principal la revisa
        periódicamente con `self.after` (patrón estándar de polling).
        """
        if getattr(self, "_actualizando_tasa", False):
            return  # ya hay una consulta en curso, evita doble clic
        self._actualizando_tasa = True

        self.btn_actualizar_tasa.config(state="disabled", text="Actualizando...")
        self.pb_tasa.pack(side=RIGHT, padx=(0, 8))
        self.pb_tasa.start(12)
        self.lbl_tasa.config(text="Consultando...")

        resultado_q = queue.Queue()

        def worker():
            resultado_q.put(bcv_rate.obtener_tasa_automatica())

        threading.Thread(target=worker, daemon=True).start()
        self._revisar_resultado_tasa(resultado_q)

    def _revisar_resultado_tasa(self, resultado_q):
        try:
            tasa, fuente = resultado_q.get_nowait()
        except queue.Empty:
            self.after(80, lambda: self._revisar_resultado_tasa(resultado_q))
            return
        self._on_tasa_refrescada(tasa, fuente)

    def _on_tasa_refrescada(self, tasa, fuente):
        self.pb_tasa.stop()
        self.pb_tasa.pack_forget()
        self.btn_actualizar_tasa.config(state="normal", text="Actualizar tasa")
        self._actualizando_tasa = False

        if tasa is None:
            messagebox.showerror(
                "Sin conexión",
                "No se pudo consultar la tasa BCV en línea (probé dolarapi.com, "
                "pydolarve.org y bcv.org.ve). Revisa tu conexión a internet; también "
                "puedes corregir la tasa manualmente."
            )
            self._aplicar_tasa(self.tasa_actual, self.tasa_fuente,
                                automatica=not self.tasa_es_manual,
                                actualizado=None)
            return
        bcv_rate.guardar_cache(tasa, fuente)
        self._aplicar_tasa(tasa, fuente, automatica=True,
                            actualizado=datetime.now().isoformat(timespec="seconds"))

    def _usar_tasa_manual(self):
        txt = self.var_tasa_manual.get().strip().replace(",", ".")
        if not txt:
            return
        try:
            tasa = round(float(txt), 2)
            if tasa <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Tasa inválida", "Ingresa un número válido, por ejemplo 190.50")
            return
        bcv_rate.guardar_cache(tasa, "Ingresada manualmente")
        self._aplicar_tasa(tasa, "Ingresada manualmente", automatica=False,
                            actualizado=datetime.now().isoformat(timespec="seconds"))
        self.var_tasa_manual.set("")

    def _aplicar_tasa(self, tasa, fuente, automatica, actualizado):
        # La tasa siempre se maneja con 2 decimales (como la publica el
        # BCV), sin importar de qué fuente venga (automática, cache o
        # manual) — así todos los cálculos de la venta usan ese mismo
        # valor redondeado, no solo lo que se muestra en pantalla.
        self.tasa_actual = round(tasa, 2) if tasa is not None else None
        self.tasa_fuente = fuente
        self.tasa_es_manual = not automatica
        if tasa is None:
            self.lbl_tasa.config(text="Sin tasa")
            self.lbl_tasa_info.config(text="Ingresa la tasa manualmente para poder cobrar →")
        else:
            self.lbl_tasa.config(text=f"{tasa:,.2f} Bs/US$")
            hora = ""
            if actualizado:
                try:
                    hora = datetime.fromisoformat(actualizado).strftime("%d/%m %H:%M")
                except ValueError:
                    hora = ""
            origen = "manual" if not automatica else "automática"
            self.lbl_tasa_info.config(text=f"Fuente: {fuente or '—'} · {origen}"
                                            + (f" · {hora}" if hora else ""))
        self._refrescar_tabla_carrito()
        self._actualizar_totales()
        if hasattr(self, "lbl_precio_producto"):
            self._actualizar_precio_label()
        if hasattr(self, "lbl_precio_producto_ppto"):
            self._actualizar_precio_label_ppto()
        if hasattr(self, "tree_carrito_ppto"):
            self._refrescar_tabla_carrito_ppto()

    # ---------------------------------------------------------------- tabs
    def _build_tabs(self):
        self.tabs = tb.Notebook(self)
        self.tabs.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.tab_venta = tb.Frame(self.tabs, padding=12)
        self.tab_presupuesto = tb.Frame(self.tabs, padding=12)
        self.tab_productos = tb.Frame(self.tabs, padding=12)
        self.tab_historial = tb.Frame(self.tabs, padding=12)
        self.tabs.add(self.tab_venta, text="  Nueva venta  ")
        self.tabs.add(self.tab_presupuesto, text="  Presupuesto  ")
        self.tabs.add(self.tab_productos, text="  Productos  ")
        self.tabs.add(self.tab_historial, text="  Historial  ")

        self._build_tab_venta()
        self._build_tab_presupuesto()
        self._build_tab_productos()
        self._build_tab_historial()
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())

    def _on_tab_changed(self):
        idx = self.tabs.index(self.tabs.select())
        if idx == 1:
            self._buscar_presupuestos()
        elif idx == 2:
            self._refrescar_tabla_productos()
        elif idx == 3:
            self._buscar_historial()

    # ----------------------------------------------------------- tab venta
    def _build_tab_venta(self):
        productos_frame = tb.Labelframe(self.tab_venta, text="Productos", padding=10)
        productos_frame.pack(fill=X, pady=(0, 10))

        tb.Label(productos_frame, text="Producto:").grid(row=0, column=0, padx=(0, 6), sticky=W)
        self.var_producto = tk.StringVar()
        self.combo_prod = tb.Combobox(productos_frame, textvariable=self.var_producto,
                                       values=[], state="readonly", width=30)
        self.combo_prod.grid(row=0, column=1, padx=(0, 16))
        self.combo_prod.bind("<<ComboboxSelected>>", lambda e: self._actualizar_precio_label())

        self.lbl_precio_producto = tb.Label(productos_frame, text="", bootstyle="secondary")
        self.lbl_precio_producto.grid(row=0, column=2, padx=(0, 16), sticky=W)

        tb.Label(productos_frame, text="Cantidad:").grid(row=0, column=3, padx=(0, 6))
        self.var_cantidad = tk.StringVar(value="1")
        entry_cant = tb.Entry(productos_frame, textvariable=self.var_cantidad, width=8)
        entry_cant.grid(row=0, column=4, padx=(0, 16))
        entry_cant.bind("<Return>", lambda e: self._agregar_producto())

        tb.Button(productos_frame, text="+ Agregar al carrito", command=self._agregar_producto,
                   bootstyle="success").grid(row=0, column=5)

        cols_carrito = ("producto", "cantidad", "precio_divisa", "precio_bs", "sub_divisa", "sub_bs")
        self.tree_carrito = tb.Treeview(self.tab_venta, columns=cols_carrito, show="headings",
                                         height=6, bootstyle="primary")
        titulos_c = {"producto": "Producto", "cantidad": "Cant.",
                     "precio_divisa": "Precio US$", "precio_bs": "Precio Bs",
                     "sub_divisa": "Subtotal US$", "sub_bs": "Subtotal Bs"}
        anchos_c = {"producto": 240, "cantidad": 60, "precio_divisa": 100,
                    "precio_bs": 100, "sub_divisa": 110, "sub_bs": 110}
        for c in cols_carrito:
            self.tree_carrito.heading(c, text=titulos_c[c])
            self.tree_carrito.column(c, width=anchos_c[c],
                                      anchor=E if c != "producto" else W)
        self.tree_carrito.pack(fill=X, pady=(8, 4))

        fila_carrito_btns = tb.Frame(self.tab_venta)
        fila_carrito_btns.pack(fill=X, pady=(0, 6))
        tb.Button(fila_carrito_btns, text="Quitar producto seleccionado",
                  command=self._quitar_producto, bootstyle="danger-outline").pack(side=LEFT)

        self.lbl_total_carrito = tb.Label(self.tab_venta, text="", font=("Segoe UI", 12, "bold"))
        self.lbl_total_carrito.pack(anchor=W)
        self.lbl_total_carrito_info = tb.Label(
            self.tab_venta,
            text="(cada pago cubre el % del total que le corresponde según su moneda; "
                 "el precio en bolívares de cada producto ya incluye su recargo)",
            bootstyle="secondary")
        self.lbl_total_carrito_info.pack(anchor=W, pady=(0, 10))

        # --- agregar pago
        agregar = tb.Labelframe(self.tab_venta, text="Agregar pago", padding=10)
        agregar.pack(fill=X, pady=(0, 10))

        tb.Label(agregar, text="Método:").grid(row=0, column=0, padx=(0, 6), sticky=W)
        self.var_metodo = tk.StringVar(value="Efectivo USD")
        combo = tb.Combobox(agregar, textvariable=self.var_metodo,
                             values=list(METODOS_PAGO.keys()), state="readonly", width=18)
        combo.grid(row=0, column=1, padx=(0, 16))
        combo.bind("<<ComboboxSelected>>", lambda e: self._actualizar_moneda_label())

        self.lbl_moneda = tb.Label(agregar, text="(USD)", bootstyle="secondary")
        self.lbl_moneda.grid(row=0, column=2, padx=(0, 16))

        tb.Label(agregar, text="Monto:").grid(row=0, column=3, padx=(0, 6))
        self.var_monto_pago = tk.StringVar()
        entry_monto = tb.Entry(agregar, textvariable=self.var_monto_pago, width=12)
        entry_monto.grid(row=0, column=4, padx=(0, 16))
        entry_monto.bind("<Return>", lambda e: self._agregar_pago())

        tb.Button(agregar, text="+ Agregar", command=self._agregar_pago,
                   bootstyle="success").grid(row=0, column=5)

        cols = ("metodo", "moneda", "monto", "equiv_usd", "fraccion")
        self.tree_pagos = tb.Treeview(self.tab_venta, columns=cols, show="headings", height=6,
                                       bootstyle="primary")
        self.tree_pagos.heading("metodo", text="Método")
        self.tree_pagos.heading("moneda", text="Moneda")
        self.tree_pagos.heading("monto", text="Monto ingresado")
        self.tree_pagos.heading("equiv_usd", text="Equivalente US$")
        self.tree_pagos.heading("fraccion", text="% del total cubierto")
        self.tree_pagos.column("metodo", width=160)
        self.tree_pagos.column("moneda", width=70, anchor=CENTER)
        self.tree_pagos.column("monto", width=140, anchor=E)
        self.tree_pagos.column("equiv_usd", width=140, anchor=E)
        self.tree_pagos.column("fraccion", width=140, anchor=E)
        self.tree_pagos.pack(fill=BOTH, expand=True, pady=(0, 6))

        tb.Button(self.tab_venta, text="Quitar pago seleccionado",
                  command=self._quitar_pago, bootstyle="danger-outline").pack(anchor=W)

        totales = tb.Frame(self.tab_venta, padding=(0, 12))
        totales.pack(fill=X)

        self.lbl_pagado = tb.Label(totales, text="Pagado: $ 0,00", font=("Segoe UI", 12))
        self.lbl_pagado.pack(anchor=W)

        self.lbl_diferencia = tb.Label(totales, text="Diferencia: $ 0,00  ·  Bs 0,00",
                                        font=("Segoe UI", 13, "bold"))
        self.lbl_diferencia.pack(anchor=W, pady=(4, 0))

        detalle_frame = tb.Labelframe(
            self.tab_venta, text="Detalle del cálculo (para verificar que todo esté bien)",
            padding=8)
        detalle_frame.pack(fill=X, pady=(10, 0))
        self.txt_detalle_calculo = tk.Text(
            detalle_frame, height=8, wrap="word", font=("Courier New", 9),
            relief="flat", background=self.style.colors.light)
        self.txt_detalle_calculo.pack(fill=X)
        self.txt_detalle_calculo.configure(state="disabled")

        acciones = tb.Frame(self.tab_venta)
        acciones.pack(fill=X, pady=(10, 0))

        tb.Label(acciones, text="Nota (opcional):").pack(side=LEFT, padx=(0, 6))
        self.var_nota = tk.StringVar()
        tb.Entry(acciones, textvariable=self.var_nota, width=40).pack(side=LEFT, padx=(0, 16))

        tb.Button(acciones, text="Cerrar venta y guardar", command=self._cerrar_venta,
                   bootstyle="success", width=22).pack(side=RIGHT)
        tb.Button(acciones, text="Limpiar", command=self._limpiar_venta,
                  bootstyle="secondary-outline").pack(side=RIGHT, padx=8)

    # ------------------------------------------------------------ productos (venta)
    def _cargar_productos(self):
        self.productos = database.listar_productos(solo_activos=True)
        nombres = [p["nombre"] for p in self.productos]
        self.combo_prod.config(values=nombres)
        if nombres and not self.var_producto.get():
            self.var_producto.set(nombres[0])
        self._actualizar_precio_label()

        if hasattr(self, "combo_prod_ppto"):
            self.combo_prod_ppto.config(values=nombres)
            if nombres and not self.var_producto_ppto.get():
                self.var_producto_ppto.set(nombres[0])
            self._actualizar_precio_label_ppto()

    def _buscar_producto(self, nombre):
        for p in self.productos:
            if p["nombre"] == nombre:
                return p
        return None

    def _actualizar_precio_label(self):
        prod = self._buscar_producto(self.var_producto.get())
        if not prod:
            self.lbl_precio_producto.config(text="")
            return
        texto = (f"{fmt_usd(prod['precio_divisa'])} en divisa  ·  "
                 f"equiv. {fmt_usd(prod['precio_bs_usd_equiv'])} si se paga en Bs "
                 f"(+{prod['recargo_pct']:g}%)")
        if self.tasa_actual:
            texto += (f"  ·  {fmt_bs(prod['precio_bs_usd_equiv'] * self.tasa_actual)} "
                      f"a la tasa actual")
        self.lbl_precio_producto.config(text=texto)

    def _agregar_producto(self):
        prod = self._buscar_producto(self.var_producto.get())
        if not prod:
            messagebox.showerror("Sin productos", "No hay productos cargados. Ve a la pestaña "
                                  "\"Productos\" para crear al menos uno.")
            return
        cantidad = self._parse_float(self.var_cantidad.get())
        if cantidad is None or cantidad <= 0:
            messagebox.showerror("Cantidad inválida", "Ingresa una cantidad válida mayor a 0.")
            return

        for item in self.carrito:
            if item["producto"] == prod["nombre"]:
                item["cantidad"] += cantidad
                self._refrescar_tabla_carrito()
                self.var_cantidad.set("1")
                return

        self.carrito.append({
            "producto": prod["nombre"],
            "cantidad": cantidad,
            "precio_unit_divisa": prod["precio_divisa"],
            "precio_unit_bs_usd_equiv": prod["precio_bs_usd_equiv"],
        })
        self._refrescar_tabla_carrito()
        self.var_cantidad.set("1")

    def _quitar_producto(self):
        sel = self.tree_carrito.selection()
        if not sel:
            return
        idx = self.tree_carrito.index(sel[0])
        del self.carrito[idx]
        self._refrescar_tabla_carrito()

    def _refrescar_tabla_carrito(self):
        self.tree_carrito.delete(*self.tree_carrito.get_children())
        for item in self.carrito:
            sub_divisa = item["cantidad"] * item["precio_unit_divisa"]
            sub_bs_usd = item["cantidad"] * item["precio_unit_bs_usd_equiv"]
            sub_bs = sub_bs_usd * self.tasa_actual if self.tasa_actual else 0
            precio_bs_real = item["precio_unit_bs_usd_equiv"] * self.tasa_actual if self.tasa_actual else None
            self.tree_carrito.insert("", END, values=(
                item["producto"],
                f"{item['cantidad']:g}",
                fmt_usd(item["precio_unit_divisa"]),
                fmt_bs(precio_bs_real) if precio_bs_real is not None else "—",
                fmt_usd(sub_divisa),
                fmt_bs(sub_bs) if self.tasa_actual else "—",
            ))
        self._actualizar_totales()

    def _totales_carrito(self):
        total_divisa = sum(i["cantidad"] * i["precio_unit_divisa"] for i in self.carrito)
        total_bs_usd_equiv = sum(i["cantidad"] * i["precio_unit_bs_usd_equiv"] for i in self.carrito)
        return round(total_divisa, 2), round(total_bs_usd_equiv, 2)

    # ------------------------------------------------------------- pagos
    def _actualizar_moneda_label(self):
        moneda = METODOS_PAGO.get(self.var_metodo.get(), "USD")
        self.lbl_moneda.config(text=f"({moneda})")

    def _parse_float(self, texto):
        try:
            return float(texto.strip().replace(",", "."))
        except (ValueError, AttributeError):
            return None

    def _agregar_pago(self):
        total_divisa, _ = self._totales_carrito()
        if total_divisa <= 0:
            messagebox.showerror("Carrito vacío", "Agrega al menos un producto antes de registrar pagos.")
            return

        metodo = self.var_metodo.get()
        moneda = METODOS_PAGO.get(metodo, "USD")
        monto = self._parse_float(self.var_monto_pago.get())
        if monto is None or monto <= 0:
            messagebox.showerror("Monto inválido", "Ingresa un monto válido mayor a 0.")
            return
        if moneda == "Bs" and not self.tasa_actual:
            messagebox.showerror("Falta la tasa BCV",
                                  "No hay una tasa BCV cargada; ingrésala arriba antes de "
                                  "registrar pagos en bolívares.")
            return

        total_divisa, total_bs_usd_equiv = self._totales_carrito()
        if moneda == "USD":
            equiv_usd = monto
            fraccion = monto / total_divisa if total_divisa > 0 else 0
        else:
            equiv_usd = monto / self.tasa_actual
            fraccion = equiv_usd / total_bs_usd_equiv if total_bs_usd_equiv > 0 else 0

        self.pagos_actuales.append({
            "metodo": metodo, "moneda": moneda,
            "monto_ingresado": round(monto, 2),
            "monto_usd_equiv": round(equiv_usd, 2),
            "fraccion_cubierta": fraccion,
        })
        self._refrescar_tabla_pagos()
        self.var_monto_pago.set("")

    def _quitar_pago(self):
        sel = self.tree_pagos.selection()
        if not sel:
            return
        idx = self.tree_pagos.index(sel[0])
        del self.pagos_actuales[idx]
        self._refrescar_tabla_pagos()

    def _refrescar_tabla_pagos(self):
        self.tree_pagos.delete(*self.tree_pagos.get_children())
        for p in self.pagos_actuales:
            monto_txt = fmt_usd(p["monto_ingresado"]) if p["moneda"] == "USD" else fmt_bs(p["monto_ingresado"])
            self.tree_pagos.insert("", END, values=(
                p["metodo"], p["moneda"], monto_txt, fmt_usd(p["monto_usd_equiv"]),
                f"{p['fraccion_cubierta'] * 100:,.1f}%",
            ))
        self._actualizar_totales()

    # ------------------------------------------------------------ totales
    def _actualizar_totales(self):
        total_divisa, total_bs_usd_equiv = self._totales_carrito()
        total_bs = total_bs_usd_equiv * self.tasa_actual if self.tasa_actual else None

        if self.carrito:
            texto_total = f"Total del carrito: {fmt_usd(total_divisa)} en divisa"
            texto_total += f"  ·  {fmt_bs(total_bs)} si se paga todo en bolívares" if total_bs is not None else "  ·  (sin tasa)"
        else:
            texto_total = "Agrega productos al carrito para calcular el total."
        self.lbl_total_carrito.config(text=texto_total)

        fraccion_pagada = sum(p["fraccion_cubierta"] for p in self.pagos_actuales)
        pagado_usd = sum(p["monto_usd_equiv"] for p in self.pagos_actuales)
        pagado_bs = sum(p["monto_ingresado"] for p in self.pagos_actuales if p["moneda"] == "Bs")
        self.lbl_pagado.config(
            text=f"Pagado: {fmt_usd(pagado_usd)} equiv.  ·  {fmt_bs(pagado_bs)} recibidos en Bs"
                 f"  ({fraccion_pagada * 100:,.1f}% del total)"
        )

        fraccion_restante = 1 - fraccion_pagada
        diff_divisa = fraccion_restante * total_divisa
        diff_bs = fraccion_restante * total_bs_usd_equiv * self.tasa_actual if self.tasa_actual else 0

        if not self.carrito:
            self.lbl_diferencia.config(text="—", bootstyle="secondary")
        elif abs(fraccion_restante) <= 0.001:
            self.lbl_diferencia.config(text="Cobro exacto ✓", bootstyle="success")
        elif fraccion_restante > 0:
            self.lbl_diferencia.config(
                text=f"Falta por cobrar: {fmt_usd(diff_divisa)} en divisa  ó  {fmt_bs(diff_bs)} en bolívares",
                bootstyle="danger")
        else:
            self.lbl_diferencia.config(
                text=f"Vuelto a favor del cliente: {fmt_usd(-diff_divisa)} en divisa  ó  {fmt_bs(-diff_bs)} en bolívares",
                bootstyle="success")

        self._actualizar_detalle_calculo(total_divisa, total_bs_usd_equiv, fraccion_pagada,
                                          fraccion_restante, diff_divisa, diff_bs)

    def _actualizar_detalle_calculo(self, total_divisa, total_bs_usd_equiv, fraccion_pagada,
                                     fraccion_restante, diff_divisa, diff_bs):
        """
        Texto explicando paso a paso cómo se llegó al 'falta/vuelto', para que
        se pueda verificar a mano que el cálculo está bien (modelo
        proporcional: cada pago cubre una fracción del total según su moneda).
        """
        if not hasattr(self, "txt_detalle_calculo"):
            return

        lineas = []
        if not self.carrito:
            lineas.append("Agrega productos al carrito para ver el detalle del cálculo.")
        else:
            total_bs = total_bs_usd_equiv * self.tasa_actual if self.tasa_actual else None
            lineas.append(f"Total en divisa (100% pagado en USD/Zelle): {fmt_usd(total_divisa)}")
            if total_bs is not None:
                lineas.append(
                    f"Total en bolívares (100% pagado en Bs, a tasa {self.tasa_actual:,.2f}): "
                    f"{fmt_bs(total_bs)}"
                )
            lineas.append("")
            if not self.pagos_actuales:
                lineas.append("Sin pagos registrados todavía → falta el 100% del total.")
            else:
                lineas.append("Pagos registrados (cada uno cubre una fracción del total, "
                               "según su propia moneda):")
                for p in self.pagos_actuales:
                    if p["moneda"] == "USD":
                        lineas.append(
                            f"  • {p['metodo']}: {fmt_usd(p['monto_ingresado'])} ÷ "
                            f"{fmt_usd(total_divisa)} (total divisa) = "
                            f"{p['fraccion_cubierta'] * 100:,.2f}%"
                        )
                    else:
                        lineas.append(
                            f"  • {p['metodo']}: {fmt_bs(p['monto_ingresado'])} ÷ "
                            f"{self.tasa_actual:,.2f} (tasa) = "
                            f"{fmt_usd(p['monto_usd_equiv'])} equiv.  ÷  "
                            f"{fmt_usd(total_bs_usd_equiv)} (total Bs en equiv. US$) = "
                            f"{p['fraccion_cubierta'] * 100:,.2f}%"
                        )
                lineas.append(f"  Suma de fracciones pagadas: {fraccion_pagada * 100:,.2f}%")

            lineas.append("")
            lineas.append(f"Fracción restante = 100% − {fraccion_pagada * 100:,.2f}% = "
                           f"{fraccion_restante * 100:,.2f}%")
            if abs(fraccion_restante) <= 0.001:
                lineas.append("→ Cobro exacto, no falta ni sobra nada.")
            else:
                verbo = "Falta por cobrar" if fraccion_restante > 0 else "Vuelto a favor del cliente"
                lineas.append(
                    f"→ {verbo}: {fraccion_restante * 100:,.2f}% × {fmt_usd(total_divisa)} "
                    f"(total divisa) = {fmt_usd(abs(diff_divisa))}"
                )
                if self.tasa_actual:
                    lineas.append(
                        f"→ {verbo} en Bs: {fraccion_restante * 100:,.2f}% × "
                        f"{fmt_usd(total_bs_usd_equiv)} (total Bs en equiv. US$) × "
                        f"{self.tasa_actual:,.2f} (tasa) = {fmt_bs(abs(diff_bs))}"
                    )

        texto = "\n".join(lineas)
        self.txt_detalle_calculo.configure(state="normal")
        self.txt_detalle_calculo.delete("1.0", "end")
        self.txt_detalle_calculo.insert("1.0", texto)
        self.txt_detalle_calculo.configure(state="disabled")

    def _cerrar_venta(self):
        if not self.carrito:
            messagebox.showerror("Carrito vacío", "Agrega al menos un producto antes de cerrar la venta.")
            return
        if not self.tasa_actual:
            messagebox.showerror("Falta la tasa BCV", "No hay tasa BCV cargada.")
            return
        if not self.pagos_actuales:
            messagebox.showerror("Sin pagos", "Agrega al menos un pago antes de cerrar la venta.")
            return

        fraccion_pagada = sum(p["fraccion_cubierta"] for p in self.pagos_actuales)
        fraccion_restante = 1 - fraccion_pagada
        if fraccion_restante > 0.001:
            total_divisa, total_bs_usd_equiv = self._totales_carrito()
            diff_divisa = fraccion_restante * total_divisa
            diff_bs = fraccion_restante * total_bs_usd_equiv * self.tasa_actual
            if not messagebox.askyesno(
                "Falta dinero por cobrar",
                f"Aún falta {fmt_usd(diff_divisa)} en divisa (o {fmt_bs(diff_bs)} en "
                "bolívares) por cobrar. ¿Deseas guardar la venta de todas formas (por "
                "ejemplo si el cliente quedó debiendo)?"
            ):
                return

        database.guardar_venta(
            carrito=self.carrito,
            tasa_bcv=self.tasa_actual,
            tasa_fuente=self.tasa_fuente,
            pagos=self.pagos_actuales,
            nota=self.var_nota.get().strip(),
        )
        messagebox.showinfo("Venta guardada", "La venta se guardó correctamente en el historial.")
        self._limpiar_venta()

    def _limpiar_venta(self):
        self.var_monto_pago.set("")
        self.var_nota.set("")
        self.var_cantidad.set("1")
        self.carrito = []
        self.pagos_actuales = []
        self._refrescar_tabla_carrito()
        self._refrescar_tabla_pagos()

    # -------------------------------------------------------- tab presupuesto
    def _build_tab_presupuesto(self):
        cliente_frame = tb.Labelframe(self.tab_presupuesto, text="Datos del cliente / presupuesto",
                                       padding=10)
        cliente_frame.pack(fill=X, pady=(0, 10))

        tb.Label(cliente_frame, text="Cliente (opcional):").grid(row=0, column=0, sticky=W, padx=(0, 6))
        self.var_cliente_nombre = tk.StringVar()
        tb.Entry(cliente_frame, textvariable=self.var_cliente_nombre, width=28).grid(
            row=0, column=1, padx=(0, 16))

        tb.Label(cliente_frame, text="Teléfono (opcional):").grid(row=0, column=2, sticky=W, padx=(0, 6))
        self.var_cliente_telefono = tk.StringVar()
        tb.Entry(cliente_frame, textvariable=self.var_cliente_telefono, width=18).grid(
            row=0, column=3, padx=(0, 16))

        tb.Label(cliente_frame, text="Válido por (días):").grid(row=0, column=4, sticky=W, padx=(0, 6))
        self.var_validez_dias = tk.StringVar(value="3")
        tb.Entry(cliente_frame, textvariable=self.var_validez_dias, width=6).grid(row=0, column=5)

        productos_frame = tb.Labelframe(self.tab_presupuesto, text="Productos", padding=10)
        productos_frame.pack(fill=X, pady=(0, 10))

        tb.Label(productos_frame, text="Producto:").grid(row=0, column=0, padx=(0, 6), sticky=W)
        self.var_producto_ppto = tk.StringVar()
        self.combo_prod_ppto = tb.Combobox(productos_frame, textvariable=self.var_producto_ppto,
                                            values=[], state="readonly", width=30)
        self.combo_prod_ppto.grid(row=0, column=1, padx=(0, 16))
        self.combo_prod_ppto.bind("<<ComboboxSelected>>",
                                   lambda e: self._actualizar_precio_label_ppto())

        self.lbl_precio_producto_ppto = tb.Label(productos_frame, text="", bootstyle="secondary")
        self.lbl_precio_producto_ppto.grid(row=0, column=2, padx=(0, 16), sticky=W)

        tb.Label(productos_frame, text="Cantidad:").grid(row=0, column=3, padx=(0, 6))
        self.var_cantidad_ppto = tk.StringVar(value="1")
        entry_cant = tb.Entry(productos_frame, textvariable=self.var_cantidad_ppto, width=8)
        entry_cant.grid(row=0, column=4, padx=(0, 16))
        entry_cant.bind("<Return>", lambda e: self._agregar_producto_ppto())

        tb.Button(productos_frame, text="+ Agregar", command=self._agregar_producto_ppto,
                   bootstyle="success").grid(row=0, column=5)

        cols_carrito = ("producto", "cantidad", "precio_divisa", "precio_bs", "sub_divisa", "sub_bs")
        self.tree_carrito_ppto = tb.Treeview(self.tab_presupuesto, columns=cols_carrito,
                                             show="headings", height=6, bootstyle="primary")
        titulos_c = {"producto": "Producto", "cantidad": "Cant.",
                     "precio_divisa": "Precio US$", "precio_bs": "Precio Bs",
                     "sub_divisa": "Subtotal US$", "sub_bs": "Subtotal Bs"}
        anchos_c = {"producto": 240, "cantidad": 60, "precio_divisa": 100,
                    "precio_bs": 100, "sub_divisa": 110, "sub_bs": 110}
        for c in cols_carrito:
            self.tree_carrito_ppto.heading(c, text=titulos_c[c])
            self.tree_carrito_ppto.column(c, width=anchos_c[c],
                                           anchor=E if c != "producto" else W)
        self.tree_carrito_ppto.pack(fill=X, pady=(8, 4))

        tb.Button(self.tab_presupuesto, text="Quitar producto seleccionado",
                  command=self._quitar_producto_ppto, bootstyle="danger-outline").pack(anchor=W)

        self.lbl_total_ppto = tb.Label(self.tab_presupuesto, text="", font=("Segoe UI", 12, "bold"))
        self.lbl_total_ppto.pack(anchor=W, pady=(10, 10))

        tb.Label(self.tab_presupuesto, text="Nota adicional (opcional, aparece en el PDF):"
                  ).pack(anchor=W)
        self.var_nota_ppto = tk.StringVar()
        tb.Entry(self.tab_presupuesto, textvariable=self.var_nota_ppto, width=80).pack(
            anchor=W, pady=(2, 10))

        acciones = tb.Frame(self.tab_presupuesto)
        acciones.pack(fill=X, pady=(0, 14))
        tb.Button(acciones, text="Generar presupuesto (PDF)", command=self._generar_presupuesto,
                   bootstyle="success", width=26).pack(side=LEFT)
        tb.Button(acciones, text="Limpiar", command=self._limpiar_presupuesto,
                  bootstyle="secondary-outline").pack(side=LEFT, padx=8)

        tb.Label(self.tab_presupuesto, text="Presupuestos generados:",
                  font=("Segoe UI", 11, "bold")).pack(anchor=W, pady=(4, 4))

        filtros = tb.Frame(self.tab_presupuesto)
        filtros.pack(fill=X, pady=(0, 6))
        tb.Label(filtros, text="Buscar cliente/nota:").pack(side=LEFT, padx=(0, 4))
        self.var_buscar_ppto = tk.StringVar()
        tb.Entry(filtros, textvariable=self.var_buscar_ppto, width=24).pack(side=LEFT, padx=(0, 8))
        tb.Button(filtros, text="Buscar", command=self._buscar_presupuestos,
                   bootstyle="primary").pack(side=LEFT)

        cols_h = ("numero", "fecha", "cliente", "total_divisa", "total_bs")
        self.tree_presupuestos = tb.Treeview(self.tab_presupuesto, columns=cols_h,
                                              show="headings", height=6, bootstyle="primary")
        titulos_h = {"numero": "N°", "fecha": "Fecha", "cliente": "Cliente",
                     "total_divisa": "Total US$", "total_bs": "Total Bs"}
        anchos_h = {"numero": 70, "fecha": 130, "cliente": 220, "total_divisa": 110, "total_bs": 120}
        for c in cols_h:
            self.tree_presupuestos.heading(c, text=titulos_h[c])
            self.tree_presupuestos.column(c, width=anchos_h[c],
                                           anchor=E if c in ("total_divisa", "total_bs") else W)
        self.tree_presupuestos.pack(fill=BOTH, expand=True)
        self.tree_presupuestos.bind("<Double-1>", lambda e: self._reabrir_presupuesto())

        botones_h = tb.Frame(self.tab_presupuesto)
        botones_h.pack(fill=X, pady=(6, 0))
        tb.Button(botones_h, text="Abrir / Ver PDF", command=self._reabrir_presupuesto,
                  bootstyle="primary-outline").pack(side=LEFT)
        tb.Button(botones_h, text="Imprimir", command=self._imprimir_presupuesto_guardado,
                  bootstyle="secondary-outline").pack(side=LEFT, padx=8)

        self.carrito_ppto = []
        self._actualizar_precio_label_ppto()
        self._actualizar_total_ppto()

    def _actualizar_precio_label_ppto(self):
        prod = self._buscar_producto(self.var_producto_ppto.get())
        if not prod:
            self.lbl_precio_producto_ppto.config(text="")
            return
        texto = (f"{fmt_usd(prod['precio_divisa'])} en divisa  ·  "
                 f"equiv. {fmt_usd(prod['precio_bs_usd_equiv'])} en Bs "
                 f"(+{prod['recargo_pct']:g}%)")
        if self.tasa_actual:
            texto += (f"  ·  {fmt_bs(prod['precio_bs_usd_equiv'] * self.tasa_actual)} "
                      f"a la tasa actual")
        self.lbl_precio_producto_ppto.config(text=texto)

    def _agregar_producto_ppto(self):
        prod = self._buscar_producto(self.var_producto_ppto.get())
        if not prod:
            messagebox.showerror("Sin productos", "No hay productos cargados. Ve a la pestaña "
                                  "\"Productos\" para crear al menos uno.")
            return
        cantidad = self._parse_float(self.var_cantidad_ppto.get())
        if cantidad is None or cantidad <= 0:
            messagebox.showerror("Cantidad inválida", "Ingresa una cantidad válida mayor a 0.")
            return

        for item in self.carrito_ppto:
            if item["producto"] == prod["nombre"]:
                item["cantidad"] += cantidad
                self._refrescar_tabla_carrito_ppto()
                self.var_cantidad_ppto.set("1")
                return

        self.carrito_ppto.append({
            "producto": prod["nombre"],
            "cantidad": cantidad,
            "precio_unit_divisa": prod["precio_divisa"],
            "precio_unit_bs": prod["precio_bs_usd_equiv"],
        })
        self._refrescar_tabla_carrito_ppto()
        self.var_cantidad_ppto.set("1")

    def _quitar_producto_ppto(self):
        sel = self.tree_carrito_ppto.selection()
        if not sel:
            return
        idx = self.tree_carrito_ppto.index(sel[0])
        del self.carrito_ppto[idx]
        self._refrescar_tabla_carrito_ppto()

    def _refrescar_tabla_carrito_ppto(self):
        self.tree_carrito_ppto.delete(*self.tree_carrito_ppto.get_children())
        for item in self.carrito_ppto:
            sub_divisa = item["cantidad"] * item["precio_unit_divisa"]
            sub_bs_usd = item["cantidad"] * item["precio_unit_bs"]
            sub_bs = sub_bs_usd * self.tasa_actual if self.tasa_actual else 0
            precio_bs_real = item["precio_unit_bs"] * self.tasa_actual if self.tasa_actual else None
            self.tree_carrito_ppto.insert("", END, values=(
                item["producto"],
                f"{item['cantidad']:g}",
                fmt_usd(item["precio_unit_divisa"]),
                fmt_bs(precio_bs_real) if precio_bs_real is not None else "—",
                fmt_usd(sub_divisa),
                fmt_bs(sub_bs) if self.tasa_actual else "—",
            ))
        self._actualizar_total_ppto()

    def _totales_carrito_ppto(self):
        total_divisa = sum(i["cantidad"] * i["precio_unit_divisa"] for i in self.carrito_ppto)
        total_bs_usd = sum(i["cantidad"] * i["precio_unit_bs"] for i in self.carrito_ppto)
        return round(total_divisa, 2), round(total_bs_usd, 2)

    def _actualizar_total_ppto(self):
        total_divisa, total_bs_usd = self._totales_carrito_ppto()
        total_bs = total_bs_usd * self.tasa_actual if self.tasa_actual else None
        if self.carrito_ppto:
            texto = f"Total del presupuesto: {fmt_usd(total_divisa)} en divisa"
            texto += f"  ·  {fmt_bs(total_bs)} en bolívares (a la tasa BCV actual)" if total_bs is not None else ""
        else:
            texto = "Agrega productos para armar el presupuesto."
        self.lbl_total_ppto.config(text=texto)

    def _generar_presupuesto(self):
        if not self.carrito_ppto:
            messagebox.showerror("Sin productos", "Agrega al menos un producto al presupuesto.")
            return
        if not self.tasa_actual:
            messagebox.showerror("Falta la tasa BCV", "No hay tasa BCV cargada.")
            return
        validez = self._parse_float(self.var_validez_dias.get())
        if validez is None or validez <= 0:
            messagebox.showerror("Validez inválida", "Ingresa un número de días válido (mayor a 0).")
            return

        os.makedirs(PRESUPUESTOS_DIR, exist_ok=True)
        numero = database.siguiente_numero_presupuesto()
        fecha = datetime.now()
        cliente_nombre = self.var_cliente_nombre.get().strip()
        nombre_archivo_sugerido = f"Presupuesto_{numero:04d}"
        if cliente_nombre:
            limpio = "".join(c if c.isalnum() else "_" for c in cliente_nombre)
            nombre_archivo_sugerido += f"_{limpio}"
        nombre_archivo_sugerido += ".pdf"

        path = filedialog.asksaveasfilename(
            title="Guardar presupuesto como",
            initialdir=PRESUPUESTOS_DIR,
            initialfile=nombre_archivo_sugerido,
            defaultextension=".pdf",
            filetypes=[("Archivo PDF", "*.pdf")],
        )
        if not path:
            return

        # precio_unit_bs en self.carrito_ppto está en equivalente-US$ (igual
        # que en el catálogo de productos); para mostrar y guardar el
        # presupuesto lo convertimos a bolívares reales multiplicando por la
        # tasa BCV actual, así el precio unitario y el subtotal en Bs son
        # consistentes entre sí y con el total en Bs.
        items_pdf = []
        for it in self.carrito_ppto:
            precio_unit_bs_real = it["precio_unit_bs"] * self.tasa_actual
            items_pdf.append({
                "producto": it["producto"],
                "cantidad": it["cantidad"],
                "precio_unit_divisa": it["precio_unit_divisa"],
                "precio_unit_bs": precio_unit_bs_real,
                "subtotal_divisa": it["cantidad"] * it["precio_unit_divisa"],
                "subtotal_bs": it["cantidad"] * precio_unit_bs_real,
            })
        total_divisa, total_bs_usd = self._totales_carrito_ppto()

        datos_pdf = {
            "numero": numero,
            "fecha": fecha,
            "validez_dias": int(validez),
            "cliente_nombre": cliente_nombre,
            "cliente_telefono": self.var_cliente_telefono.get().strip(),
            "items": items_pdf,
            "total_divisa": total_divisa,
            "total_bs": total_bs_usd * self.tasa_actual,
            "tasa_bcv": self.tasa_actual,
            "tasa_fuente": self.tasa_fuente,
            "nota": self.var_nota_ppto.get().strip(),
        }

        try:
            presupuesto_pdf.generar_pdf(path, datos_pdf)
        except Exception as exc:
            messagebox.showerror("Error al generar el PDF", f"No se pudo generar el PDF:\n{exc}")
            return

        database.guardar_presupuesto(
            numero=numero,
            fecha_iso=fecha.isoformat(timespec="seconds"),
            validez_dias=int(validez),
            cliente_nombre=cliente_nombre,
            cliente_telefono=self.var_cliente_telefono.get().strip(),
            items=[{
                "producto": it["producto"], "cantidad": it["cantidad"],
                "precio_unit_divisa": it["precio_unit_divisa"],
                "precio_unit_bs": it["precio_unit_bs"] * self.tasa_actual,
            } for it in self.carrito_ppto],
            tasa_bcv=self.tasa_actual,
            tasa_fuente=self.tasa_fuente,
            nota=self.var_nota_ppto.get().strip(),
            archivo=path,
        )

        self._buscar_presupuestos()
        abrio = abrir_archivo(path)
        mensaje = f"Presupuesto N° {numero:04d} generado y guardado en:\n{path}"
        if not abrio:
            mensaje += "\n\n(No se pudo abrir automáticamente; ábrelo desde esa carpeta.)"
        messagebox.showinfo("Presupuesto generado", mensaje)
        self._limpiar_presupuesto()

    def _limpiar_presupuesto(self):
        self.carrito_ppto = []
        self.var_cliente_nombre.set("")
        self.var_cliente_telefono.set("")
        self.var_validez_dias.set("3")
        self.var_nota_ppto.set("")
        self.var_cantidad_ppto.set("1")
        self._refrescar_tabla_carrito_ppto()

    def _buscar_presupuestos(self):
        texto = self.var_buscar_ppto.get().strip() or None if hasattr(self, "var_buscar_ppto") else None
        presupuestos = database.listar_presupuestos(texto=texto)
        self.tree_presupuestos.delete(*self.tree_presupuestos.get_children())
        for p in presupuestos:
            fecha = p["fecha"].replace("T", " ")
            self.tree_presupuestos.insert("", END, iid=str(p["id"]), values=(
                f"{p['numero']:04d}", fecha, p["cliente_nombre"] or "—",
                fmt_usd(p["total_divisa"]), fmt_bs(p["total_bs"]),
            ))

    def _presupuesto_seleccionado(self):
        sel = self.tree_presupuestos.selection()
        if not sel:
            messagebox.showinfo("Selecciona un presupuesto", "Primero selecciona uno de la lista.")
            return None
        return database.obtener_presupuesto(int(sel[0]))

    def _reabrir_presupuesto(self):
        detalle = self._presupuesto_seleccionado()
        if not detalle:
            return
        path = self._asegurar_pdf_presupuesto(detalle)
        if path:
            abrir_archivo(path)

    def _imprimir_presupuesto_guardado(self):
        detalle = self._presupuesto_seleccionado()
        if not detalle:
            return
        path = self._asegurar_pdf_presupuesto(detalle)
        if not path:
            return
        if not imprimir_archivo(path):
            abrir_archivo(path)
            messagebox.showinfo(
                "Imprimir manualmente",
                "No se pudo enviar directo a la impresora desde aquí. Se abrió el PDF: "
                "imprímelo con Cmd+P (Mac) o Ctrl+P (Windows) desde el visor."
            )

    def _asegurar_pdf_presupuesto(self, detalle):
        """Si el archivo guardado ya no existe, lo regenera a partir de los datos guardados."""
        p, items = detalle["presupuesto"], detalle["items"]
        path = p.get("archivo") or ""
        if path and os.path.exists(path):
            return path

        os.makedirs(PRESUPUESTOS_DIR, exist_ok=True)
        nuevo_path = os.path.join(PRESUPUESTOS_DIR, f"Presupuesto_{p['numero']:04d}.pdf")
        items_pdf = [{
            "producto": it["producto"], "cantidad": it["cantidad"],
            "precio_unit_divisa": it["precio_unit_divisa"],
            "precio_unit_bs": it["precio_unit_bs"],
            "subtotal_divisa": it["subtotal_divisa"], "subtotal_bs": it["subtotal_bs"],
        } for it in items]
        datos_pdf = {
            "numero": p["numero"],
            "fecha": datetime.fromisoformat(p["fecha"]),
            "validez_dias": p["validez_dias"],
            "cliente_nombre": p["cliente_nombre"],
            "cliente_telefono": p["cliente_telefono"],
            "items": items_pdf,
            "total_divisa": p["total_divisa"],
            "total_bs": p["total_bs"],
            "tasa_bcv": p["tasa_bcv"],
            "tasa_fuente": p["tasa_fuente"],
            "nota": p["nota"],
        }
        try:
            presupuesto_pdf.generar_pdf(nuevo_path, datos_pdf)
        except Exception as exc:
            messagebox.showerror("Error al generar el PDF", f"No se pudo regenerar el PDF:\n{exc}")
            return None
        database.actualizar_archivo_presupuesto(p["id"], nuevo_path)
        return nuevo_path

    # ------------------------------------------------------------ tab productos
    def _build_tab_productos(self):
        info = tb.Label(
            self.tab_productos,
            text="Cada producto tiene su precio en divisa y su propio % de recargo para "
                 "cuando se paga en bolívares (precio en Bs = precio en divisa × (1 + recargo%)).",
            bootstyle="secondary", wraplength=900, justify=LEFT)
        info.pack(anchor=W, pady=(0, 10))

        botones = tb.Frame(self.tab_productos)
        botones.pack(fill=X, pady=(0, 8))
        tb.Button(botones, text="+ Nuevo producto", command=lambda: self._abrir_form_producto(None),
                   bootstyle="success").pack(side=LEFT)
        tb.Button(botones, text="Editar seleccionado",
                  command=self._editar_producto_seleccionado, bootstyle="primary-outline"
                  ).pack(side=LEFT, padx=8)
        tb.Button(botones, text="Eliminar seleccionado",
                  command=self._eliminar_producto_seleccionado, bootstyle="danger-outline"
                  ).pack(side=LEFT)

        cols = ("nombre", "precio_divisa", "recargo", "precio_bs")
        self.tree_productos = tb.Treeview(self.tab_productos, columns=cols, show="headings",
                                           bootstyle="primary")
        titulos = {"nombre": "Producto", "precio_divisa": "Precio divisa (US$)",
                   "recargo": "Recargo en Bs (%)", "precio_bs": "Precio en Bs (equiv. US$)"}
        anchos = {"nombre": 300, "precio_divisa": 170, "recargo": 160, "precio_bs": 220}
        for c in cols:
            self.tree_productos.heading(c, text=titulos[c])
            self.tree_productos.column(c, width=anchos[c], anchor=E if c != "nombre" else W)
        self.tree_productos.pack(fill=BOTH, expand=True)
        self.tree_productos.bind("<Double-1>", lambda e: self._editar_producto_seleccionado())

    def _refrescar_tabla_productos(self):
        productos = database.listar_productos(solo_activos=True)
        self.tree_productos.delete(*self.tree_productos.get_children())
        for p in productos:
            self.tree_productos.insert("", END, iid=str(p["id"]), values=(
                p["nombre"], fmt_usd(p["precio_divisa"]), f"{p['recargo_pct']:g}%",
                fmt_usd(p["precio_bs_usd_equiv"]),
            ))

    def _producto_seleccionado_id(self):
        sel = self.tree_productos.selection()
        if not sel:
            messagebox.showinfo("Selecciona un producto", "Primero selecciona un producto de la lista.")
            return None
        return int(sel[0])

    def _editar_producto_seleccionado(self):
        pid = self._producto_seleccionado_id()
        if pid is None:
            return
        self._abrir_form_producto(pid)

    def _eliminar_producto_seleccionado(self):
        pid = self._producto_seleccionado_id()
        if pid is None:
            return
        prod = database.obtener_producto(pid)
        if not prod:
            return
        if messagebox.askyesno("Eliminar producto",
                                f"¿Eliminar \"{prod['nombre']}\" del catálogo? Las ventas ya "
                                "guardadas que lo usaron no se ven afectadas."):
            database.eliminar_producto(pid)
            self._refrescar_tabla_productos()
            self._cargar_productos()

    def _abrir_form_producto(self, producto_id):
        editar = producto_id is not None
        prod = database.obtener_producto(producto_id) if editar else None

        win = tb.Toplevel(self)
        win.title("Editar producto" if editar else "Nuevo producto")
        win.geometry("460x300")
        win.resizable(False, False)

        frame = tb.Frame(win, padding=16)
        frame.pack(fill=BOTH, expand=True)

        tb.Label(frame, text="Nombre del producto:").grid(row=0, column=0, columnspan=2,
                                                            sticky=W, pady=(0, 4))
        var_nombre = tk.StringVar(value=prod["nombre"] if prod else "")
        tb.Entry(frame, textvariable=var_nombre, width=40).grid(row=1, column=0, columnspan=2,
                                                                  sticky=W, pady=(0, 12))

        tb.Label(frame, text="Precio en divisa (US$):").grid(row=2, column=0, sticky=W, pady=(0, 4))
        var_precio = tk.StringVar(value=f"{prod['precio_divisa']:g}" if prod else "")
        entry_precio = tb.Entry(frame, textvariable=var_precio, width=15)
        entry_precio.grid(row=3, column=0, sticky=W, pady=(0, 12))

        tb.Label(frame, text="Precio en Bs (equiv. US$):").grid(row=2, column=1, sticky=W, pady=(0, 4))
        var_bs = tk.StringVar(value=f"{prod['precio_bs_usd_equiv']:g}" if prod else "")
        entry_bs = tb.Entry(frame, textvariable=var_bs, width=15)
        entry_bs.grid(row=3, column=1, sticky=W, pady=(0, 12))

        tb.Label(frame, text="Recargo en Bs (%):").grid(row=4, column=0, sticky=W, pady=(0, 4))
        var_recargo = tk.StringVar(value=f"{prod['recargo_pct']:g}" if prod else "30")
        entry_recargo = tb.Entry(frame, textvariable=var_recargo, width=15)
        entry_recargo.grid(row=5, column=0, sticky=W, pady=(0, 12))

        lbl_ayuda = tb.Label(
            frame,
            text="Puedes escribir el precio en Bs (y se calcula el % solo) o el %\n"
                 "(y se calcula el precio en Bs) — lo último que edites manda.",
            bootstyle="secondary", justify=LEFT)
        lbl_ayuda.grid(row=4, column=1, rowspan=2, sticky=W, pady=(0, 12))

        # Evita bucles infinitos entre los traces cuando uno actualiza al otro.
        estado = {"actualizando": False}

        def desde_recargo(*_):
            if estado["actualizando"]:
                return
            p = self._parse_float(var_precio.get())
            r = self._parse_float(var_recargo.get())
            if p is not None and p > 0 and r is not None:
                estado["actualizando"] = True
                var_bs.set(f"{round(p * (1 + r / 100.0), 4):g}")
                estado["actualizando"] = False

        def desde_precio_bs(*_):
            if estado["actualizando"]:
                return
            p = self._parse_float(var_precio.get())
            b = self._parse_float(var_bs.get())
            if p is not None and p > 0 and b is not None:
                estado["actualizando"] = True
                var_recargo.set(f"{round((b / p - 1) * 100.0, 4):g}")
                estado["actualizando"] = False

        def cambio_precio_base(*_):
            # Si cambia el precio en divisa, se mantiene el % de recargo y
            # se recalcula el precio en Bs (no al revés), para no pisar el
            # % que el usuario ya haya fijado.
            desde_recargo()

        var_recargo.trace_add("write", desde_recargo)
        var_bs.trace_add("write", desde_precio_bs)
        var_precio.trace_add("write", cambio_precio_base)

        def guardar():
            nombre = var_nombre.get().strip()
            precio = self._parse_float(var_precio.get())
            recargo = self._parse_float(var_recargo.get())
            if not nombre:
                messagebox.showerror("Falta el nombre", "Ingresa el nombre del producto.")
                return
            if precio is None or precio <= 0:
                messagebox.showerror("Precio inválido", "Ingresa un precio en divisa válido, mayor a 0.")
                return
            if recargo is None or recargo < 0:
                messagebox.showerror(
                    "Recargo inválido",
                    "El % de recargo calculado no es válido. Revisa el precio en divisa y "
                    "el precio en Bs (el precio en Bs debe ser mayor o igual al de divisa)."
                )
                return
            excluir = producto_id if editar else None
            if database.nombre_producto_existe(nombre, excluir_id=excluir):
                messagebox.showerror("Nombre repetido", "Ya existe un producto con ese nombre.")
                return

            if editar:
                database.actualizar_producto(producto_id, nombre, precio, recargo)
            else:
                database.crear_producto(nombre, precio, recargo)

            self._refrescar_tabla_productos()
            self._cargar_productos()
            win.destroy()

        botones = tb.Frame(frame)
        botones.grid(row=6, column=0, columnspan=2, sticky=E, pady=(10, 0))
        tb.Button(botones, text="Cancelar", command=win.destroy,
                  bootstyle="secondary-outline").pack(side=RIGHT, padx=(8, 0))
        tb.Button(botones, text="Guardar", command=guardar, bootstyle="success").pack(side=RIGHT)

        # Al abrir con datos ya cargados (editar), sincroniza el precio en
        # Bs con el % guardado, por si difieren por redondeo.
        if prod:
            desde_recargo()

    # -------------------------------------------------------- tab historial
    def _build_tab_historial(self):
        filtros = tb.Frame(self.tab_historial)
        filtros.pack(fill=X, pady=(0, 10))

        tb.Label(filtros, text="Desde (AAAA-MM-DD):").pack(side=LEFT, padx=(0, 4))
        self.var_desde = tk.StringVar()
        tb.Entry(filtros, textvariable=self.var_desde, width=12).pack(side=LEFT, padx=(0, 12))

        tb.Label(filtros, text="Hasta (AAAA-MM-DD):").pack(side=LEFT, padx=(0, 4))
        self.var_hasta = tk.StringVar()
        tb.Entry(filtros, textvariable=self.var_hasta, width=12).pack(side=LEFT, padx=(0, 12))

        tb.Label(filtros, text="Buscar en nota/estado:").pack(side=LEFT, padx=(0, 4))
        self.var_texto_buscar = tk.StringVar()
        tb.Entry(filtros, textvariable=self.var_texto_buscar, width=20).pack(side=LEFT, padx=(0, 12))

        tb.Button(filtros, text="Buscar", command=self._buscar_historial,
                   bootstyle="primary").pack(side=LEFT)

        cols = ("fecha", "total_divisa", "total_bs", "tasa", "estado", "nota")
        self.tree_historial = tb.Treeview(self.tab_historial, columns=cols, show="headings",
                                           bootstyle="primary")
        titulos = {"fecha": "Fecha", "total_divisa": "Total US$", "total_bs": "Total Bs",
                   "tasa": "Tasa BCV", "estado": "Estado", "nota": "Nota"}
        anchos = {"fecha": 140, "total_divisa": 100, "total_bs": 110, "tasa": 90,
                  "estado": 190, "nota": 200}
        for c in cols:
            self.tree_historial.heading(c, text=titulos[c])
            self.tree_historial.column(c, width=anchos[c],
                                        anchor=E if c in ("total_divisa", "total_bs", "tasa") else W)
        self.tree_historial.pack(fill=BOTH, expand=True)
        self.tree_historial.bind("<Double-1>", lambda e: self._ver_detalle_venta())

        tb.Label(self.tab_historial, text="Doble clic sobre una venta para ver el detalle de productos y pagos.",
                  bootstyle="secondary").pack(anchor=W, pady=(6, 0))

    def _buscar_historial(self):
        desde = self.var_desde.get().strip() or None
        hasta = self.var_hasta.get().strip() or None
        texto = self.var_texto_buscar.get().strip() or None
        ventas = database.listar_ventas(desde=desde, hasta=hasta, texto=texto)
        self.tree_historial.delete(*self.tree_historial.get_children())
        for v in ventas:
            fecha = v["fecha"].replace("T", " ")
            self.tree_historial.insert("", END, iid=str(v["id"]), values=(
                fecha, fmt_usd(v["total_divisa"]), fmt_bs(v["total_bs"]),
                f"{v['tasa_bcv']:,.2f}", v["estado"], v["nota"] or "",
            ))

    def _ver_detalle_venta(self):
        sel = self.tree_historial.selection()
        if not sel:
            return
        venta_id = int(sel[0])
        detalle = database.obtener_venta(venta_id)
        if not detalle:
            return
        v, items, pagos = detalle["venta"], detalle["items"], detalle["pagos"]

        win = tb.Toplevel(self)
        win.title(f"Venta #{v['id']} - {v['fecha'].replace('T', ' ')}")
        win.geometry("580x620")

        info = tb.Frame(win, padding=14)
        info.pack(fill=X)
        tb.Label(info, text=f"Total: {fmt_usd(v['total_divisa'])} en divisa  ·  {fmt_bs(v['total_bs'])} en bolívares",
                  font=("Segoe UI", 12, "bold")).pack(anchor=W)
        tb.Label(info, text=f"Tasa BCV usada: {v['tasa_bcv']:,.2f}  ({v['tasa_fuente'] or '—'})"
                 ).pack(anchor=W, pady=(4, 0))
        tb.Label(info, text=f"Estado: {v['estado']}").pack(anchor=W, pady=(4, 0))
        if v["nota"]:
            tb.Label(info, text=f"Nota: {v['nota']}").pack(anchor=W, pady=(4, 0))

        tb.Label(win, text="Productos:", font=("Segoe UI", 11, "bold"), padding=(14, 6, 0, 0)
                  ).pack(anchor=W)
        cols_i = ("producto", "cantidad", "sub_divisa", "sub_bs")
        tree_i = tb.Treeview(win, columns=cols_i, show="headings", height=5)
        tree_i.heading("producto", text="Producto")
        tree_i.heading("cantidad", text="Cant.")
        tree_i.heading("sub_divisa", text="Subtotal US$")
        tree_i.heading("sub_bs", text="Subtotal US$ (Bs)")
        for c, w in (("producto", 200), ("cantidad", 60), ("sub_divisa", 110), ("sub_bs", 130)):
            tree_i.column(c, width=w, anchor=E if c != "producto" else W)
        tree_i.pack(fill=X, padx=14, pady=(4, 10))
        for it in items:
            tree_i.insert("", END, values=(
                it["producto"], f"{it['cantidad']:g}",
                fmt_usd(it["subtotal_divisa"]), fmt_usd(it["subtotal_bs_usd_equiv"]),
            ))

        tb.Label(win, text="Pagos:", font=("Segoe UI", 11, "bold"), padding=(14, 6, 0, 0)
                  ).pack(anchor=W)
        cols = ("metodo", "moneda", "monto", "equiv", "fraccion")
        tree = tb.Treeview(win, columns=cols, show="headings", height=6)
        tree.heading("metodo", text="Método")
        tree.heading("moneda", text="Moneda")
        tree.heading("monto", text="Monto")
        tree.heading("equiv", text="Equiv. US$")
        tree.heading("fraccion", text="% cubierto")
        for c, w in (("metodo", 130), ("moneda", 70), ("monto", 110), ("equiv", 100), ("fraccion", 90)):
            tree.column(c, width=w, anchor=E if c != "metodo" else W)
        tree.pack(fill=BOTH, expand=True, padx=14, pady=(4, 14))
        for p in pagos:
            monto_txt = fmt_usd(p["monto_ingresado"]) if p["moneda"] == "USD" else fmt_bs(p["monto_ingresado"])
            tree.insert("", END, values=(p["metodo"], p["moneda"], monto_txt,
                                          fmt_usd(p["monto_usd_equiv"]),
                                          f"{p['fraccion_cubierta'] * 100:,.1f}%"))


if __name__ == "__main__":
    app = MezclillaApp()
    app.mainloop()
