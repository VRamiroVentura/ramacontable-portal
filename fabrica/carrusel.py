"""Arma las placas del carrusel (1080x1350, formato vertical de Instagram)."""
from pathlib import Path

from PIL import Image, ImageDraw

from . import marca as m

W, H = 1080, 1350
MARGEN = 84
WEB = "ramacontable.com.ar"
# Temas contables: llevan la web en las placas y en la última "Más información en ramacontable.com.ar"
SERIES_CONTABLES = ("impuestos",)
PALABRAS_CONTABLES = ("arca", "afip", "monotribut", "ganancias", "siradig", "iva", "impuesto", "factura",
                      "aportes", "contribuciones", "sueldo", "recibo", "aguinaldo", "indemnizacion", "convenio",
                      "empleador", "cuit", "clave fiscal", "ingresos brutos", "arba", "bienes personales")


def es_contable(contenido, serie_nombre=""):
    import re
    import unicodedata

    def normal(t):
        return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()

    if any(x in normal(serie_nombre) for x in SERIES_CONTABLES):
        return True
    texto = " ".join([str(contenido.get("titulo", ""))] + [str(h) for h in contenido.get("hashtags", [])] +
                     [f'{p.get("titulo", "")} {p.get("cuerpo", "") or p.get("texto", "")}'
                      for p in contenido.get("carrusel", [])])
    texto = " " + re.sub(r"[^a-z0-9 ]+", " ", normal(texto)) + " "
    return sum(1 for x in PALABRAS_CONTABLES if f" {x}" in texto) >= 2


def _pill(d, x, y, texto, fondo, color, size=30):
    f = m.fuente("bold", size)
    ancho = d.textlength(texto, font=f)
    d.rounded_rectangle([x, y, x + ancho + 44, y + size + 26], radius=(size + 26) // 2, fill=fondo)
    d.text((x + 22, y + 13), texto, font=f, fill=color)


def _flecha(d, x_der, y_centro, color, largo=46):
    d.line([x_der - largo, y_centro, x_der - 4, y_centro], fill=color, width=5)
    d.polygon([(x_der, y_centro), (x_der - 16, y_centro - 12), (x_der - 16, y_centro + 12)], fill=color)


def _pie(d, usuario, color, derecha="Deslizá", flecha=True):
    f = m.fuente("semibold", 32)
    d.text((MARGEN, H - 92), usuario, font=f, fill=color)
    x = W - MARGEN
    if flecha:
        _flecha(d, x, H - 74, color)
        x -= 64
    if derecha:
        d.text((x, H - 92), derecha, font=f, fill=color, anchor="ra")


def _titulo(d, texto, y, color, max_lineas, inicio, ancho=W - 2 * MARGEN):
    estilo = "titulo" if m.es_anton() else "bold"
    f, lineas = m.ajustar(d, texto.upper() if m.es_anton() else texto, estilo, ancho, max_lineas, inicio, 48)
    return m.escribir(d, (MARGEN, y), lineas, f, color, interlineado=1.05)


def portada(placa, serie, usuario, ilustracion=None):
    img = Image.new("RGB", (W, H), m.AMARILLO)
    d = ImageDraw.Draw(img)
    _pill(d, MARGEN, 90, serie.upper(), m.NEGRO, m.AMARILLO)
    y = _titulo(d, placa.get("titulo", ""), 210, m.NEGRO, 4, 150)
    if placa.get("cuerpo"):
        f, lineas = m.ajustar(d, placa["cuerpo"], "semibold", W - 2 * MARGEN, 2, 46, 34)
        y = m.escribir(d, (MARGEN, y + 40), lineas, f, m.NEGRO)
    zona_top = int(y + 40)
    zona_alto = H - 150 - zona_top
    if ilustracion and Path(ilustracion).exists() and zona_alto > 260:
        lado = min(zona_alto, 640)
        pic = Image.open(ilustracion).convert("RGB").resize((lado, lado), Image.LANCZOS)
        mask = Image.new("L", (lado, lado), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, lado, lado], 40, fill=255)
        x = W - MARGEN - lado
        d.rounded_rectangle([x - 8, zona_top - 8, x + lado + 8, zona_top + lado + 8], 46, fill=m.NEGRO)
        img.paste(pic, (x, zona_top), mask)
    elif zona_alto > 200:
        lado = min(zona_alto, 380)
        m.pegar_emoji(img, placa.get("emoji", ""), (W - MARGEN - lado / 2, zona_top + zona_alto / 2), lado)
    _pie(d, usuario, m.NEGRO)
    return img


