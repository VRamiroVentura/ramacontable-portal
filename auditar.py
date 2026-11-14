"""Control SEO del sitio armado (carpeta sitio/), sin internet y sin costo.

Revisa cada página .html: títulos y descripciones (faltan, largo, repetidos), canonical,
noindex, enlaces internos rotos, páginas huérfanas (nadie las enlaza), páginas sin enlaces,
páginas muy escondidas (más de 3 clics desde la portada), imágenes sin texto alternativo,
orden de títulos internos (h1, h2...), contenido muy corto o repetido, y el sitemap.

Uso: python auditar.py   → imprime el informe y escribe sitio-auditoria.md (fuera de sitio/).
En GitHub el informe aparece en el resumen de la ejecución de "Publicar web". Nunca frena la publicación.
"""
import hashlib
import json
import os
import re
import sys
from collections import defaultdict, deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote

RAIZ = os.path.dirname(os.path.abspath(__file__))
SITIO = os.path.join(RAIZ, "sitio")
INFORME = os.path.join(RAIZ, "sitio-auditoria.md")

# Páginas que no se indexan a propósito (admin, buscar, etc.): no se exigen descripciones ni enlaces.
TITULO_MIN, TITULO_MAX = 25, 65
DESC_MIN, DESC_MAX = 70, 160
PALABRAS_MIN = 250
PROFUNDIDAD_MAX = 3
FUERA_DE_SITEMAP_OK = {"terminos.html"}   # páginas legales: se indexan pero no hace falta mandarlas en el sitemap


class Lector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titulo, self.desc, self.canonical, self.robots = None, None, None, ""
        self.enlaces, self.imgs_sin_alt, self.headings = [], 0, []
        self._en_titulo, self._salto = False, 0
        self._en_h = None
        self.texto = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "template"):
            self._salto += 1
        elif tag == "title":
            self._en_titulo, self.titulo = True, ""
        elif tag == "meta":
            n = (a.get("name") or "").lower()
            if n == "description":
                self.desc = a.get("content") or ""
            elif n == "robots":
                self.robots += " " + (a.get("content") or "").lower()
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "a" and a.get("href"):
            self.enlaces.append(a["href"])
        elif tag == "img":
            if not (a.get("alt") or "").strip() and a.get("alt") != "" and a.get("role") != "presentation":
                self.imgs_sin_alt += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self._salto = max(0, self._salto - 1)
        elif tag == "title":
            self._en_titulo = False

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo += data
        elif not self._salto:
            self.texto.append(data)


def leer_sitemap(base):
    urls = set()
    for nombre in os.listdir(SITIO):
        if nombre.startswith("sitemap") and nombre.endswith(".xml"):
            with open(os.path.join(SITIO, nombre), encoding="utf-8") as f:
                for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", f.read()):
                    urls.add(loc)
    return urls


def ruta_de_url(url, base):
    """URL absoluta del sitio → ruta relativa dentro de sitio/ (o None si es externa)."""
    if not url.startswith(base):
        return None
    r = unquote(urlparse(url[len(base):]).path).lstrip("/")
    return r or "index.html"


# ---------------------------------------------------------------------------
# Controles por página tomados de claude-seo (scripts/page_checks.py), de Agrici Daniel, licencia MIT:
# https://github.com/AgriciDaniel/claude-seo — se reprogramaron acá con los mismos umbrales
# (relevancia del título 30% y de la descripción 20% con 50+ palabras; HTML de más de 2 MB),
# con palabras vacías en español.
# ---------------------------------------------------------------------------
HTML_MAX_BYTES = 2_000_000
TITULO_RELEVANCIA_MIN, DESC_RELEVANCIA_MIN, RELEVANCIA_MIN_PALABRAS = 0.3, 0.2, 50
VACIAS = frozenset("""a al algo algun alguna algunas alguno algunos ante antes aqui asi aun bajo bien cada como con contra cual cuales cuando
de del desde donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto estos fue fueron ha
hace hasta hay la las le les lo los mas me mi muy nada ni no nos o otra otras otro otros para pero poco por porque que quien
se sea ser si sin sobre son su sus tambien tan te tiene tienen todo todos tu un una unas uno unos ya y ramacontable hoy""".split())


