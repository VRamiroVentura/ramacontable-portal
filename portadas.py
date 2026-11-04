"""Portadas automáticas de cada nota (1200×630): color de la sección, ícono del tema y el dato clave.
Se usan en las tarjetas del portal y al compartir en WhatsApp y redes. Las genera build.py con Pillow."""
import os
import re
import unicodedata


W, H = 1200, 630
VERDE, VERDE2, DORADO, CREMA, TINTA = (19, 39, 31), (29, 58, 46), (176, 140, 82), (244, 239, 227), (27, 37, 32)
ESTILOS = {
    "sueldos": {"fondo": VERDE, "texto": (255, 255, 255), "suave": (196, 210, 200), "acento": DORADO},
    "impuestos": {"fondo": CREMA, "texto": TINTA, "suave": (90, 102, 96), "acento": (138, 106, 54), "cuaderno": True},
    "profesion": {"fondo": (43, 47, 44), "texto": (255, 255, 255), "suave": (200, 200, 195), "acento": DORADO},
    "guia": {"fondo": VERDE2, "texto": (255, 255, 255), "suave": (196, 210, 200), "acento": DORADO},
}
_FUENTES = {}
RAIZ = os.path.dirname(os.path.abspath(__file__))


def _fuente(tipo, tam):
    """Tipografías del portal si están en fuentes/ (las baja el build); si no, DejaVu."""
    from PIL import ImageFont
    candidatos = {
        "serif": [os.path.join(RAIZ, "fuentes", "LibreBaskerville-Bold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
        "sans": [os.path.join(RAIZ, "fuentes", "SourceSans3-Bold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
        "sansr": [os.path.join(RAIZ, "fuentes", "SourceSans3-Regular.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    }[tipo]
    clave = (tipo, tam)
    if clave not in _FUENTES:
        for c in candidatos:
            if os.path.exists(c):
                f = ImageFont.truetype(c, tam)
                if "[" in os.path.basename(c):  # tipografía variable: elegir el grosor
                    try:
                        f.set_variation_by_axes([700 if tipo != "sansr" else 400])
                    except Exception:
                        pass
                _FUENTES[clave] = f
                break
        else:
            _FUENTES[clave] = ImageFont.load_default()
    return _FUENTES[clave]


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def tema_icono(n):
    t = _norm(" ".join([n.get("dato") or "", n.get("antetitulo", ""), n.get("titulo", ""), n.get("tema") or ""]))
    if re.search(r"vence|vencimiento|prorroga|pasa al|plazo|calendario|feriado|cronograma|fecha", t):
        return "calendario"
    if re.search(r"escala|salari|sueldo|paritaria|convenio|aguinaldo|sac\b|recibo|aumento|no remunerativ|bono|vacacion|horas extra|liquidacion|indemniz", t):
        return "recibo"
    if re.search(r"tasa|inflacion|dolar|bcra|cer\b|uva|interes|indice", t):
        return "grafico"
    return "documento"


def _envolver(d, texto, fuente, ancho, max_lineas):
    palabras, lineas, actual = str(texto).split(), [], ""
    for p in palabras:
        prueba = (actual + " " + p).strip()
        if d.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        while lineas[-1] and d.textlength(lineas[-1] + "…", font=fuente) > ancho:
            lineas[-1] = lineas[-1].rsplit(" ", 1)[0]
        lineas[-1] += "…"
    return lineas


def _icono(d, tipo, x, y, s, col, fondo):
    """Íconos simples dibujados (sin imágenes externas). (x, y) = esquina, s = tamaño."""
    lw = max(4, s // 28)
    if tipo == "recibo":
        d.rounded_rectangle([x, y, x + s * 0.78, y + s], radius=s // 14, outline=col, width=lw)
        for i in range(4):
            yy = y + s * (0.22 + i * 0.13)
            d.line([x + s * 0.12, yy, x + s * (0.45 if i % 2 else 0.6), yy], fill=col, width=lw)
            d.line([x + s * 0.55, yy, x + s * 0.66, yy], fill=col, width=lw)
        d.line([x + s * 0.12, y + s * 0.8, x + s * 0.66, y + s * 0.8], fill=col, width=lw * 2)
        cx, cy, r = x + s * 0.85, y + s * 0.18, s * 0.17
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        f = _fuente("sans", int(r * 1.3))
        d.text((cx, cy), "$", font=f, fill=fondo, anchor="mm")
    elif tipo == "calendario":
        d.rounded_rectangle([x, y + s * 0.08, x + s, y + s], radius=s // 12, outline=col, width=lw)
        d.rectangle([x, y + s * 0.08, x + s, y + s * 0.3], fill=col)
        for i in (0.25, 0.75):
            d.line([x + s * i, y, x + s * i, y + s * 0.18], fill=col, width=lw * 2)
        for fila in range(3):
            for colm in range(4):
                cx, cy = x + s * (0.17 + colm * 0.22), y + s * (0.45 + fila * 0.17)
                d.rounded_rectangle([cx - s * 0.06, cy - s * 0.05, cx + s * 0.06, cy + s * 0.05], radius=3,
                                    fill=col if (fila, colm) == (1, 2) else None, outline=col, width=max(2, lw // 2))
    elif tipo == "grafico":
        d.line([x, y + s, x + s, y + s], fill=col, width=lw)
        d.line([x, y, x, y + s], fill=col, width=lw)
        for i, h in enumerate((0.35, 0.55, 0.45, 0.8)):
            bx = x + s * (0.12 + i * 0.22)
            d.rectangle([bx, y + s * (1 - h), bx + s * 0.14, y + s - lw], fill=col)
        d.line([x + s * 0.1, y + s * 0.5, x + s * 0.4, y + s * 0.3, x + s * 0.6, y + s * 0.4, x + s * 0.95, y + s * 0.05], fill=col, width=lw)
    else:  # documento con sello
        d.polygon([(x, y), (x + s * 0.55, y), (x + s * 0.78, y + s * 0.22), (x + s * 0.78, y + s), (x, y + s)], outline=col, width=lw)
        d.line([x + s * 0.55, y, x + s * 0.55, y + s * 0.22, x + s * 0.78, y + s * 0.22], fill=col, width=lw)
        for i in range(4):
            yy = y + s * (0.38 + i * 0.12)
            d.line([x + s * 0.12, yy, x + s * (0.66 if i < 3 else 0.4), yy], fill=col, width=lw)
        cx, cy, r = x + s * 0.8, y + s * 0.82, s * 0.2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=lw)
        d.line([cx - r * 0.45, cy, cx - r * 0.1, cy + r * 0.4, cx + r * 0.5, cy - r * 0.35], fill=col, width=lw)


def bajar_fuentes():
    """Baja las tipografías del portal (licencia libre OFL) desde el repositorio de Google Fonts, una vez por publicación."""
    import urllib.request
    base = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
    archivos = {"LibreBaskerville-Bold.ttf": ["librebaskerville/LibreBaskerville-Bold.ttf", "librebaskerville/LibreBaskerville%5Bwght%5D.ttf"],
                "SourceSans3-Bold.ttf": ["sourcesans3/SourceSans3%5Bwght%5D.ttf"], "SourceSans3-Regular.ttf": ["sourcesans3/SourceSans3%5Bwght%5D.ttf"]}
    os.makedirs(os.path.join(RAIZ, "fuentes"), exist_ok=True)
    for nombre, rutas in archivos.items():
        destino = os.path.join(RAIZ, "fuentes", nombre)
        if os.path.exists(destino):
            continue
        for r in rutas:
            try:
                datos = urllib.request.urlopen(base + r, timeout=30).read()
                if len(datos) > 10000:
                    open(destino, "wb").write(datos)
                    break
            except Exception as ex:
                print("Aviso: no pude bajar la tipografía", nombre, ex)


def disponible():
    try:
        import PIL  # noqa
        return True
    except Exception:
        return False


def generar(n, destino):
    """Crea la portada de la nota n en destino (.png). Devuelve la ruta."""
    from PIL import Image, ImageDraw
    clave = "guia" if n.get("tipo") == "guia" else (n.get("seccion") if n.get("seccion") in ESTILOS else "profesion")
    e = ESTILOS[clave]
    img = Image.new("RGB", (W, H), e["fondo"])
    d = ImageDraw.Draw(img)
    if e.get("cuaderno"):  # hoja de cuaderno contable, como los videos de impuestos
        for yy in range(70, H, 38):
            d.line([0, yy, W, yy], fill=(214, 222, 228), width=2)
        d.line([92, 0, 92, H], fill=(214, 120, 110), width=3)
    else:
        d.rectangle([0, 0, W, 10], fill=e["acento"])
    margen = 130 if e.get("cuaderno") else 80
    ante = str(n.get("antetitulo") or ("Guía práctica" if clave == "guia" else "")).upper()[:70]
    d.text((margen, 62), ante, font=_fuente("sans", 26), fill=e["acento"])
    y = 120
    ancho_texto = 760
    dato = (n.get("dato") or "").strip()
    if dato:
        tam = 92
        while tam > 50 and d.textlength(dato, font=_fuente("serif", tam)) > ancho_texto:
            tam -= 4
        d.text((margen, y), dato, font=_fuente("serif", tam), fill=e["acento"])
        y += tam + 34
    # título: se achica la letra hasta que entre completo (máximo 4 líneas)
    disponible = H - 120 - y
    for tam in range(56 if not dato else 46, 29, -2):
        ft = _fuente("serif", tam)
        lineas = _envolver(d, n.get("titulo", ""), ft, ancho_texto, 99)
        if len(lineas) * tam * 1.25 <= disponible and len(lineas) <= 4:
            break
    lineas = _envolver(d, n.get("titulo", ""), ft, ancho_texto, 4)
    for linea in lineas:
        d.text((margen, y), linea, font=ft, fill=e["texto"])
        y += int(tam * 1.25)
    _icono(d, tema_icono(n), 935, 175, 210, e["acento"], e["fondo"])
    # pie con la marca
    d.line([margen, H - 92, W - 80, H - 92], fill=e["acento"], width=2)
    d.text((margen, H - 70), "ramacontable", font=_fuente("serif", 34), fill=e["texto"])
    d.text((W - 80, H - 62), "ramacontable.com.ar", font=_fuente("sansr", 24), fill=e["suave"], anchor="ra")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, "PNG", optimize=True)
    return destino
