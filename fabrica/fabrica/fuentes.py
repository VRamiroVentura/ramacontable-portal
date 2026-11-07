"""Lectura de fuentes: feeds (RSS) o portadas HTML, y el texto de cada nota.
Adaptado de shorts-fabrica (serie contable)."""
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from . import util

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36",
      "Accept-Language": "es-AR,es;q=0.9"}
GRAPH = "https://graph.facebook.com/v25.0/"

_EXCLUIR_URL = ("/tag/", "/tags/", "/categoria", "/category", "/autor", "/author", "/page/", "/seccion", "/buscar",
                "mailto:", "whatsapp", "javascript:", "#", "/contacto", "/suscri", "/login", "/publicidad")


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _limpio(html_texto):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_texto or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def _bajar(url):
    r = util.pedir("GET", url, intentos=2, espera=3, headers=UA, timeout=40)
    if r is None or r.status_code != 200:
        util.log("No pude leer", url, getattr(r, "status_code", "?"))
        return None
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r


# ---------- Lectura de sitios (RSS o portada HTML) ----------

def _fecha(txt):
    if not txt:
        return None
    try:
        return parsedate_to_datetime(txt)
    except Exception:  # noqa
        pass
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:  # noqa
        return None


def _rss(contenido):
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        return None
    ns_content = "{http://purl.org/rss/1.0/modules/content/}encoded"
    atom = "{http://www.w3.org/2005/Atom}"
    items = []
    for it in raiz.iter("item"):
        items.append({
            "titulo": _limpio(it.findtext("title")),
            "url": (it.findtext("link") or "").strip(),
            "fecha": _fecha(it.findtext("pubDate")),
            "texto": _limpio(it.findtext(ns_content) or it.findtext("description")),
        })
    for it in raiz.iter(atom + "entry"):
        link = it.find(atom + "link")
        items.append({
            "titulo": _limpio(it.findtext(atom + "title")),
            "url": link.get("href", "") if link is not None else "",
            "fecha": _fecha(it.findtext(atom + "updated") or it.findtext(atom + "published")),
            "texto": _limpio(it.findtext(atom + "content") or it.findtext(atom + "summary")),
        })
    return items if (items or raiz.tag in ("rss", atom + "feed")) else None


class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._txt = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._txt = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._txt)).strip()))
            self._href = None


def _portada(html_texto, base):
    p = _Enlaces()
    try:
        p.feed(html_texto)
    except Exception:  # noqa
        pass
    host = urlparse(base).netloc.replace("www.", "")
    vistos, items = set(), []
    for href, txt in p.links:
        if not href or not (35 <= len(txt) <= 220) or txt.count(" ") < 4 or txt.startswith(("http", "/", "www")):
            continue
        url = urljoin(base, href)
        u = urlparse(url)
        if u.netloc.replace("www.", "") != host or u.path.strip("/") == "" or any(x in url.lower() for x in _EXCLUIR_URL):
            continue
        clave = _norm(txt)
        if url in vistos or clave in vistos:
            continue
        vistos.update({url, clave})
        items.append({"titulo": txt, "url": url, "fecha": None, "texto": ""})
    return items


