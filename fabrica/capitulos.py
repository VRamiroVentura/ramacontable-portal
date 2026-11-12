"""Series por capítulos (series/*.json): la fábrica toma el próximo capítulo pendiente y lo arma animado.

- El capítulo funciona como un tema pedido: sus datos están chequeados a mano y el guion no puede salirse de ahí.
- Los montos (topes y cuotas) se toman del portal el día del video; si no se pueden leer, el video no los dice.
- Los capítulos hechos quedan en data/estado.json → temas_hechos (igual que los temas pedidos).
- La animación (Remotion, carpeta animaciones/) se arma después del guion: cada escena recibe una pieza.
"""
import json
import re
from pathlib import Path

from . import util

CARPETA = util.RAIZ / "series"
GUIONES = util.RAIZ / "data" / "guiones"
MONTOS = "data/montos_monotributo.json"
PORTAL_MONTOS = "https://ramacontable.com.ar/monotributo-categorias-vigentes.html"
# Respaldo: escala vigente desde el 1/8/2026 (ARCA). Solo se usa hasta el 31/1/2027.
RESPALDO = {
    "vigencia": "desde el 1 de agosto de 2026", "vence": "2027-01-31",
    "tope_A": "$12.009.410,45", "tope_K": "$126.610.838,75", "precio_max": "$716.840,77",
    "cuota_A": "$49.527,18", "cuota_K_servicios": "$1.614.446,04", "cuota_K_bienes": "$702.103,24",
}
NOMBRES = {
    "tope_A": "Tope de facturación anual de la categoría A (la más baja)",
    "tope_K": "Tope de facturación anual de la categoría K (la más alta)",
    "precio_max": "Precio máximo por unidad para quien vende productos",
    "cuota_A": "Cuota mensual de la categoría A (servicios y productos)",
    "cuota_K_servicios": "Cuota mensual de la categoría K para servicios",
    "cuota_K_bienes": "Cuota mensual de la categoría K para venta de productos",
}
PIEZAS = ("titulo", "barrido", "checklist", "etiquetas", "banda")
ICONOS = ("factura", "moneda", "caja_fuerte", "calendario", "recibo_sueldo", "persona", "casa", "calculadora",
          "lupa", "billetera", "alerta", "check", "grafico", "maletin")


