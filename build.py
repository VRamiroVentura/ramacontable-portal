"""Arma la web estática del portal Ramacontable.

Lee las notas de la carpeta notas/ (un .json por nota) y genera en sitio/:
portada, una página por sección y una página por nota.
Las claves públicas de Supabase se toman de las variables de entorno
SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (en GitHub vienen de los Secrets).
"""
import html, json, os, re, shutil, glob, datetime, urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
VERSION = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M")  # evita que el navegador muestre archivos viejos
SALIDA = os.path.join(RAIZ, "sitio")

SECCIONES = {
    "sueldos": "Sueldos",
    "impuestos": "Impuestos",
    "profesion": "Profesión",
    "economia": "Economía",
}
REDES = {
    "Instagram": "https://www.instagram.com/ramacontable",
    "YouTube": "https://www.youtube.com/@ramacontable",
    "TikTok": "https://www.tiktok.com/@ramacontable",
}
MAIL = "ramacontable@gmail.com"
MENU = {"sueldos": "Sueldos", "impuestos": "Impuestos", "guias": "Guías", "economia": "Economía"}
RAMAS_GUIAS = {"sueldos": "Guías de sueldos", "impuestos": "Guías de impuestos", "profesion": "Guías contables y de la profesión"}
es_guia = lambda n: n.get("tipo") == "guia"


def sitio_url():
    try:
        u = json.load(open(os.path.join(RAIZ, "config.json"), encoding="utf-8")).get("sitio_url", "")
    except Exception:
        u = ""
    return (u or "https://vramiroventura.github.io/ramacontable-portal/").rstrip("/") + "/"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

e = html.escape
LOGO_SVG = '<svg class="isotipo" viewBox="0 0 48 48" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M24 44V24"/><path d="M24 31 12 19v-6"/><path d="M24 31l12-12v-6"/><path d="M24 24V9"/></g><g fill="#A8844F"><circle cx="12" cy="10" r="3.6"/><circle cx="24" cy="6.5" r="3.6"/><circle cx="36" cy="10" r="3.6"/></g></svg>'


def fecha_larga(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def cargar_aportes():
    """Trae los paso a paso publicados para que Google los lea (la página los vuelve a cargar al abrirse)."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return {}
    try:
        req = urllib.request.Request(
            url + "/rest/v1/pasos?select=nota,titulo,porque,texto_pdf,contenido,perfiles(nombre)&order=creado.asc",
            headers={"apikey": key, "Authorization": "Bearer " + key})
        datos = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as ex:
        print("Aviso: no se pudieron leer los aportes:", ex)
        return {}
    por_nota = {}
    for p in datos:
        por_nota.setdefault(p["nota"], []).append(p)
    return por_nota


def texto_plano(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def pasos_estaticos(lista):
    if not lista:
        return ""
    items = []
    for p in lista:
        autor = (p.get("perfiles") or {}).get("nombre", "")
        cuerpo = texto_plano(p.get("contenido"))[:3000]
        extra = (p.get("texto_pdf") or "")[:3000]
        items.append(f'<div class="aporte"><p class="autor"><b>{e(autor)}</b></p><h4>{e(p["titulo"])}</h4>'
                     f'<p>{e(cuerpo)}</p><p>{e(extra)}</p><div class="dato porque-caja"><b>¿Por qué se hace así? </b>{e(p["porque"])}</div></div>')
    return "".join(items)


def notas_supabase():
    """Notas publicadas en Supabase (las escribe la fábrica y las edita el administrador)."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        req = urllib.request.Request(url + "/rest/v1/notas?select=*&estado=eq.publicada&order=fecha.desc&limit=2000",
                                     headers={"apikey": key, "Authorization": "Bearer " + key})
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as ex:
        print("Aviso: no se pudieron leer las notas de Supabase:", ex)
        return None


_NO_PUBLICADAS = None


