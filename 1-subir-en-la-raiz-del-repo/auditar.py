"""Control SEO del sitio armado (carpeta sitio/), sin internet y sin costo.

Revisa cada página .html: títulos y descripciones (faltan, largo, repetidos), canonical,
noindex, enlaces internos rotos, páginas huérfanas (nadie las enlaza), páginas sin enlaces,
páginas muy escondidas (más de 3 clics desde la portada), imágenes sin texto alternativo,
orden de títulos internos (h1, h2...), contenido muy corto o repetido, y el sitemap.

Uso: python auditar.py   → imprime el informe y escribe sitio-auditoria.md (fuera de sitio/).
En GitHub el informe aparece en el resumen de la ejecución de "Publicar web". Nunca frena la publicación.
"""
import hashlib
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
                "Provincias y municipios": r"^(?:ingresos-brutos|monotributo-unificado|regimen-simplificado|monotasa|tasas?-|alicuotas-)"}
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