# ---------------------------------------------------------------- series y capítulos
def _series(cfg):
    orden = cfg.get("capitulos_orden") or []
    archivos = {p.stem: p for p in sorted(CARPETA.glob("*.json"))} if CARPETA.exists() else {}
    claves = [k for k in orden if k in archivos] + [k for k in archivos if k not in orden]
    salida = []
    for k in claves:
        try:
            salida.append(json.loads(archivos[k].read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            util.log(f"Serie {k}: el archivo tiene un error ({e}); la salteo.")
    return salida


def _hechos():
    return set((util.leer_json("data/estado.json", {}) or {}).get("temas_hechos", []))


def proximo(cfg):
    hechos = _hechos()
    for s in _series(cfg):
        for c in s.get("capitulos", []):
            if c.get("id") and c["id"] not in hechos:
                return s, c
    return None, None


def serie_de_hoy(cfg):
    """La clave de serie para la grilla: "capitulos" si el próximo capítulo tiene su guion guardado (revisado con
    tiempo); si no, None y va la serie de respaldo. Nunca se arma un capítulo sin guion previo."""
    s, c = proximo(cfg)
    if not (c and "capitulos" in cfg["series"]):
        return None
    if not guion(c["id"]):
        util.avisar("El capítulo de hoy no tiene guion revisado",
                    f"«{c.get('titulo')}» no salió: falta su guion en data/guiones/{c['id']}.json. Va la serie de respaldo.")
        return None
    return "capitulos"


# ---------------------------------------------------------------- guiones guardados (se revisan 2 días antes)
def guion(cap_id):
    return util.leer_json(f"data/guiones/{cap_id}.json", None)


def contenido_guardado(cap_id):
    g = guion(cap_id) or {}
    c = g.get("contenido")
    return c if isinstance(c, dict) and c.get("escenas") else None


def guardar_guion(tema, contenido, estado="para revisar"):
    GUIONES.mkdir(parents=True, exist_ok=True)
    util.guardar_json(f"data/guiones/{tema['id']}.json", {
        "id": tema["id"], "titulo": tema.get("titulo", ""), "estado": estado,
        "actualizado": util.ahora().strftime("%Y-%m-%d %H:%M"),
        "_ayuda": "Podés corregir el texto de cada escena (texto_voz = lo que dice la voz; texto_pantalla = lo que se "
                  "lee). Respetá las comillas y las comas. O usá el workflow «Corregir guion» y escribí los cambios.",
        "contenido": contenido})


def mail_revision(tema, contenido, asunto_extra=""):
    import html
    import os
    from . import publicar
    repo = os.getenv("GITHUB_REPOSITORY", "VRamiroVentura/shorts-fabrica")
    piezas = ((contenido.get("animacion") or {}).get("piezas") or [])
    filas = []
    for i, e in enumerate(contenido.get("escenas", [])):
        pieza = piezas[i].get("tipo", "") if i < len(piezas) else ""
        filas.append(f"<tr><td style='vertical-align:top;padding:6px 10px;color:#888'>{i + 1}</td>"
                     f"<td style='padding:6px 10px'>{html.escape(e.get('texto_voz', ''))}<br>"
                     f"<small style='color:#888'>En pantalla: {html.escape(e.get('texto_pantalla', ''))} · pieza: {pieza}</small></td></tr>")
    cuerpo = (f"<h2>{html.escape(tema.get('titulo', ''))}</h2>"
              "<p><b>Sale el miércoles a las 20:00 con este guion, palabra por palabra.</b> Revisalo con tiempo.</p>"
              f"<table style='border-collapse:collapse'>{''.join(filas)}</table>"
              f"<p><b>Título:</b> {html.escape(contenido.get('titulo', ''))}<br><b>Descripción:</b> "
              f"{html.escape(contenido.get('descripcion', ''))}</p>"
              "<h3>Si querés cambiar algo</h3><ul>"
              f"<li>Escribí los cambios en <a href='https://github.com/{repo}/actions/workflows/corregir-guion.yml'>"
              "Corregir guion</a> (Run workflow) y te llega este mail de nuevo.</li>"
              f"<li>O editá el texto directo: <a href='https://github.com/{repo}/edit/main/data/guiones/{tema['id']}.json'>"
              f"data/guiones/{tema['id']}.json</a>.</li>"
              "<li>Si está bien, no hagas nada.</li></ul>"
              "<h3>Datos que usó (chequeados)</h3><pre style='white-space:pre-wrap'>" + html.escape(tema.get("datos", "")) + "</pre>")
    return publicar.mail(f"URGENTE: revisá el capítulo del miércoles{asunto_extra} · {tema.get('titulo', '')}", cuerpo)


def _buscar(cap_id, cfg=None):
    for s in _series(cfg or util.config()):
        for c in s.get("capitulos", []):
            if c.get("id") == cap_id:
                return s, c
    return None, None


# ---------------------------------------------------------------- montos del portal
def _limpio(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def _formato_ok(v):
    return isinstance(v, str) and re.fullmatch(r"\$\s?\d{1,3}(\.\d{3})*(,\d{1,2})?", v.strip()) is not None


def montos(cfg):
    """{clave: "$..."} vigentes, leídos del portal (con caché del día). Si falla, el respaldo mientras esté vigente."""
    hoy = util.ahora().strftime("%Y-%m-%d")
    cache = util.leer_json(MONTOS, {}) or {}
    if cache.get("fecha") == hoy and cache.get("valores"):
        return cache["valores"]
    valores = {}
    try:
        r = util.pedir("GET", cfg.get("capitulos_portal_montos", PORTAL_MONTOS), intentos=2, timeout=40)
        if r is not None and r.status_code == 200:
            from . import escritor
            pedido = ("De este texto de una página con las categorías vigentes del monotributo, devolvé SOLO un JSON con "
                      "estas claves y los montos tal cual aparecen, en formato \"$12.345,67\": " +
                      ", ".join(f'"{k}" ({v})' for k, v in NOMBRES.items()) +
                      ', y "vigencia" (desde cuándo rigen, en palabras). Si un dato no está, no lo pongas.\n\nTEXTO:\n'
                      + _limpio(r.text)[:12000])
            d = escritor._json_de(escritor.gemini("Extraés datos exactos de una página. Respondés solo JSON.", pedido, 0.1))
            valores = {k: str(v).strip() for k, v in (d or {}).items() if k in NOMBRES and _formato_ok(str(v))}
            if valores and d.get("vigencia"):
                valores["vigencia"] = str(d["vigencia"])[:80]
    except Exception as e:  # noqa
        util.log("No pude leer los montos del portal:", util.ocultar(e))
    if len([k for k in valores if k in NOMBRES]) < 3:
        if hoy <= RESPALDO["vence"]:
            util.log("Montos: uso los de respaldo (escala de ARCA vigente).")
            valores = {k: v for k, v in RESPALDO.items() if k != "vence"}
        else:
            util.avisar("No pude leer los montos del monotributo",
                        "El capítulo sale sin montos y manda al portal para verlos.")
            valores = {}
    util.guardar_json(MONTOS, {"fecha": hoy, "valores": valores})
    return valores


# ---------------------------------------------------------------- el capítulo como tema pedido
def _tema(cfg, s, c):
    total = len([x for x in s.get("capitulos", []) if not x.get("suelto")])
    datos = c.get("datos", "")
    pedidos = c.get("montos") or []
    if pedidos:
        m = montos(cfg)
        lineas = [f"- {NOMBRES[k]}: {m[k]}" for k in pedidos if k in m]
        if lineas:
            datos += (f"\nMONTOS VIGENTES ({m.get('vigencia', 'escala actual')}; se actualizan en febrero y agosto, "
                      "decilo así y mandá a chequear el valor de hoy al portal):\n" + "\n".join(lineas))
        else:
            datos += "\nNO hay montos confirmados hoy: no digas ningún monto; decí que los valores de hoy están en el portal."
    encabezado = ("Capítulo suelto de la serie" if c.get("suelto") else f"Capítulo {c.get('numero')} de {total} de la serie")
    prompt = (f"{encabezado} «{s.get('nombre')}». {c.get('titulo')}.\n"
              f"TONO: {s.get('tono', '')}\n"
              f"GUÍA DEL CAPÍTULO: {c.get('prompt', '')}\n"
              "- El video arranca diciendo de qué capítulo se trata (por ejemplo: \"Capítulo 2: lo que pagás todos los meses\"), "
              "salvo que sea un capítulo suelto.\n"
              "- Es un video animado: escribí escenas cortas y claras, una idea por escena (el texto en pantalla va en "
              "pocas palabras).\n"
              "- El cierre ya está escrito: la última escena la reemplaza la fábrica.")
    return {"id": c["id"], "serie": "capitulos", "titulo": c.get("titulo", ""), "prompt": prompt, "datos": datos,
            "cierre": c.get("cierre") or {}, "palabras_max": c.get("palabras_max", 130),
            "fuente": "ARCA y ramacontable.com.ar", "fecha_datos": util.ahora().strftime("%d/%m/%Y"),
            "capitulo": {"serie_id": s.get("id"), "serie": s.get("nombre"), "numero": c.get("numero"),
                         "total": total, "suelto": bool(c.get("suelto")), "portada_tipo": s.get("portada_tipo", "cero"),
                         "portada": c.get("portada") or {}, "proximo": c.get("proximo", ""),
                         "destino": c.get("destino", ""), "cierre_pantalla": (c.get("cierre") or {}).get("pantalla", "")}}


def tema_de_hoy(cfg):
    s, c = proximo(cfg)
    if not c:
        return None
    t = _tema(cfg, s, c)
    util.log(f"Capítulo de hoy: {s.get('nombre')} · {c.get('titulo')} ({c['id']})")
    return t


def tema_por_id(cap_id):
    cfg = util.config()
    s, c = _buscar(cap_id, cfg)
    return _tema(cfg, s, c) if c else None


# ---------------------------------------------------------------- animación
def _corto(t, n=60):
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def _pieza_valida(p, escena):
    tipo = p.get("tipo")
    if tipo not in PIEZAS:
        return None
    icono = p.get("icono") if p.get("icono") in ICONOS else None
    if tipo == "titulo":
        texto = _corto(p.get("texto") or escena.get("texto_pantalla"), 48)
        return {"tipo": "titulo", "texto": texto, **({"icono": icono} if icono else {}),
                **({"cinta": _corto(p["cinta"], 28)} if p.get("cinta") else {})} if texto else None
    if tipo == "barrido":
        texto = _corto(p.get("texto"), 18)
        return {"tipo": "barrido", "texto": texto} if texto else None
    if tipo == "checklist":
        items = [_corto(x, 24) for x in (p.get("items") or []) if str(x).strip()][:4]
        if len(items) < 2:
            return None
        activo = p.get("activo") if isinstance(p.get("activo"), int) else 0
        return {"tipo": "checklist", "titulo": _corto(p.get("titulo") or "", 30), "items": items,
                "activo": max(0, min(activo, len(items) - 1)), "icono": icono or "check"}
    if tipo == "etiquetas":
        palabra = _corto(p.get("palabra"), 14)
        cintas = [_corto(x, 28) for x in (p.get("cintas") or []) if str(x).strip()][:2]
        orb = p.get("icono_orbita") if p.get("icono_orbita") in ICONOS else "moneda"
        return {"tipo": "etiquetas", "palabra": palabra, "cintas": cintas, "icono_orbita": orb} if palabra else None
    if tipo == "banda":
        texto = _corto(p.get("texto"), 22)
        numero = p.get("numero") if isinstance(p.get("numero"), int) else 1
        return {"tipo": "banda", "numero": numero, "texto": texto, "icono": icono or "factura",
                **({"detalle": _corto(p["detalle"], 70)} if p.get("detalle") else {})} if texto else None
    return None


def _de_respaldo(escena, i):
    """Si la IA no eligió una pieza válida: título escrito con el texto en pantalla, alternando el ícono."""
    return {"tipo": "titulo", "texto": _corto(escena.get("texto_pantalla") or escena.get("texto_voz"), 48),
            "icono": ICONOS[(i * 5) % len(ICONOS)]}


def animar(contenido, tema):
    """Le asigna una pieza animada a cada escena. Primera = portada; última = cierre al portal."""
    cap = (tema or {}).get("capitulo") or {}
    escenas = contenido.get("escenas") or []
    if not cap or len(escenas) < 3:
        return contenido
    medio = escenas[1:-1]
    elegidas = {}
    try:
        from . import escritor
        pedido = (
            "Para cada escena de este video animado elegí UNA pieza visual. Devolvé solo un JSON: "
            '{"piezas": [{"escena": n, "tipo": "...", ...}]}. Tipos y campos:\n'
            '- titulo: {"texto": "frase corta en pantalla (máx 6 palabras)", "icono": "...", "cinta": "opcional"}\n'
            '- barrido: {"texto": "1 a 3 palabras grandes, ej. 3 partes"} (para anunciar algo; máx una vez)\n'
            '- checklist: {"titulo": "...", "items": ["2 a 4 ítems cortos"], "activo": 0}\n'
            '- etiquetas: {"palabra": "UNA palabra clave", "cintas": ["1 o 2 frases cortas"], "icono_orbita": "moneda"}\n'
            '- banda: {"numero": 1, "texto": "título corto", "icono": "...", "detalle": "frase corta opcional"}\n'
            "Íconos posibles: " + ", ".join(ICONOS) + ".\n"
            "Variá las piezas (no repitas la misma dos veces seguidas). Los textos en pantalla salen de lo que dice la "
            "escena, sin datos nuevos. Si una escena dice un monto, ponelo tal cual en la pieza.\n\nESCENAS:\n" +
            "\n".join(f"{k}. {e.get('texto_voz')}" for k, e in enumerate(medio, start=1)))
        d = escritor._json_de(escritor.gemini("Sos diseñador de videos animados explicativos. Respondés solo JSON.",
                                              pedido, 0.4)) or {}
        for p in d.get("piezas") or []:
            try:
                n = int(p.get("escena"))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(medio):
                v = _pieza_valida(p, medio[n - 1])
                if v:
                    elegidas[n] = v
    except Exception as e:  # noqa
        util.log("No pude elegir las piezas animadas con la IA; uso las de respaldo:", util.ocultar(e))
    piezas = []
    # portada
    if cap.get("suelto"):
        piezas.append({"tipo": "titulo", "texto": _corto(tema.get("titulo"), 48), "icono": "calculadora",
                       "cinta": "¿Cuál te conviene?"})
    else:
        port = cap.get("portada") or {}
        piezas.append({"tipo": "portada", "titulo": _corto(port.get("tema") or tema.get("titulo"), 40),
                       "icono": port.get("icono") if port.get("icono") in ICONOS else "factura",
                       **({"cinta": _corto(port.get("nicho"), 28)} if port.get("nicho") else {})})
    for k, e in enumerate(medio, start=1):
        piezas.append(elegidas.get(k) or _de_respaldo(e, k))
    texto_cierre = re.sub(r"\s*ramacontable\.com\.ar\s*$", "", cap.get("cierre_pantalla") or "").strip() or "Más info en"
    piezas.append({"tipo": "cierre", "texto": _corto(texto_cierre, 40),
                   "web": "ramacontable.com.ar", **({"proximo": _corto(cap["proximo"], 32)} if cap.get("proximo") else {})})
    serie = None if cap.get("suelto") else {"nombre": cap.get("serie"), "capitulo": cap.get("numero"), "total": cap.get("total")}
    port = dict(cap.get("portada") or {})
    portada = ({"tipo": "vs"} if (cap.get("suelto") or port.get("tipo") == "vs") else
               {"tipo": cap.get("portada_tipo", "cero"), "capitulo": cap.get("numero"), "total": cap.get("total"),
                "tema": port.get("tema", ""), "icono": port.get("icono", "lupa"), "nicho": port.get("nicho", ""),
                **({"grande": port["grande"]} if port.get("grande") else {})})
    return dict(contenido, animacion={"serie": serie, "piezas": piezas}, portada_animada=portada)


def con_destino(contenido, tema):
    """Suma a la descripción el link a la guía del capítulo en el portal (si no está)."""
    url = ((tema or {}).get("capitulo") or {}).get("destino", "")
    desc = contenido.get("descripcion", "")
    if not url or url in desc:
        return contenido
    return dict(contenido, descripcion=(desc.rstrip() + "\nGuía completa: " + url).strip())


# ---------------------------------------------------------------- render (lo llama el montaje)
def renderizar(contenido, tiempos, total, trabajo):
    """Arma el fondo animado completo y la portada con Remotion. Devuelve (video, portada) o (None, None)."""
    import subprocess
    anim = contenido.get("animacion") or {}
    piezas = anim.get("piezas") or []
    carpeta = util.RAIZ / "animaciones"
    if not piezas or len(piezas) != len(tiempos) or not (carpeta / "node_modules").exists():
        util.log("Animación: no se puede armar (faltan piezas o no está instalado Remotion); va con clips.")
        return None, None
    escenas = []
    for k, (p, (ini, fin)) in enumerate(zip(piezas, tiempos)):
        seg = max(0.8, fin - ini)
        if k == len(piezas) - 1:
            seg = max(seg, total - ini) + 0.8  # un poco de aire al final para que el fondo no quede corto
        escenas.append(dict(p, segundos=round(seg, 3)))
    props = {"serie": anim.get("serie"), "escenas": escenas, "conSubtitulos": True}
    trabajo = Path(trabajo)
    ruta_props = trabajo / "animacion.json"
    ruta_props.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    video = trabajo / "animacion.mp4"
    try:
        subprocess.run(["npx", "remotion", "render", "src/index.ts", "Explicativo", str(video),
                        f"--props={ruta_props}", "--log=error"], cwd=carpeta, check=True, timeout=1500)
    except Exception as e:  # noqa
        util.avisar("No pude armar la animación", f"El video sale con clips. Detalle: {util.ocultar(e)}")
        return None, None
    portada = None
    if contenido.get("portada_animada"):
        ruta_p = trabajo / "portada.json"
        ruta_p.write_text(json.dumps(contenido["portada_animada"], ensure_ascii=False), encoding="utf-8")
        destino = trabajo / "portada.png"
        try:
            subprocess.run(["npx", "remotion", "still", "src/index.ts", "Portada", str(destino),
                            f"--props={ruta_p}", "--log=error"], cwd=carpeta, check=True, timeout=600)
            portada = destino
        except Exception as e:  # noqa
            util.log("No pude armar la portada animada; queda la de siempre:", util.ocultar(e))
    return video, portada