def no_publicada(slug):
    """True si la nota existe en Supabase pero no está publicada (borrada o en revisión)."""
    global _NO_PUBLICADAS
    if _NO_PUBLICADAS is None:
        _NO_PUBLICADAS = set()
        url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        if url and key:
            try:
                req = urllib.request.Request(url + "/rest/v1/rpc/slugs_no_publicados", data=b"{}", method="POST",
                                             headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"})
                _NO_PUBLICADAS = set(json.load(urllib.request.urlopen(req, timeout=30)) or [])
            except Exception as ex:
                print("Aviso: no se pudo consultar notas retiradas:", ex)
    return slug in _NO_PUBLICADAS


def cargar_notas():
    locales = {}
    for ruta in glob.glob(os.path.join(RAIZ, "notas", "*.json")):
        with open(ruta, encoding="utf-8") as f:
            n = json.load(f)
        locales[n["slug"]] = n
    remotas = notas_supabase()
    if remotas is None:
        notas = list(locales.values())
    else:
        # Supabase manda: si una nota se editó o se borró allá, vale lo de allá
        todas = {r["slug"]: r for r in remotas}
        for s, n in locales.items():
            if s not in todas and not no_publicada(s):
                todas[s] = n
        notas = list(todas.values())
    notas.sort(key=lambda n: (str(n["fecha"]), n["slug"]), reverse=True)
    return notas


def cargar_convenios():
    locales = {}
    for ruta in glob.glob(os.path.join(RAIZ, "convenios", "*.json")):
        with open(ruta, encoding="utf-8") as f:
            c = json.load(f)
        locales[c["slug"]] = c
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if url and key:
        try:
            req = urllib.request.Request(url + "/rest/v1/convenios?select=*", headers={"apikey": key, "Authorization": "Bearer " + key})
            for c in json.load(urllib.request.urlopen(req, timeout=30)):
                locales[c["slug"]] = c
        except Exception as ex:
            print("Aviso: no se pudieron leer los convenios:", ex)
    return sorted(locales.values(), key=lambda c: c["nombre"])


def tabla_html(t):
    if not t:
        return ""
    cab = "".join(f"<th>{e(str(x))}</th>" for x in t[0])
    filas = "".join("<tr>" + "".join(f"<td>{e(str(x))}</td>" for x in f) + "</tr>" for f in t[1:])
    return f'<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{filas}</tbody></table></div>'


def pagina_convenio(c, notas, aportes=None):
    esc = c.get("escala") or {}
    periodo = esc.get("periodo") or ""
    seccion = lambda titulo, bloques: (f"<h2>{titulo}</h2>" + "".join(bloque(x) for x in bloques)) if bloques else ""
    if esc.get("tabla"):
        escala = (f'<p class="periodo"><b>Período:</b> {e(periodo)}' + (f' · <b>Vigencia:</b> {e(esc.get("vigencia",""))}' if esc.get("vigencia") else "") + "</p>"
                  + tabla_html(esc["tabla"]) + (f'<p class="ayuda">{e(esc.get("aclaraciones",""))}</p>' if esc.get("aclaraciones") else ""))
    else:
        escala = '<div class="vacio-caja"><b>Escala pendiente de carga</b>Se actualiza automáticamente con el próximo acuerdo salarial publicado.</div>'
    relacionadas_c = [n for n in notas if n.get("convenio") == c["slug"]][:8]
    hist = c.get("historial") or []
    hist_html = ("<h2>Historial de escalas</h2><ul class='historial'>" + "".join(
        f'<li><b>{e(h.get("periodo",""))}</b>' + (f' · <a href="nota-{e(h["nota"])}.html">ver nota</a>' if h.get("nota") else "") + "</li>" for h in hist[::-1]) + "</ul>") if hist else ""
    notas_html = ("<h2>Notas sobre este convenio</h2><ul class='historial'>" + "".join(
        f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a> <small>{fecha_larga(n["fecha"])}</small></li>' for n in relacionadas_c) + "</ul>") if relacionadas_c else ""
    falsa_nota = {"preguntas": c.get("preguntas") or []}
    slug = "convenio-" + c["slug"]
    titulo_vis = f"Escala salarial {c['nombre']}" + (f" {periodo}" if periodo else "")
    contenido = f"""<div class="grilla"><article class="nota convenio" data-nota="{slug}" data-convenio="{e(c['slug'])}" data-actualizado="{e(str(c.get('actualizado') or ''))}">
<div class="nota-contenido">
<p class="miga"><a href="sueldos.html">Sueldos</a> / <a href="convenios.html">Convenios</a></p>
<p class="ante">{e(c['cct'])} | {e(c['partes'])}</p>
<h1>{e(titulo_vis)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(str(c.get('actualizado') or datetime.date.today().isoformat())[:10])}</p>
<div class="encorto"><b>Quiénes están comprendidos</b><p>{e(c.get('descripcion',''))}</p></div>
<h2>Escala vigente</h2>{escala}
{seccion("Qué cambió con el último acuerdo", c.get("novedades"))}
{seccion("Cómo se calcula", c.get("calculo"))}
{seccion("Sumas no remunerativas: aportes y contribuciones", c.get("nr"))}
{seccion("Cómo figura en el recibo", c.get("recibo"))}
{preguntas_html(falsa_nota)}
{hist_html}{notas_html}
{f'<p class="fuente"><b>Fuente:</b> {e(c["fuente"])}</p>' if c.get("fuente") else ""}
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en el acuerdo homologado y en las fuentes oficiales. Cada profesional es responsable de su aplicación.</p>
</div>
<section class="bloque-op" id="opiniones">
<h2 class="tit-bloque">Opiniones <span data-n="opiniones">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="¿Qué opinás de esta escala?" required></textarea><button class="btn">Publicar opinión</button></form>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más opiniones</button>
</section>
<section class="bloque-aplica" id="aplica">
<h2 class="tit-bloque">¿Cómo se liquida? <span data-n="pasos">0</span></h2>
<p class="ayuda">Mostrá cómo se liquida este convenio, paso a paso y explicando el porqué. Los más votados quedan arriba.</p>
<div id="lista-pasos" class="lista">{pasos_estaticos(aportes or [])}</div>
<button class="btn ancho" data-nuevo-paso>Subir mi explicativo</button>
</section>
</article>{lateral(notas)}</div>"""
    seo_t = f"Escala {c['nombre']} {periodo} ({c['cct']}): básicos, NR y cómo liquidar".replace("  ", " ")
    desc = f"Escala salarial vigente de {c['nombre']} ({c['cct']}): valores por categoría, sumas no remunerativas, aportes y cómo se liquida."
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": titulo_vis[:110], "description": desc,
          "dateModified": str(c.get("actualizado") or datetime.date.today().isoformat()), "inLanguage": "es-AR",
          "author": {"@type": "Organization", "name": "Redacción Ramacontable"}, "mainEntityOfPage": f"{sitio_url()}escala-{c['slug']}.html"}
    head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>'
    if c.get("preguntas"):
        head += '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in c["preguntas"]]}, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    return pagina(seo_t + " | Ramacontable", contenido, "sueldos", desc, f"escala-{c['slug']}.html", head)


def pagina_convenios(convenios, notas):
    items = "".join(
        f'<a class="tarjeta conv" href="escala-{c["slug"]}.html"><div class="tx"><p class="ante">{e(c["cct"])}</p><h2>{e(c["nombre"])}</h2>'
        f'<p class="meta">{e((c.get("escala") or {}).get("periodo") or "Escala pendiente de carga")}</p></div></a>' for c in convenios)
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Convenios y escalas salariales</h1><p class="ayuda">Escalas vigentes, novedades de cada acuerdo, tratamiento de las sumas no remunerativas y cómo se liquida cada convenio.</p><div class="tarjetas">{items}</div></section>{lateral(notas)}</div>'
    return pagina("Escalas salariales por convenio 2026: Comercio, UOCRA, UOM, Sanidad y más | Ramacontable", cuerpo, "sueldos",
                  "Escalas salariales vigentes por convenio colectivo, con novedades, sumas no remunerativas y cómo liquidar.", "convenios.html")


def tira_guias(guias, seccion):
    lista = [g for g in guias if g["seccion"] == seccion]
    if not lista:
        return ""
    return (f'<div class="conv-chips guias-chips"><b>{e(RAMAS_GUIAS[seccion])}:</b> ' + " ".join(
        f'<a href="nota-{g["slug"]}.html">{e(g["titulo"].split(":")[0])}</a>' for g in lista[:12]) + ' <a href="guias.html">Ver todas →</a></div>')


def pagina_guias(guias, notas, catalogo):
    hechas = {g["slug"] for g in guias}
    bloques = ""
    for k, titulo in RAMAS_GUIAS.items():
        lista = sorted([g for g in guias if g["seccion"] == k], key=lambda g: g["titulo"])
        prox = [c for c in catalogo if c["seccion"] == k and "guia-" + c["slug"] not in hechas]
        items = "".join(f'<li><a href="nota-{g["slug"]}.html"><b>{e(g["titulo"])}</b><span>{e(g.get("encorto", "")[:140])}</span></a></li>' for g in lista)
        items += "".join(f'<li class="prox"><b>{e(c["titulo"])}</b><span>Próximamente</span></li>' for c in prox)
        bloques += f'<section class="rama-guias" id="{k}"><h2>{e(titulo)}</h2><ul class="lista-guias">{items}</ul></section>'
    otras = '<p class="ayuda">¿Buscás novedades de la profesión? <a href="profesion.html">Ver notas de Profesión →</a></p>'
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Guías prácticas</h1><p class="ayuda">Guías completas de sueldos, impuestos y temas contables, basadas en la norma oficial y actualizadas cuando cambia algo. Debajo de cada una, la comunidad suma su explicación paso a paso.</p>{bloques}{otras}</section>{lateral(notas)}</div>'
    return pagina("Guías prácticas de sueldos, impuestos y contabilidad | Ramacontable", cuerpo, "guias",
                  "Guías prácticas para contadores y liquidadores: vacaciones, liquidación final, Ganancias, IVA, Monotributo, Ingresos Brutos y más.", "guias.html")


def html_admin(h):
    """HTML que escribió el administrador al editar: se quitan scripts y atributos peligrosos."""
    h = re.sub(r"(?is)<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1\s*>", "", h or "")
    h = re.sub(r"(?is)</?(script|style|iframe|object|embed|form|link|meta|base)\b[^>]*>", "", h)
    h = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h)
    return re.sub(r"(?i)javascript:", "", h)


ICONOS = {
    "Instagram": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>',
    "YouTube": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="M10 9l5 3-5 3z" fill="currentColor"/></svg>',
    "TikTok": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v11a4 4 0 1 1-4-4"/><path d="M14 3c.5 3 2.5 5 5 5"/></svg>',
}


def pagina(titulo, cuerpo, actual="", descripcion="", ruta="", extra_head=""):
    menu = "".join(
        f'<a href="{k}.html"{" aria-current=page" if k == actual else ""}>{v}</a>'
        for k, v in list(MENU.items()))
    redes = "".join(
        f'<a href="{u}" target="_blank" rel="noopener" aria-label="{n}">{ICONOS[n]}</a>'
        for n, u in REDES.items())
    anio = datetime.date.today().year
    return f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descripcion or 'Novedades contables, impositivas y laborales explicadas claro, y una comunidad que muestra cómo se aplican.')}">