def interior(placa, n, total, usuario, oscura=False, web=False):
    fondo, texto, acento = (m.NEGRO, m.BLANCO, m.AMARILLO) if oscura else (m.CREMA, m.NEGRO, m.AMARILLO)
    img = Image.new("RGB", (W, H), fondo)
    d = ImageDraw.Draw(img)
    # número de placa
    d.ellipse([MARGEN, 84, MARGEN + 92, 176], fill=acento)
    d.text((MARGEN + 46, 130), str(n), font=m.fuente("bold", 44), fill=m.NEGRO, anchor="mm")
    d.text((W - MARGEN, 112), f"{n}/{total}", font=m.fuente("semibold", 30), fill=m.GRIS if not oscura else acento, anchor="ra")
    y = _titulo(d, placa.get("titulo", ""), 240, acento if oscura else m.NEGRO, 3, 104)
    d.rectangle([MARGEN, y + 26, MARGEN + 140, y + 36], fill=acento)
    f, lineas = m.ajustar(d, placa.get("cuerpo", ""), "regular", W - 2 * MARGEN, 8, 58, 38)
    y = m.escribir(d, (MARGEN, y + 80), lineas, f, texto, interlineado=1.32)
    lado = 270
    cx, cy = W - MARGEN - lado / 2, H - 170 - lado / 2
    if cy - lado / 2 > y + 20:
        d.ellipse([cx - lado / 2 - 30, cy - lado / 2 - 30, cx + lado / 2 + 30, cy + lado / 2 + 30],
                  fill=(255, 236, 140) if not oscura else (45, 45, 45))
        m.pegar_emoji(img, placa.get("emoji", ""), (cx, cy), lado)
    _pie(d, usuario, m.GRIS if not oscura else acento, derecha=WEB if web else "", flecha=n < total)
    return img


def cierre(placa, usuario, web=False):
    img = Image.new("RGB", (W, H), m.AMARILLO)
    d = ImageDraw.Draw(img)
    m.pegar_emoji(img, placa.get("emoji", "📌"), (W / 2, 330), 260)
    estilo = "titulo" if m.es_anton() else "bold"
    t = placa.get("titulo", "Guardalo para después")
    f, lineas = m.ajustar(d, t.upper() if m.es_anton() else t, estilo, W - 2 * MARGEN, 3, 120, 56)
    y = m.escribir(d, (W / 2, 520), lineas, f, m.NEGRO, interlineado=1.05, anchor="ma")
    cuerpo = placa.get("cuerpo") or ""
    if web and WEB in cuerpo:  # la web va fija abajo: no la repetimos en el texto
        cuerpo = ""
    if cuerpo:
        f2, l2 = m.ajustar(d, cuerpo, "semibold", W - 2 * MARGEN, 3, 46, 34)
        y = m.escribir(d, (W / 2, y + 30), l2, f2, m.NEGRO, anchor="ma")
    if web:
        fw = m.fuente("bold", 40)
        tw = "Más información en " + WEB
        if d.textlength(tw, font=fw) > W - 2 * MARGEN:
            fw = m.fuente("bold", 34)
        yw = max(y + 40, H - 380)
        if yw + 60 > H - 270:  # si el título es largo, la web va más chica, pegada al usuario
            yw, fw = H - 330, m.fuente("bold", 32)
        ancho = d.textlength(tw, font=fw)
        d.rounded_rectangle([W / 2 - ancho / 2 - 30, yw - 8, W / 2 + ancho / 2 + 30, yw + fw.size + 18],
                            radius=(fw.size + 26) // 2, fill=m.BLANCO)
        d.text((W / 2, yw + 5), tw, font=fw, fill=m.NEGRO, anchor="ma")
    fu = m.fuente("bold", 52)
    ancho = d.textlength(usuario, font=fu)
    d.rounded_rectangle([W / 2 - ancho / 2 - 40, H - 260, W / 2 + ancho / 2 + 40, H - 170], 45, fill=m.NEGRO)
    d.text((W / 2, H - 215), usuario, font=fu, fill=m.AMARILLO, anchor="mm")
    d.text((W / 2, H - 120), "Guardalo  ·  Compartilo  ·  Seguinos", font=m.fuente("semibold", 32),
           fill=m.NEGRO, anchor="mm")
    return img


def generar(contenido, serie_nombre, usuario, carpeta, ilustracion=None):
    """Devuelve la lista de rutas JPG de las placas."""
    web = es_contable(contenido, serie_nombre)
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    placas = contenido["carrusel"]
    total = len(placas)
    rutas = []
    for i, p in enumerate(placas, start=1):
        if i == 1:
            img = portada(p, serie_nombre, usuario, ilustracion)
        elif i == total:
            img = cierre(p, usuario, web=web)
        else:
            img = interior(p, i, total, usuario, oscura=(i == total - 1), web=web)
        ruta = carpeta / f"placa{i:02d}.jpg"
        img.save(ruta, "JPEG", quality=92)
        rutas.append(ruta)
    return rutas
