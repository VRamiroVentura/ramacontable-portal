"""Utilidades de la fábrica de notas (tomadas de shorts-fabrica)."""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

RAIZ = Path(__file__).resolve().parent.parent
ZONA = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora():
    return datetime.now(ZONA)


def config():
    p = RAIZ / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def secreto(nombre):
    v = os.getenv(nombre, "").strip()
    return v or None


def log(*a):
    print("[notas]", *a, flush=True)


_SECRETOS = ["GEMINI_API_KEY", "SUPABASE_SECRET_KEY", "SMTP_USER", "SMTP_PASS", "GITHUB_TOKEN"]


def ocultar(texto):
    texto = str(texto)
    for n in _SECRETOS:
        v = os.getenv(n, "").strip()
        if len(v) >= 6:
            texto = texto.replace(v, "***")
    return re.sub(r"([?&](?:key|access_token|token|apikey)=)[^&\s]+", r"\1***", texto)


def resumen(md):
    """Escribe en la portada de la ejecución de GitHub (o en pantalla si se corre a mano)."""
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    else:
        print(md)


def avisar(titulo, mensaje):
    msg = ocultar(mensaje)[:1500]
    print(f"::warning title={titulo}::" + msg.replace("%", "%25").replace("\r", "").replace("\n", "%0A"), flush=True)
    resumen(f"> ⚠️ **{titulo}**: {msg}\n")


def pedir(metodo, url, intentos=4, espera=5, ok=(200, 201, 202, 204), **kw):
    """requests con reintentos para errores temporales (429 y 5xx)."""
    kw.setdefault("timeout", 120)
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.request(metodo, url, **kw)
            if r.status_code in ok:
                return r
            ultimo = r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(espera * (i + 1))
                continue
            return r
        except requests.RequestException as e:  # noqa
            ultimo = e
            time.sleep(espera * (i + 1))
    if isinstance(ultimo, Exception):
        raise ultimo
    return ultimo