<link rel="canonical" href="{sitio_url()}{ruta}">
<meta property="og:site_name" content="Ramacontable"><meta property="og:locale" content="es_AR">
<meta property="og:title" content="{e(titulo)}"><meta property="og:description" content="{e(descripcion or 'Novedades de la profesión contable')}">
<meta property="og:url" content="{sitio_url()}{ruta}"><meta property="og:image" content="{sitio_url()}compartir.png">
<meta name="twitter:card" content="summary_large_image">
{extra_head}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=swap">
<link rel="stylesheet" href="estilos.css?v={VERSION}">
<link rel="icon" href="logo.svg" type="image/svg+xml">
</head><body>
<header class="cab"><div class="wrap fila">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<nav class="menu">{menu}<a class="chico" href="convenios.html">Escalas</a><a class="chico2" href="calculadoras.html">Calculadoras</a><a class="chico2" href="herramientas.html">Vencimientos</a><a class="chico2" href="feriados.html">Feriados</a></nav>
<div id="sesion" class="sesion"><button class="btn" data-ingresar>Ingresar</button></div>
</div></header>
<main class="wrap">{cuerpo}</main>
<footer class="pie"><div class="wrap">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<p>Novedades de la profesión contable explicadas claro.</p>
<div class="redes">{redes}</div>
<p><a href="mailto:{MAIL}">{MAIL}</a></p>
<p class="legal">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. · <a href="terminos.html">Términos y privacidad</a> · © {anio} Ramacontable</p>
</div></footer>
<div id="modal" class="modal" hidden></div>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"></script>
<script src="vendor/purify.min.js"></script>
<script src="vendor/jszip.min.js"></script>
<script src="config.js"></script>
<script src="editor.js?v={VERSION}"></script>
<script src="app.js?v={VERSION}"></script>
</body></html>"""


def tarjeta(n, grande=False):
    clase = "tarjeta grande" if grande else "tarjeta"
    pastilla = f'<span class="pastilla">{e(n["dato"])}</span>' if n.get("dato") else ""
    return f"""<a class="{clase}" href="nota-{n['slug']}.html"><div class="tx">