class Revisor(HTMLParser):
    """Junta lo que necesitan los controles por página."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.c = defaultdict(int)          # cantidad de title / description / canonical / robots
        self.og_url = self.og_img = self.canonical = self.lang = None
        self.viewport = False
        self.jsonld, self._en_ld, self._ld = [], False, []
        self.imgs = []                     # (tiene medidas, lazy, en main)
        self.links_sin_texto = []
        self._link = None
        self._main = 0
        self._cromo = 0                    # nav / header / footer / aside
        self._salto = 0
        self.visible = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self.c["title"] += 1
        elif tag == "meta":
            n, pr = (a.get("name") or "").lower(), (a.get("property") or "").lower()
            if n in ("description", "robots"):
                self.c[n] += 1
            elif n == "viewport":
                self.viewport = True
            elif pr == "og:url":
                self.og_url = a.get("content")
            elif pr == "og:image":
                self.og_img = a.get("content")
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.c["canonical"] += 1
            self.canonical = a.get("href")
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._en_ld, self._ld = True, []
        if tag in ("script", "style", "noscript", "template"):
            self._salto += 1
        if tag in ("nav", "header", "footer", "aside"):
            self._cromo += 1
        if tag == "main":
            self._main += 1
        if tag == "img":
            self.imgs.append((bool(a.get("width") and a.get("height")), (a.get("loading") or "").lower() == "lazy", self._main > 0 and not self._cromo))
            if self._link is not None and (a.get("alt") or "").strip():
                self._link["txt"] += " " + a["alt"]
        if tag == "svg" and self._link is not None and (a.get("aria-label") or ""):
            self._link["txt"] += " " + a["aria-label"]
        if tag == "a" and a.get("href") and not a["href"].startswith(("#", "javascript:", "mailto:", "tel:")):
            self._link = {"href": a["href"], "txt": (a.get("aria-label") or a.get("title") or "")}

    def handle_endtag(self, tag):
        if tag == "script" and self._en_ld:
            self.jsonld.append("".join(self._ld))
            self._en_ld = False
        if tag in ("script", "style", "noscript", "template"):
            self._salto = max(0, self._salto - 1)
        if tag in ("nav", "header", "footer", "aside"):
            self._cromo = max(0, self._cromo - 1)
        if tag == "main":
            self._main = max(0, self._main - 1)
        if tag == "a" and self._link is not None:
            if not self._link["txt"].strip():
                self.links_sin_texto.append(self._link["href"])
            self._link = None

    def handle_data(self, data):
        if self._en_ld:
            self._ld.append(data)
        if self._link is not None:
            self._link["txt"] += data
        if not self._salto and self._main and not self._cromo:
            self.visible.append(data)


def terminos(texto):
    return [w for w in re.findall(r"[a-záéíóúñü]{3,}", (texto or "").lower()) if w not in VACIAS]


def controles_pagina(rel, p, problemas, base):
    """Controles por página (ver Revisor). p es el Lector de la página, con título y descripción ya leídos."""
    ruta = os.path.join(SITIO, rel)
    tam = os.path.getsize(ruta)
    rv = Revisor()
    with open(ruta, encoding="utf-8", errors="replace") as f:
        html_txt = f.read()
    rv.feed(html_txt)
    if tam > HTML_MAX_BYTES:
        problemas["html-mas-2mb"].append((rel, f"{tam // 1000} KB"))
    if not html_txt.lstrip().lower().startswith("<!doctype html"):
        problemas["sin-doctype"].append((rel, ""))
    if not rv.lang:
        problemas["sin-idioma"].append((rel, ""))
    if not rv.viewport:
        problemas["sin-viewport"].append((rel, ""))
    dup = [k for k in ("title", "description", "canonical", "robots") if rv.c[k] > 1]
    if dup:
        problemas["etiquetas-duplicadas"].append((rel, ", ".join(f"{k} ×{rv.c[k]}" for k in dup)))
    for i, bloque in enumerate(rv.jsonld, 1):
        try:
            json.loads(bloque)
        except Exception as ex:
            problemas["jsonld-invalido"].append((rel, f"bloque {i}: {str(ex)[:80]}"))
    if rv.canonical and rv.og_url and rv.og_url.rstrip("/") != rv.canonical.rstrip("/"):
        problemas["og-url-distinta"].append((rel, f"og:url {rv.og_url}"))
    if not rv.og_img:
        problemas["sin-imagen-para-compartir"].append((rel, ""))
    sin_medidas = sum(1 for m, _, _ in rv.imgs if not m)
    if sin_medidas:
        problemas["imagen-sin-medidas"].append((rel, f"{sin_medidas} imagen(es)"))
    en_main = [x for x in rv.imgs if x[2]]
    if en_main and en_main[0][1]:
        problemas["primera-imagen-diferida"].append((rel, ""))
    if rv.links_sin_texto:
        problemas["link-sin-texto"].append((rel, f"{len(rv.links_sin_texto)}: {', '.join(rv.links_sin_texto[:3])}"))
    if "noindex" not in p.robots:
        cuerpo = set(terminos(" ".join(rv.visible)))
        if len(cuerpo) >= RELEVANCIA_MIN_PALABRAS:
            for campo, minimo, cod in ((p.titulo, TITULO_RELEVANCIA_MIN, "titulo-no-refleja"), (p.desc, DESC_RELEVANCIA_MIN, "descripcion-no-refleja")):
                ts = set(terminos(campo))
                if ts and len(ts & cuerpo) / len(ts) < minimo:
                    problemas[cod].append((rel, f"{round(100 * len(ts & cuerpo) / len(ts))}% de sus palabras en el texto; faltan: {', '.join(sorted(ts - cuerpo)[:6])}"))


MESES_A = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
TEXTO_PROPIO_MIN = 40


def cuerpo_principal(rel):
    """Texto del contenido principal (sin menú, barra lateral ni pie)."""
    with open(os.path.join(SITIO, rel), encoding="utf-8", errors="replace") as f:
        t = f.read()
    m = re.search(r"<main[^>]*>(.*)</main>", t, re.S)
    t = m.group(1) if m else t
    t = re.sub(r"<(script|style|aside|nav)[^>]*>.*?</\1>", " ", t, flags=re.S)
    return re.sub(r"<[^>]+>", " ", t)


def main():
    informe, _ = auditar()
    with open(INFORME, "w", encoding="utf-8") as f:
        f.write(informe)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(informe + "\n")
    print(informe)
    return 0


def auditar():
    """Devuelve (informe en markdown, datos) para el control diario y el informe semanal."""
    if not os.path.isdir(SITIO):
        return "No existe sitio/: corré primero python build.py", {}
    paginas = {}
    for carpeta, _, archivos in os.walk(SITIO):
        for a in archivos:
            if a.endswith(".html"):
                rel = os.path.relpath(os.path.join(carpeta, a), SITIO).replace(os.sep, "/")
                with open(os.path.join(carpeta, a), encoding="utf-8", errors="replace") as f:
                    lec = Lector()
                    lec.feed(f.read())
                paginas[rel] = lec

    # Base del sitio: la sale del canonical de la portada.
    base = ""
    if "index.html" in paginas and paginas["index.html"].canonical:
        c = paginas["index.html"].canonical
        base = c[: c.rfind("/") + 1]

    def destino(origen, href):
        href = href.split("#")[0].split("?")[0]
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:", "whatsapp:")):
            return None
        absoluto = urljoin(base + origen, href) if base else None
        if href.startswith(("http://", "https://", "//")):
            return ruta_de_url(href, base) if base else None
        if absoluto:
            return ruta_de_url(absoluto, base)
        return os.path.normpath(os.path.join(os.path.dirname(origen), href)).replace(os.sep, "/")

    problemas = defaultdict(list)  # código → [(página, detalle)]
    entrantes = defaultdict(set)
    salientes = {}
    for rel, p in paginas.items():
        controles_pagina(rel, p, problemas, base)
        noindex = "noindex" in p.robots
        destinos = set()
        for href in p.enlaces:
            d = destino(rel, href)
            if d is None:
                continue
            if d.endswith("/"):
                d += "index.html"
            if not os.path.exists(os.path.join(SITIO, d)):
                problemas["enlace-roto"].append((rel, href))
                continue
            if d.endswith(".html") and d != rel:
                destinos.add(d)
                entrantes[d].add(rel)
        salientes[rel] = destinos
        if noindex:
            continue
        t = (p.titulo or "").strip()
        if not t:
            problemas["sin-titulo"].append((rel, ""))
        elif len(t) > TITULO_MAX:
            problemas["titulo-largo"].append((rel, f"{len(t)} car.: {t}"))
        elif len(t) < TITULO_MIN:
            problemas["titulo-corto"].append((rel, f"{len(t)} car.: {t}"))
        d = (p.desc or "").strip()
        if not d:
            problemas["sin-descripcion"].append((rel, ""))
        elif len(d) > DESC_MAX:
            problemas["descripcion-larga"].append((rel, f"{len(d)} car."))
        elif len(d) < DESC_MIN:
            problemas["descripcion-corta"].append((rel, f"{len(d)} car.: {d}"))
        if not p.canonical:
            problemas["sin-canonical"].append((rel, ""))
        elif base and ruta_de_url(p.canonical, base) not in (rel, rel.replace("index.html", "")):
            problemas["canonical-a-otra"].append((rel, p.canonical))
        h1 = p.headings.count(1)
        if h1 == 0:
            problemas["sin-h1"].append((rel, ""))
        elif h1 > 1:
            problemas["varios-h1"].append((rel, f"{h1} h1"))
        for x, y in zip(p.headings, p.headings[1:]):
            if y > x + 1:
                problemas["titulos-salteados"].append((rel, f"h{x} → h{y}"))
                break
        if p.imgs_sin_alt:
            problemas["imagen-sin-alt"].append((rel, f"{p.imgs_sin_alt} imagen(es)"))
        if not destinos:
            problemas["sin-enlaces-internos"].append((rel, ""))

    indexables = {r for r, p in paginas.items() if "noindex" not in p.robots}

    # Repetidos (solo páginas indexables).
    for campo, codigo in (("titulo", "titulo-repetido"), ("desc", "descripcion-repetida")):
        grupos = defaultdict(list)
        for r in indexables:
            v = (getattr(paginas[r], campo) or "").strip().lower()
            if v:
                grupos[v].append(r)
        for v, rs in grupos.items():
            if len(rs) > 1:
                problemas[codigo].append((", ".join(sorted(rs)), v[:90]))

    textos = {}
    grupos_texto = defaultdict(list)
    for r in indexables:
        palabras = re.findall(r"\w+", " ".join(paginas[r].texto).lower())
        textos[r] = len(palabras)
        grupos_texto[hashlib.md5(" ".join(palabras).encode()).hexdigest()].append(r)
    for rs in grupos_texto.values():
        if len(rs) > 1:
            problemas["contenido-repetido"].append((", ".join(sorted(rs)), ""))

    # Profundidad desde la portada.
    prof = {"index.html": 0}
    cola = deque(["index.html"])
    while cola:
        r = cola.popleft()
        for d in salientes.get(r, ()):
            if d not in prof:
                prof[d] = prof[r] + 1
                cola.append(d)

    sitemap = leer_sitemap(base) if base else set()
    en_sitemap = {ruta_de_url(u, base) for u in sitemap}
    for u in sorted(sitemap):
        r = ruta_de_url(u, base)
        if r and r.endswith("/"):
            r += "index.html"
        if r and not os.path.exists(os.path.join(SITIO, r)):
            problemas["sitemap-a-pagina-inexistente"].append((u, ""))
        elif r in paginas and "noindex" in paginas[r].robots:
            problemas["sitemap-con-noindex"].append((r, ""))

    for r in sorted(indexables):
        if r == "index.html":
            continue
        if not entrantes.get(r):
            problemas["huerfana"].append((r, "nadie la enlaza" + (" (está en el sitemap)" if r in en_sitemap else "")))
        elif r not in prof:
            problemas["no-se-llega-desde-portada"].append((r, ""))
        elif prof[r] > PROFUNDIDAD_MAX:
            problemas["muy-escondida"].append((r, f"{prof[r]} clics desde la portada"))
        if textos.get(r, 0) < PALABRAS_MIN:
            problemas["poco-contenido"].append((r, f"{textos[r]} palabras"))
        if base and sitemap and r not in en_sitemap and r not in FUERA_DE_SITEMAP_OK:
            problemas["fuera-del-sitemap"].append((r, ""))

    # Texto propio en las familias de páginas automáticas (criterio de «contenido en masa» de Google):
    # palabras que aparecen en menos del 10% de las páginas de la familia, sobre el total de la página.
    familias = {"Escalas por convenio": r"^escala-", "Datos por mes": r"-(?:" + "|".join(MESES_A) + r")-\d{4}\.html$",
                "Provincias y municipios": r"^(?:ingresos-brutos|monotributo-unificado|regimen-simplificado|monotasa|tasas-municipales|alicuotas-|licencia-|patente-)"}
    unicidad = {}
    for nombre_f, patron in familias.items():
        grupo = [r for r in indexables if re.search(patron, r) and not r.startswith(("nota-", "que-cambia-"))]
        if len(grupo) < 3:
            continue
        cuerpos = {r: re.findall(r"[a-záéíóúñü]{3,}", cuerpo_principal(r).lower()) for r in grupo}
        cuenta = defaultdict(int)
        for ws in cuerpos.values():
            for w in set(ws):
                cuenta[w] += 1
        tope = max(2, len(grupo) // 10)  # 2: el mismo dato en dos meses comparte su explicación
        pct = {r: round(100 * sum(1 for w in ws if cuenta[w] <= tope) / len(ws)) if ws else 0 for r, ws in cuerpos.items()}
        flacas = sorted([r for r in grupo if pct[r] < TEXTO_PROPIO_MIN and len(cuerpos[r]) < 300], key=lambda r: pct[r])
        unicidad[nombre_f] = {"paginas": len(grupo), "flacas": len(flacas), "promedio": round(sum(pct.values()) / len(grupo))}
        for r in flacas:
            problemas["poco-texto-propio"].append((r, f"{nombre_f}: {pct[r]}% propio, {len(cuerpos[r])} palabras"))

    NOMBRES = {
        "jsonld-invalido": ("🔴", "Datos estructurados (JSON-LD) mal escritos: Google los ignora"),
        "html-mas-2mb": ("🔴", "Páginas de más de 2 MB (Google lee solo los primeros 2 MB)"),
        "etiquetas-duplicadas": ("🟠", "Etiquetas repetidas (title, description, canonical o robots)"),
        "titulo-no-refleja": ("🟠", "Títulos cuyas palabras casi no aparecen en el texto de la página"),
        "descripcion-no-refleja": ("🟡", "Descripciones cuyas palabras casi no aparecen en el texto"),
        "og-url-distinta": ("🟡", "Link para compartir (og:url) distinto de la dirección oficial"),
        "sin-imagen-para-compartir": ("🟡", "Páginas sin imagen para compartir (og:image)"),
        "imagen-sin-medidas": ("🟡", "Imágenes sin ancho y alto (la página salta mientras carga)"),
        "primera-imagen-diferida": ("🟡", "La primera imagen del contenido carga tarde (lazy)"),
        "link-sin-texto": ("🟡", "Links sin texto ni nombre (íconos sin descripción)"),
        "sin-doctype": ("🟡", "Páginas sin <!doctype html>"),
        "sin-idioma": ("🟡", "Páginas sin idioma declarado"),
        "sin-viewport": ("🟡", "Páginas sin ajuste para celular (viewport)"),
        "poco-texto-propio": ("🟠", f"Páginas automáticas con menos de {TEXTO_PROPIO_MIN}% de texto propio y menos de 300 palabras"),
        "enlace-roto": ("🔴", "Enlaces internos rotos"),
        "sitemap-a-pagina-inexistente": ("🔴", "El sitemap apunta a páginas que no existen"),
        "sin-titulo": ("🔴", "Páginas sin título"),
        "canonical-a-otra": ("🔴", "Canonical que apunta a otra página"),
        "sitemap-con-noindex": ("🔴", "Páginas en el sitemap pero marcadas noindex"),
        "huerfana": ("🟠", "Páginas huérfanas (ninguna otra las enlaza)"),
        "titulo-repetido": ("🟠", "Títulos repetidos"),
        "descripcion-repetida": ("🟠", "Descripciones repetidas"),
        "contenido-repetido": ("🟠", "Contenido idéntico en varias páginas"),
        "sin-descripcion": ("🟠", "Páginas sin descripción"),
        "sin-canonical": ("🟠", "Páginas sin canonical"),
        "sin-h1": ("🟠", "Páginas sin título principal (h1)"),
        "no-se-llega-desde-portada": ("🟠", "No se llega navegando desde la portada"),
        "fuera-del-sitemap": ("🟠", "Páginas indexables que no están en el sitemap"),
        "titulo-largo": ("🟡", f"Títulos de más de {TITULO_MAX} caracteres (Google los corta)"),
        "titulo-corto": ("🟡", f"Títulos de menos de {TITULO_MIN} caracteres"),
        "descripcion-larga": ("🟡", f"Descripciones de más de {DESC_MAX} caracteres"),
        "descripcion-corta": ("🟡", f"Descripciones de menos de {DESC_MIN} caracteres"),
        "varios-h1": ("🟡", "Más de un h1"),
        "titulos-salteados": ("🟡", "Títulos internos salteados (ej. h2 → h4)"),
        "imagen-sin-alt": ("🟡", "Imágenes sin texto alternativo"),
        "sin-enlaces-internos": ("🟡", "Páginas sin enlaces a otras páginas del sitio"),
        "muy-escondida": ("🟡", f"Páginas a más de {PROFUNDIDAD_MAX} clics de la portada"),
        "poco-contenido": ("🟡", f"Páginas con menos de {PALABRAS_MIN} palabras"),
    }
    orden = {"🔴": 0, "🟠": 1, "🟡": 2}
    lineas = [f"# Auditoría SEO del sitio", "",
              f"{len(paginas)} páginas revisadas ({len(indexables)} indexables).", ""]
    total = 0
    for cod in sorted(problemas, key=lambda c: (orden[NOMBRES[c][0]], c)):
        icono, nombre = NOMBRES[cod]
        items = problemas[cod]
        total += len(items)
        lineas.append(f"## {icono} {nombre}: {len(items)}")
        for pag, det in items[:25]:
            lineas.append(f"- {pag}" + (f" — {det}" if det else ""))
        if len(items) > 25:
            lineas.append(f"- … y {len(items) - 25} más")
        lineas.append("")
    if not total:
        lineas.append("Sin problemas. 👌")
    if unicidad:
        lineas += ["## Texto propio por familia de páginas automáticas", ""] + [
            f"- {k}: {v['paginas']} páginas indexables, {v['promedio']}% de texto propio en promedio, {v['flacas']} flacas" for k, v in unicidad.items()]
    datos = {"paginas": len(paginas), "indexables": len(indexables), "unicidad": unicidad,
             "conteo": {cod: len(v) for cod, v in problemas.items()},
             "nombres": {cod: NOMBRES[cod] for cod in problemas},
             "detalle": {cod: v[:10] for cod, v in problemas.items()}}
    return "\n".join(lineas), datos


if __name__ == "__main__":
    sys.exit(main())
