"""
Obtiene la tasa de cambio oficial (BCV) desde internet, con varias
fuentes de respaldo y, si todas fallan, la última tasa guardada o el
ingreso manual.

Orden de fuentes (de la más simple/rápida a la más robusta):
1. dolarapi.com — API pública, la que indicó Gianfranco.
2. pydolarve.org — API pública alternativa, mismo tipo de dato.
3. Scraping directo a bcv.org.ve — el sitio oficial del Banco Central.
   Esta es la fuente "de última instancia": no depende de que un
   tercero mantenga su API funcionando, pero es más frágil (si el BCV
   cambia el HTML de su página, hay que ajustar el selector). El sitio
   del BCV además usa un certificado SSL que la mayoría de los
   clientes HTTP rechazan por defecto, por eso se desactiva la
   verificación SSL solo para esta fuente puntual.

La última tasa obtenida (automática o manual) se guarda en un archivo
local (rate_cache.json) junto a la base de datos, para que la app
arranque con un valor razonable incluso sin internet.
"""

import json
import os
import re
from datetime import datetime

import requests

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rate_cache.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def _fuente_dolarapi(timeout):
    resp = requests.get(
        "https://ve.dolarapi.com/v1/dollars/official",
        headers=HEADERS, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data["promedio"])


def _fuente_pydolarve(timeout):
    resp = requests.get(
        "https://pydolarve.org/api/v1/dollar?page=bcv&format_date=default&rounded_price=true",
        headers=HEADERS, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data["monitors"]["bcv"]["price"])


def _fuente_bcv_scraping(timeout):
    """
    Respaldo robusto: lee directamente la página oficial del BCV
    (https://www.bcv.org.ve/) y extrae el valor del dólar del bloque
    con id="dolar", igual que hace el scraper de referencia que usa
    Mezclilla San Miguel en su backend (Node/cheerio) — aquí la misma
    idea, con requests + BeautifulSoup.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError(
            "Falta la librería beautifulsoup4 para el scraping del BCV "
            "(agrégala con: pip install beautifulsoup4)"
        ) from exc

    resp = requests.get(
        "https://www.bcv.org.ve/",
        headers=HEADERS, timeout=timeout, verify=False,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    contenedor = soup.select_one("#dolar strong")
    if contenedor is None:
        raise ValueError("No se encontró el bloque de la tasa del dólar en bcv.org.ve")

    texto = contenedor.get_text(strip=True)
    # El sitio del BCV usa coma como separador decimal, ej: "189,3456"
    texto_normalizado = re.sub(r"[^\d,\.]", "", texto).replace(",", ".")
    return float(texto_normalizado)


FUENTES = [
    {"nombre": "dolarapi.com (BCV)", "fn": _fuente_dolarapi},
    {"nombre": "pydolarve.org (BCV)", "fn": _fuente_pydolarve},
    {"nombre": "bcv.org.ve (sitio oficial)", "fn": _fuente_bcv_scraping},
]


def obtener_tasa_automatica(timeout=8):
    """
    Intenta obtener la tasa BCV desde las fuentes en línea, en orden.
    Devuelve (tasa, nombre_fuente) o (None, None) si todas fallan.
    """
    # Silenciar el warning de "InsecureRequestWarning" que sale al
    # desactivar la verificación SSL contra bcv.org.ve.
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    for fuente in FUENTES:
        try:
            tasa = fuente["fn"](timeout)
            if tasa and tasa > 0:
                # La tasa BCV se maneja siempre con 2 decimales (como la
                # publica el propio BCV), aunque la fuente entregue más.
                return round(tasa, 2), fuente["nombre"]
        except Exception:
            continue
    return None, None


def guardar_cache(tasa, fuente):
    payload = {
        "tasa": tasa,
        "fuente": fuente,
        "actualizado": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def leer_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def obtener_tasa_inicial():
    """
    Punto de entrada usado al arrancar la app: intenta las fuentes
    automáticas en orden y, si alguna funciona, la guarda en cache. Si
    todas fallan, cae al último valor guardado en cache. Devuelve un
    dict: {"tasa": float|None, "fuente": str, "automatica": bool,
    "actualizado": str|None}.
    """
    tasa, fuente = obtener_tasa_automatica()
    if tasa is not None:
        guardar_cache(tasa, fuente)
        return {
            "tasa": tasa,
            "fuente": fuente,
            "automatica": True,
            "actualizado": datetime.now().isoformat(timespec="seconds"),
        }

    cache = leer_cache()
    if cache:
        return {
            "tasa": cache.get("tasa"),
            "fuente": cache.get("fuente", "cache local"),
            "automatica": False,
            "actualizado": cache.get("actualizado"),
        }

    return {"tasa": None, "fuente": None, "automatica": False, "actualizado": None}