<p class="ante">{e(n['antetitulo'])}</p><h2>{e(n['titulo'])}</h2>
{f"<p class='resumen'>{e(n['encorto'])}</p>" if grande else ""}
<p class="meta">{pastilla}{fecha_larga(n['fecha'])} · <span data-contador="{n['slug']}"></span></p></div></a>"""


def lateral(notas):
    esperando = "".join(
        f'<li><a href="nota-{n["slug"]}.html#aplica">{e(n["titulo"])}</a><span>Sé el primero en explicarlo</span></li>'
        for n in notas[:4])
    return f"""<aside class="lateral">
<section class="caja"><h3>Notas esperando su paso a paso</h3><ul class="esperando" id="esperando">{esperando}</ul></section>
<section class="caja" id="destacados" hidden><h3>Destacados de la comunidad</h3><ol id="ranking"></ol></section>
<a class="caja caja-calc" href="aguinaldo.html"><b>Calculadora de aguinaldo</b><span>Diciembre 2026 · paso a paso, con descuentos y neto</span></a>
<a class="caja caja-calc" href="sueldo-comercio.html"><b>Calculadora de sueldo de Comercio</b><span>Con escala vigente, antigüedad, presentismo y neto</span></a>
<section class="caja"><h3>Vencimientos que se vienen</h3><ul class="venc">
<li><span>DDJJ Ganancias 2025 (personas humanas)</span><b>16/11</b></li>
<li><span>Adhesión a planes de pago MiPyME y salud</span><b>30/12</b></li>
</ul><a class="mas" href="herramientas.html">Ver todos</a></section>
</aside>"""


def bloque(b):
    if "h" in b:
        return f"<h2>{e(b['h'])}</h2>"
    if "p" in b:
        return f"<p>{e(b['p'])}</p>"
    if "tabla" in b:
        filas = b["tabla"]
        cab = "".join(f"<th>{e(c)}</th>" for c in filas[0])
        resto = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in f) + "</tr>" for f in filas[1:])
        return f'<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{resto}</tbody></table></div>'
    if "html" in b:
        return html_admin(b["html"])
    return ""


def preguntas_html(n):
    qs = n.get("preguntas") or []
    if not qs:
        return ""
    items = "".join(f"<details><summary>{e(q['p'])}</summary><p>{e(q['r'])}</p></details>" for q in qs)
    return f'<section class="faq"><h2>Preguntas frecuentes</h2>{items}</section>'


def relacionadas(n, notas):
    otras = [x for x in notas if x["slug"] != n["slug"] and x["seccion"] == n["seccion"] and es_guia(x) == es_guia(n)][:4]
    if not otras:
        return ""
    return '<section class="relacionadas"><h2>' + (e(RAMAS_GUIAS.get(n["seccion"], "Otras guías")) if es_guia(n) else 'Más sobre ' + e(SECCIONES[n["seccion"]])) + "</h2><ul>" + "".join(
        f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in otras) + "</ul></section>"


def sitemaps(notas, convenios=()):
    base = sitio_url()
    hoy = datetime.date.today().isoformat()
    urls = [f"<url><loc>{base}</loc><lastmod>{hoy}</lastmod></url>"] + [
        f"<url><loc>{base}{k}.html</loc><lastmod>{hoy}</lastmod></url>" for k in list(SECCIONES) + ["aguinaldo", "herramientas", "convenios", "guias", "calculadoras", "feriados", "sueldo-comercio", "sueldo-casas-particulares"]] + [
        f"<url><loc>{base}escala-{c['slug']}.html</loc><lastmod>{str(c.get('actualizado') or hoy)[:10]}</lastmod></url>" for c in convenios] + [
        f"<url><loc>{base}nota-{n['slug']}.html</loc><lastmod>{str(n.get('actualizado') or n['fecha'])[:10]}</lastmod></url>" for n in notas]
    mapa = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    limite = datetime.date.today() - datetime.timedelta(days=2)
    recientes = [n for n in notas if str(n["fecha"])[:10] >= limite.isoformat() and not es_guia(n)]
    noticias = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + "".join(
        f"<url><loc>{base}nota-{n['slug']}.html</loc><news:news><news:publication><news:name>Ramacontable</news:name>"
        f"<news:language>es</news:language></news:publication><news:publication_date>{str(n['fecha'])[:10]}</news:publication_date>"
        f"<news:title>{e(n['titulo'])}</news:title></news:news></url>" for n in recientes) + "</urlset>")
    robots = f"User-agent: *\nAllow: /\nDisallow: /admin.html\nSitemap: {base}sitemap.xml\nSitemap: {base}sitemap-noticias.xml\n"
    return mapa, noticias, robots


def pagina_nota(n, notas, aportes=None):
    verif = ("Elaborada con fuentes oficiales." if n.get("verificada")
             else "Pendiente de verificación con fuente oficial.")
    cuerpo = "".join(bloque(b) for b in n["cuerpo"])
    sec = SECCIONES[n["seccion"]]
    previa = ""
    if n.get("actualiza"):
        previa = f'<p class="actualiza">Esta nota actualiza a: <a href="nota-{e(n["actualiza"])}.html">la nota anterior sobre el tema</a></p>'
    contenido = f"""<div class="grilla"><article class="nota" data-nota="{n['slug']}" data-actualizado="{e(str(n.get('actualizado') or ''))}">