class _Articulo(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.parrafos, self._en_p, self._buf, self._salto = {}, [], 0, [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k in ("og:description", "description", "article:published_time", "og:title"):
                self.meta.setdefault(k, a.get("content") or "")
        elif tag in ("script", "style", "nav", "footer", "aside"):
            self._salto += 1
        elif tag == "p":
            self._en_p, self._buf = 1, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside") and self._salto:
            self._salto -= 1
        elif tag == "p" and self._en_p:
            t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(t) > 60:
                self.parrafos.append(t)
            self._en_p = 0

    def handle_data(self, data):
        if self._en_p and not self._salto:
            self._buf.append(data)


def detalle(url, largo=6000):
    """Texto completo (párrafos) de una nota, para que la IA lea lo que realmente dice."""
    r = _bajar(url)
    if r is None:
        return "", None
    a = _Articulo()
    try:
        a.feed(r.text)
    except Exception:  # noqa
        pass
    texto = " ".join([a.meta.get("og:description", "") or a.meta.get("description", "")] + a.parrafos)
    return texto.strip()[:largo], _fecha(a.meta.get("article:published_time"))


def leer(fuente, dias=3, maximo=25):
    """Lista de novedades recientes de una fuente: [{titulo, url, fecha, texto, fuente, tipo}]."""
    r = _bajar(fuente["url"])
    if r is None:
        return []
    items = _rss(r.content)
    if items is None:
        items = _portada(r.text, fuente["url"])
    filtro = [f.lower() for f in fuente.get("filtro", [])]
    limite = util.ahora() - timedelta(days=dias)
    salida = []
    for it in items[:maximo]:
        if not it["titulo"] or not it["url"]:
            continue
        if it["fecha"] and it["fecha"].astimezone(util.ZONA) < limite:
            continue
        if filtro and not any(f in _norm(it["titulo"] + " " + it["texto"]) for f in filtro):
            continue
        salida.append(dict(it, fuente=fuente["nombre"], tipo=fuente.get("tipo", "portal"),
                           fecha=it["fecha"].isoformat() if it["fecha"] else None))
    return salida


# ---------- Guías: buscar material de referencia ----------

PORTALES_WP = [("Ignacio Online", "https://www.ignacioonline.com.ar"), ("Contadores en Red", "https://contadoresenred.com")]


def buscar_portales(consulta, por_portal=3, portales=None):
    """Busca notas en los portales WordPress (API pública de búsqueda). Devuelve [{fuente, titulo, url, texto}]."""
    salida = []
    for nombre, base in portales or PORTALES_WP:
        r = _bajar(f"{base}/wp-json/wp/v2/posts?search={consulta.replace(' ', '+')}&per_page={por_portal}&_fields=title,link,content")
        try:
            posts = r.json() if r is not None else []
        except Exception:  # noqa
            posts = []
        for p in posts if isinstance(posts, list) else []:
            texto = _limpio((p.get("content") or {}).get("rendered", ""))
            if len(texto) > 300:
                salida.append({"fuente": nombre, "tipo": "portal", "titulo": _limpio((p.get("title") or {}).get("rendered", "")),
                               "url": p.get("link", ""), "texto": texto[:7000]})
    return salida


def _art(norm, marca, desde=0):
    """Posición donde EMPIEZA un artículo (por ejemplo «Art. 158.-» o «ARTICULO 158 —»), no una simple mención."""
    m = re.search(r"\d+", marca or "")
    if not m:
        return -1
    patron = re.compile(r"\bART(?:ICULO|\.)?\s*" + m.group(0) + r"\s*(?:BIS\s*)?[º°O]?\s*[\.\-—–:]")
    hit = patron.search(norm, desde)
    return hit.start() if hit else -1


_OFICIALES = re.compile(r'href=["\'](https?://(?:[\w-]+\.)*(?:gob\.ar|gov\.ar|bcra\.gob\.ar|boletinoficial\.gob\.ar|'
                        r'argentina\.gob\.ar|arca\.gob\.ar|afip\.gob\.ar|infoleg\.gob\.ar|saij\.gob\.ar|gba\.gob\.ar|'
                        r'arba\.gov\.ar|agip\.gob\.ar)[^"\'#\s]*)', re.I)
_NO_NORMA = ("/login", "/contacto", "/buscar", "facebook", "twitter", "/home", "/inicio")


def fuente_oficial_citada(url):
    """Busca en una nota de un portal el link a la fuente oficial (ARCA, Boletín Oficial, BCRA, Infoleg...) y la baja.
    Devuelve {titulo, url, texto, tipo: oficial} o None. Sirve para chequear una nota que vino de un solo portal."""
    r = _bajar(url)
    if r is None:
        return None
    vistos = []
    for u in _OFICIALES.findall(r.text):
        u = u.rstrip(").,;")
        if u not in vistos and not any(x in u.lower() for x in _NO_NORMA) and len(u.split("/", 3)[-1]) > 3:
            vistos.append(u)
    for u in vistos[:3]:
        if u.lower().endswith(".pdf"):
            return {"titulo": "Documento oficial citado", "url": u, "texto": "", "tipo": "oficial", "fuente": "Fuente oficial citada", "pdf": True}
        texto, _ = detalle(u, largo=8000)
        if len(texto) > 300:
            return {"titulo": "Fuente oficial citada", "url": u, "texto": texto, "tipo": "oficial", "fuente": "Fuente oficial citada"}
    return None


def texto_oficial(ref):
    """Fragmento de una norma (por ejemplo, de ARTICULO 150 a ARTICULO 158) para que la guía se apoye en el texto legal."""
    r = _bajar(ref["url"])
    if r is None:
        return ""
    t = _limpio(r.text)
    norm = _norm(t).upper()
    i = _art(norm, ref.get("desde")) if ref.get("desde") else 0
    if i < 0:
        util.log("No encontré", ref.get("desde"), "en", ref["url"])
        return ""
    j = _art(norm, ref.get("hasta"), i + 10) if ref.get("hasta") else -1
    return t[i: j if j > i else i + 15000][:20000]


# ---------- Escalas: documento oficial del sindicato ----------

_FECHA_DOC = re.compile(r"(20\d\d)[-_./ ]?(0[1-9]|1[0-2])?")


def _peso_doc(url, texto):
    """Para elegir el documento más nuevo: año y mes que aparezcan en el nombre o en el texto del link."""
    mejor = (0, 0)
    for a, m in _FECHA_DOC.findall(_norm(url + " " + texto)):
        mejor = max(mejor, (int(a), int(m or 0)))
    return mejor


def documento_oficial(urls, claves=()):
    """Devuelve (url, tipo, contenido) del documento con la escala vigente.
    Si la URL es un PDF, lo baja. Si es una página, busca en ella el PDF más nuevo que coincida con las claves."""
    claves = [_norm(c) for c in claves]
    for url in urls:
        r = _bajar(url)
        if r is None:
            continue
        tipo = (r.headers.get("content-type") or "").lower()
        if "pdf" in tipo or url.lower().split("?")[0].endswith(".pdf"):
            if r.content[:4] == b"%PDF":
                return url, "pdf", r.content
            continue
        links = []
        for href, txt in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text):
            completo = urljoin(url, unescape(href))
            etiqueta = _limpio(txt)
            n = _norm(completo + " " + etiqueta)
            es_doc = ".pdf" in completo.lower() or "download" in n or "descarg" in n
            if es_doc and (not claves or any(c in n for c in claves)):
                links.append((_peso_doc(completo, etiqueta), completo))
        for _, link in sorted(links, reverse=True)[:3]:
            d = _bajar(link)
            if d is not None and d.content[:4] == b"%PDF":
                return link, "pdf", d.content
        texto = _limpio(r.text)
        if len(texto) > 500 and any(c in _norm(texto) for c in ("basico", "categoria", "escala")):
            return url, "html", texto[:20000]
    return None, None, None


def estado(url):
    """Código HTTP de una página (para saber si una publicación fue borrada). None si no respondió."""
    try:
        r = util.pedir("GET", url, intentos=2, espera=3, headers=UA, timeout=40, ok=(200,))
        return getattr(r, "status_code", None)
    except Exception:  # noqa
        return None
