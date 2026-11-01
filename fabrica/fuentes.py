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