<div class="nota-contenido">
<p class="miga">{f'<a href="guias.html">Guías</a> / <a href="guias.html#{n["seccion"]}">{RAMAS_GUIAS.get(n["seccion"], sec)}</a>' if es_guia(n) else f'<a href="{n["seccion"]}.html">{sec}</a>'}</p>
<p class="ante">{e(n['antetitulo'])}</p>
<h1>{e(n['titulo'])}</h1>
<p class="firma">Redacción Ramacontable · {('Guía actualizada al ' + fecha_larga(str(n.get('actualizado') or n['fecha'])[:10])) if es_guia(n) else fecha_larga(n['fecha'])}</p>
{previa}
<div class="encorto"><b>En corto</b><p>{e(n['encorto'])}</p></div>
{cuerpo}
{preguntas_html(n)}
<p class="fuente"><b>Fuente:</b> {e(n['fuente'])}</p>
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. {verif}</p>
</div>

{relacionadas(n, notas)}
<section class="bloque-op" id="opiniones">
<h2 class="tit-bloque">Opiniones <span data-n="opiniones">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="{'¿Algo para sumar o corregir en esta guía?' if es_guia(n) else '¿Qué opinás de esta novedad?'}" required></textarea><button class="btn">Publicar opinión</button></form>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más opiniones</button>
</section>
<section class="bloque-aplica" id="aplica">
<h2 class="tit-bloque">¿Cómo se aplica? <span data-n="pasos">0</span></h2>
<p class="ayuda">Mostrá cómo se liquida o se aplica esta novedad, paso a paso y explicando el porqué. Los más votados quedan arriba.</p>
<div id="lista-pasos" class="lista">{pasos_estaticos(aportes or [])}</div>
<button class="btn ancho" data-nuevo-paso>Subir mi explicativo</button>
</section>
</article>{lateral(notas)}</div>"""
    url = f"{sitio_url()}nota-{n['slug']}.html"
    ld = [{"@context": "https://schema.org", "@type": "Article" if es_guia(n) else "NewsArticle", "headline": n["titulo"][:110],
           "description": n.get("descripcion_seo") or n["encorto"], "datePublished": str(n["fecha"]),
           "dateModified": str(n.get("actualizado") or n["fecha"]), "inLanguage": "es-AR",
           "mainEntityOfPage": url, "articleSection": SECCIONES[n["seccion"]],
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "logo.svg"}}}]
    if n.get("preguntas"):
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in n["preguntas"]]})
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    head += f'<meta property="og:type" content="article"><meta property="article:published_time" content="{e(str(n["fecha"]))}">'
    return pagina(n.get("seo_titulo") or f"{n['titulo']} | Ramacontable", contenido, n["seccion"],
                  n.get("descripcion_seo") or n["encorto"], f"nota-{n['slug']}.html", head)


def portada(notas, titulo_pag="Ramacontable | Comunidad contable", actual="", encabezado="", extra=""):
    if not notas:
        lista = '<p class="vacio">Todavía no hay notas en esta sección.</p>'
    else:
        lista = tarjeta(notas[0], grande=True) + '<div class="tarjetas">' + "".join(tarjeta(n) for n in notas[1:]) + "</div>"
    cab = f'<h1 class="titsec">{e(encabezado)}</h1>' if encabezado else ""
    return pagina(titulo_pag, f'<div class="grilla"><section>{cab}{extra}{lista}</section>{lateral(notas)}</div>', actual, "", f"{actual}.html" if actual else "")


def main():
    if os.path.exists(SALIDA):
        shutil.rmtree(SALIDA)
    shutil.copytree(os.path.join(RAIZ, "web"), SALIDA)
    notas = cargar_notas()
    with open(os.path.join(SALIDA, "config.js"), "w", encoding="utf-8") as f:
        f.write("window.RC_CONFIG=" + json.dumps({
            "url": os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
            "key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            "build": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }) + ";")
    escribir = lambda nombre, txt: open(os.path.join(SALIDA, nombre), "w", encoding="utf-8").write(txt)
    convenios = cargar_convenios()
    todas = notas
    guias = [n for n in todas if es_guia(n)]
    notas = [n for n in todas if not es_guia(n)]
    try:
        catalogo = json.load(open(os.path.join(RAIZ, "guias", "catalogo.json"), encoding="utf-8"))
    except Exception:
        catalogo = []
    escribir("index.html", portada(notas))
    escribir("guias.html", pagina_guias(guias, notas, catalogo))
    for k, v in SECCIONES.items():
        extra = ""
        if k == "sueldos":
            extra = ('<div class="conv-chips"><b>Escalas por convenio:</b> ' + " ".join(
                f'<a href="escala-{c["slug"]}.html">{e(c["nombre"])}</a>' for c in convenios) + ' <a href="convenios.html">Ver todos →</a></div>')
        if k in RAMAS_GUIAS:
            extra += tira_guias(guias, k)
        escribir(f"{k}.html", portada([n for n in notas if n["seccion"] == k], f"{v} | Ramacontable", k, v, extra))
    aportes = cargar_aportes()
    for n in todas:
        escribir(f"nota-{n['slug']}.html", pagina_nota(n, guias if es_guia(n) else notas, aportes.get(n['slug'])))
    with open(os.path.join(RAIZ, "paginas", "herramientas.html"), encoding="utf-8") as f:
        escribir("herramientas.html", pagina("Vencimientos | Ramacontable", f.read(), "", "Vencimientos impositivos y previsionales que se vienen.", "herramientas.html"))
    with open(os.path.join(RAIZ, "paginas", "terminos.html"), encoding="utf-8") as f:
        escribir("terminos.html", pagina("Términos y privacidad | Ramacontable", f.read()))
    with open(os.path.join(RAIZ, "paginas", "aguinaldo.html"), encoding="utf-8") as f:
        escribir("aguinaldo.html", pagina("Calculadora de aguinaldo diciembre 2026 (SAC): cálculo paso a paso | Ramacontable", f.read(), "",
                 "Calculá el aguinaldo de diciembre 2026: mensualizados y jornalizados, proporcional por días, descuentos y neto, con el cálculo paso a paso.",
                 "aguinaldo.html"))
    with open(os.path.join(RAIZ, "paginas", "nota-dinamica.html"), encoding="utf-8") as f:
        escribir("nota.html", pagina("Nota | Ramacontable", f.read()))
    with open(os.path.join(RAIZ, "paginas", "admin.html"), encoding="utf-8") as f:
        escribir("admin.html", pagina("Administración | Ramacontable", f.read()))
    escribir("convenios.html", pagina_convenios(convenios, notas))
    por_slug = {c["slug"]: c for c in convenios}
    def calc_conv(archivo, salida_html, slug, titulo, desc):
        c = por_slug.get(slug) or {}
        datos = dict(c.get("escala") or {}, slug=slug)
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            cuerpo = f.read().replace('<script src="sueldo.js', '<script>window.RC_ESCALA=' + json.dumps(datos, ensure_ascii=False).replace("</", "<\\/") + ';</script><script src="sueldo.js')
        escribir(salida_html, pagina(titulo, cuerpo, "", desc, salida_html))
    calc_conv("sueldo-comercio.html", "sueldo-comercio.html", "comercio", "Calculadora de sueldo Empleados de Comercio 2026: neto con antigüedad y presentismo | Ramacontable",
              "Calculá el sueldo de comercio con la escala vigente: básico por categoría, antigüedad, presentismo, sumas no remunerativas, descuentos y neto.")
    calc_conv("sueldo-casas.html", "sueldo-casas-particulares.html", "casas-particulares", "Calculadora de sueldo de empleadas domésticas 2026: por hora y mensual | Ramacontable",
              "Calculá el sueldo de casas particulares por categoría, con o sin retiro, mensual o por hora, con antigüedad y zona desfavorable.")
    for archivo, titulo, desc in [("calculadoras.html", "Calculadoras de sueldos y aguinaldo | Ramacontable", "Calculadoras gratuitas para liquidar sueldos: comercio, casas particulares y aguinaldo, con escalas vigentes."),
                                  ("feriados.html", "Feriados 2026 Argentina: calendario completo y cómo se pagan | Ramacontable", "Calendario de feriados 2026 en Argentina: inamovibles, trasladables y días no laborables, y cómo se liquida trabajar un feriado.")]:
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            escribir(archivo, pagina(titulo, f.read(), "", desc, archivo))
    for c in convenios:
        escribir(f"escala-{c['slug']}.html", pagina_convenio(c, notas, aportes.get("convenio-" + c["slug"])))
    mapa, noticias, robots = sitemaps(todas, convenios)
    escribir("sitemap.xml", mapa)
    escribir("sitemap-noticias.xml", noticias)
    escribir("robots.txt", robots)
    escribir(".nojekyll", "")
    print(f"Listo: {len(notas)} notas en {SALIDA}")


if __name__ == "__main__":
    main()
