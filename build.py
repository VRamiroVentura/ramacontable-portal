"""Arma la web estática del portal Ramacontable.

Lee las notas de la carpeta notas/ (un .json por nota) y genera en sitio/:
portada, una página por sección y una página por nota.
Las claves públicas de Supabase se toman de las variables de entorno
SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (en GitHub vienen de los Secrets).
"""
import unicodedata
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
MENU = {"sueldos": "Sueldos", "impuestos": "Impuestos", "guias": "Guías", "datos-al-dia": "Datos del día"}
RAMAS_GUIAS = {"sueldos": "Guías de sueldos", "impuestos": "Guías de impuestos", "profesion": "Guías contables y de la profesión"}
GRUPOS_GUIAS = {"sueldos": "Guías de sueldos", "impuestos": "Guías de impuestos", "contables": "Guías contables",
                "tramites": "Sociedades y trámites", "otras": "Otras guías"}
IMPUESTOS = [
    ("ganancias", "Ganancias", ["ganancias", "siradig", "cuarta categoria"], ["ganancias-cuarta-categoria", "siradig", "ganancias-personas-humanas", "ganancias-sociedades"]),
    ("iva", "IVA", ["iva", "valor agregado"], ["iva"]),
    ("monotributo", "Monotributo", ["monotribut", "regimen simplificado"], ["monotributo"]),
    ("autonomos", "Autónomos", ["autonomo"], ["autonomos"]),
    ("bienes-personales", "Bienes Personales", ["bienes personales"], ["bienes-personales"]),
    ("ingresos-brutos", "Ingresos Brutos", ["ingresos brutos", "arba", "agip", "convenio multilateral"], ["ingresos-brutos-arba", "convenio-multilateral"]),
    ("retenciones", "Retenciones y percepciones", ["retencion", "percepcion"], ["retenciones-percepciones"]),
    ("planes-de-pago", "Planes de pago y moratorias", ["plan de pago", "planes de pago", "moratoria", "facilidades de pago"], ["planes-de-pago-arca"]),
]
_N = lambda t: "".join(ch for ch in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(ch) != "Mn")
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


VENC = []
PORTADAS_OK = set()  # notas que ya tienen su imagen para compartir  # filas de la tabla vencimientos (la arma la fábrica a diario)


def cargar_vencimientos():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return []
    try:
        req = urllib.request.Request(url + "/rest/v1/vencimientos?select=*&order=mes.asc", headers={"apikey": key, "Authorization": "Bearer " + key})
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as ex:
        print("Aviso: no se pudieron leer los vencimientos:", ex)
        return []


def proximos_vencimientos(n=None):
    hoy = datetime.date.today().isoformat()
    todos = [x for fila in VENC for x in (fila.get("items") or []) if x.get("fecha", "") >= hoy]
    todos.sort(key=lambda x: (x["fecha"], x.get("concepto", "")))
    return todos[:n] if n else todos


def fecha_corta(iso):
    return f"{iso[8:10]}/{iso[5:7]}"


# Series oficiales del BCRA (API pública de estadísticas, v4.0). Se bajan en cada publicación de la web.
SERIES_BCRA = {
    "cer": (30, "CER (Coeficiente de Estabilización de Referencia)", "indice"),
    "uva": (31, "UVA (Unidad de Valor Adquisitivo)", "indice"),
    "icl": (40, "ICL (Índice para Contratos de Locación)", "indice"),
    "dolar_minorista": (4, "Dólar oficial minorista (promedio vendedor)", "indice"),
    "dolar_mayorista": (5, "Dólar mayorista de referencia (Com. A 3500)", "indice"),
    "ipc": (27, "Inflación mensual (IPC)", "mensual"),
    "justicia": (43, "Tasa pasiva uso de justicia (Com. P 14.290)", "acumulada"),
    "badlar": (7, "Tasa BADLAR bancos privados", "tna"),
    "tamar": (44, "Tasa TAMAR bancos privados", "tna"),
    "plazo_fijo": (12, "Tasa de plazo fijo a 30 días", "tna"),
    "personales": (14, "Tasa de préstamos personales", "tna"),
}


def bajar_series(destino):
    """Escribe sitio/datos/serie-<clave>.json con {f: fechas, v: valores}. Si el BCRA no responde, esa serie queda sin archivo."""
    import ssl
    os.makedirs(destino, exist_ok=True)
    resumen = {}
    desde = "2016-01-01"
    for clave, (idv, nombre, tipo) in SERIES_BCRA.items():
        puntos = {}
        try:
            offset = 0
            while True:
                url = f"https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{idv}?desde={desde}&limit=3000&offset={offset}"
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ramacontable-build"})
                try:
                    datos = json.load(urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()))
                except ssl.SSLError:
                    # si el sistema no reconoce el certificado del BCRA, se prueba con la lista de certificados de certifi
                    import certifi
                    datos = json.load(urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context(cafile=certifi.where())))
                det = (datos.get("results") or [{}])[0].get("detalle") or []
                for d in det:
                    puntos[d["fecha"][:10]] = d["valor"]
                if len(det) < 3000:
                    break
                offset += 3000
        except Exception as ex:
            print(f"Aviso: no se pudo bajar la serie {clave} del BCRA:", ex)
        if not puntos:
            continue
        fechas = sorted(puntos)
        json.dump({"nombre": nombre, "tipo": tipo, "f": fechas, "v": [puntos[x] for x in fechas]},
                  open(os.path.join(destino, f"serie-{clave}.json"), "w", encoding="utf-8"), separators=(",", ":"))
        resumen[clave] = {"nombre": nombre, "tipo": tipo, "desde": fechas[0], "hasta": fechas[-1], "ultimo": puntos[fechas[-1]]}
    json.dump(resumen, open(os.path.join(destino, "series.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return resumen


def escribir_feriados(destino):
    """Lista de feriados y días no laborables (página de feriados + los que confirmó la fábrica) para contar días hábiles."""
    os.makedirs(destino, exist_ok=True)
    fechas = set(re.findall(r'data-f="(\d{4}-\d{2}-\d{2})"', open(os.path.join(RAIZ, "paginas", "feriados.html"), encoding="utf-8").read()))
    for fila in VENC:
        for x in fila.get("feriados") or []:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", str(x.get("fecha", ""))):
                fechas.add(x["fecha"])
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        for x in json.load(open(ruta, encoding="utf-8")).get("feriados", []):
            fechas.add(x["fecha"])
    anios = sorted({f[:4] for f in fechas})
    json.dump({"fechas": sorted(fechas), "anios": anios}, open(os.path.join(destino, "feriados.json"), "w", encoding="utf-8"))


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
                loc = locales.get(c["slug"]) or {}
                if not c.get("escala") and loc.get("escala"):  # escala cargada a mano en el repo mientras la fábrica no tenga una
                    c = dict(c, escala=loc["escala"], historial=c.get("historial") or loc.get("historial") or [],
                             actualizado=c.get("actualizado") or loc.get("actualizado"))
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
<p class="ayuda">Explicá cómo se liquida este convenio: un caso práctico, un recibo de ejemplo o una aclaración de la norma. Las más votadas quedan arriba.</p>
<div id="lista-pasos" class="lista">{pasos_estaticos(aportes or [])}</div>
<button class="btn ancho" data-nuevo-paso>Subir una explicación</button>
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
    contenido = contenido.replace("</article>", '<section class="relacionadas"><h2>Paritarias por mes</h2><ul>' + "".join(
        f'<li><a href="paritarias-{c["slug"]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html">Paritarias {e(c["nombre"])} {MESES[int(m[5:]) - 1]} {m[:4]}</a></li>' for m in _meses_paginas()) + "</ul></section></article>", 1)
    return pagina(seo_t + " | Ramacontable", contenido, "sueldos", desc, f"escala-{c['slug']}.html", head,
                  [("Sueldos", "sueldos.html"), ("Convenios", "convenios.html"), (c["nombre"], f"escala-{c['slug']}.html")])


def pagina_convenios(convenios, notas):
    items = "".join(
        f'<a class="tarjeta conv" href="escala-{c["slug"]}.html"><div class="tx"><p class="ante">{e(c["cct"])}</p><h2>{e(c["nombre"])}</h2>'
        f'<p class="meta">{e((c.get("escala") or {}).get("periodo") or "Escala pendiente de carga")}</p></div></a>' for c in convenios)
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Convenios y escalas salariales</h1><p class="ayuda">Escalas vigentes, novedades de cada acuerdo, tratamiento de las sumas no remunerativas y cómo se liquida cada convenio.</p><div class="tarjetas">{items}</div></section>{lateral(notas)}</div>'
    return pagina("Escalas salariales por convenio 2026: Comercio, UOCRA, UOM, Sanidad y más | Ramacontable", cuerpo, "sueldos",
                  "Escalas salariales vigentes por convenio colectivo, con novedades, sumas no remunerativas y cómo liquidar.", "convenios.html",
                  migas=[("Sueldos", "sueldos.html"), ("Convenios", "convenios.html")])


PRINCIPALES = ["comercio", "casas-particulares", "uocra", "uom", "sanidad"]


def tira_guias(guias, seccion):
    lista = [g for g in guias if g["seccion"] == seccion]
    if not lista:
        return ""
    return (f'<div class="conv-chips guias-chips"><b>{e(RAMAS_GUIAS[seccion])}:</b> ' + " ".join(
        f'<a href="nota-{g["slug"]}.html">{e(g["titulo"].split(":")[0])}</a>' for g in lista[:2]) + f' <a class="mas-chip" href="guias.html#{seccion}">Ver más guías ({len(lista)}) →</a></div>')


def pagina_guias(guias, notas, catalogo):
    hechas = {g["slug"] for g in guias}
    grupo_cat = {"guia-" + c["slug"]: c.get("grupo") or c["seccion"] for c in catalogo}
    grupo_de = lambda g: grupo_cat.get(g["slug"]) or (g["seccion"] if g["seccion"] in ("sueldos", "impuestos") else "otras")
    bloques = ""
    for k, titulo in GRUPOS_GUIAS.items():
        lista = sorted([g for g in guias if grupo_de(g) == k], key=lambda g: g["titulo"])
        prox = [c for c in catalogo if (c.get("grupo") or c["seccion"]) == k and "guia-" + c["slug"] not in hechas]
        if not lista and not prox:
            continue
        items = "".join(f'<li><a href="nota-{g["slug"]}.html"><b>{e(g["titulo"])}</b><span>{e(g.get("encorto", "")[:140])}</span></a></li>' for g in lista)
        items += "".join(f'<li class="prox"><b>{e(c["titulo"])}</b><span>Próximamente</span></li>' for c in prox)
        bloques += f'<section class="rama-guias" id="{k}"><h2>{e(titulo)}</h2><ul class="lista-guias">{items}</ul></section>'
    otras = '<p class="ayuda">¿Buscás novedades de la profesión? <a href="profesion.html">Ver notas de Profesión →</a></p>'
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Guías prácticas</h1><p class="ayuda">Guías completas de sueldos, impuestos y temas contables, basadas en la norma oficial y actualizadas cuando cambia algo. Debajo de cada una, la comunidad suma sus explicaciones y casos prácticos.</p>{bloques}{otras}</section>{lateral(notas)}</div>'
    return pagina("Guías prácticas de sueldos, impuestos y contabilidad | Ramacontable", cuerpo, "guias",
                  "Guías prácticas para contadores y liquidadores: vacaciones, liquidación final, Ganancias, IVA, Monotributo, Ingresos Brutos y más.", "guias.html", migas=[("Guías", "guias.html")])


def pagina_impuesto(imp, notas, guias, catalogo):
    slug, nombre, claves, guias_slugs = imp
    por_slug = {g["slug"]: g for g in guias}
    tit_cat = {c["slug"]: c["titulo"] for c in catalogo}
    items = ""
    for s in guias_slugs:
        g = por_slug.get("guia-" + s)
        items += (f'<li><a href="nota-{g["slug"]}.html"><b>{e(g["titulo"])}</b><span>{e(g.get("encorto", "")[:140])}</span></a></li>' if g
                  else f'<li class="prox"><b>{e(tit_cat.get(s, s))}</b><span>Próximamente</span></li>')
    relacionadas_i = [n for n in notas if any(c in _N(n["titulo"] + " " + n.get("antetitulo", "") + " " + (n.get("tema") or "")) for c in claves)]
    lista = ('<div class="tarjetas">' + "".join(tarjeta(n) for n in relacionadas_i[:20]) + "</div>") if relacionadas_i else '<p class="vacio">Todavía no hay novedades de este tema.</p>'
    cuerpo = (f'<div class="grilla"><section><p class="miga"><a href="impuestos.html">Impuestos</a></p><h1 class="titsec">{e(nombre)}</h1>'
              f'<section class="rama-guias"><h2>Guías de {e(nombre)}</h2><ul class="lista-guias">{items}</ul></section>'
              + ('<div class="conv-chips"><b>Por provincia:</b> ' + " ".join(f'<a href="{j["ruta"]}.html">{e(j["titulo_corto"])}</a>' for j in JURIS)
                 + ' <a class="mas-chip" href="provincias-y-municipios.html">Todas →</a></div>' if slug == "ingresos-brutos" and JURIS else "")
              +               f'<section class="rama-guias"><h2>Novedades de {e(nombre)}</h2>{lista}</section></section>{lateral(notas)}</div>')
    return pagina(f"{nombre}: novedades, vencimientos y guías prácticas | Ramacontable", cuerpo, "impuestos",
                  f"Todo sobre {nombre} para contadores: últimas novedades, normas y guías prácticas paso a paso.", f"impuesto-{slug}.html",
                  migas=[("Impuestos", "impuestos.html"), (nombre, f"impuesto-{slug}.html")])


def pagina_vencimientos(notas):
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    hoy = datetime.date.today().isoformat()
    bloques = ""
    for fila in VENC:
        items = [x for x in fila.get("items") or [] if x.get("fecha", "") >= hoy[:8] + "01"]
        if not items or fila["mes"] < hoy[:7]:
            continue
        anio, mes = fila["mes"].split("-")
        filas = "".join(
            f'<tr{" class=pasado" if x["fecha"] < hoy else ""}><td>{DIAS[datetime.date.fromisoformat(x["fecha"]).weekday()].capitalize()} {int(x["fecha"][8:])}</td>'
            f'<td>{e(x["concepto"])}</td><td>{e(x.get("detalle") or "Todas las terminaciones")}</td></tr>' for x in items)
        fer = "".join(f'<li><b>{fecha_corta(x["fecha"])}</b> {e(x["nombre"])} <small>({e(x.get("tipo",""))})</small></li>' for x in fila.get("feriados") or [])
        bloques += (f'<h2>Vencimientos de {MESES[int(mes)-1]} {anio}</h2><div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Obligación</th><th>Terminación de CUIT</th></tr></thead><tbody>{filas}</tbody></table></div>'
                    + (f'<p class="ayuda"><b>Feriados y días no laborables del mes:</b></p><ul class="historial">{fer}</ul>' if fer else ""))
    if not bloques:
        bloques = '<div class="vacio-caja"><b>Agenda en preparación</b>La agenda del mes se actualiza automáticamente todos los días.</div>'
    cuerpo = (f'<div class="grilla"><article class="nota calc"><p class="ante">Herramientas | ARCA</p><h1>Vencimientos impositivos y previsionales</h1>'
              f'<p class="firma">Redacción Ramacontable · Se actualiza todos los días</p>{bloques}'
              '<p class="aviso">Se publican solo las fechas confirmadas por al menos dos fuentes. Verificá siempre en la agenda oficial de ARCA según la terminación de tu CUIT.</p>'
              f'</article>{lateral(notas)}</div>')
    return pagina("Vencimientos ARCA: calendario del mes por terminación de CUIT | Ramacontable", cuerpo, "",
                  "Vencimientos impositivos y previsionales del mes por terminación de CUIT: IVA, F.931, Monotributo, Autónomos, Ganancias y más.", "herramientas.html")


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


def datos_sitio(migas=None):
    """Datos estructurados que lee Google: el sitio, la organización y la ruta de la página (migas de pan)."""
    base = sitio_url()
    grafo = [{"@type": "Organization", "@id": base + "#org", "name": "Ramacontable", "url": base,
              "logo": {"@type": "ImageObject", "url": base + "icono-512.png"}, "email": MAIL, "sameAs": list(REDES.values())},
             {"@type": "WebSite", "@id": base + "#web", "name": "Ramacontable", "url": base, "inLanguage": "es-AR",
              "publisher": {"@id": base + "#org"}}]
    if migas:
        grafo.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": base + u} for i, (n, u) in enumerate([("Inicio", "")] + list(migas))]})
    return '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": grafo}, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def herramienta_ld(nombre, descripcion, ruta):
    return '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "WebApplication", "name": nombre,
        "description": descripcion, "url": sitio_url() + ruta, "applicationCategory": "FinanceApplication", "operatingSystem": "Web",
        "inLanguage": "es-AR", "offers": {"@type": "Offer", "price": "0", "priceCurrency": "ARS"}}, ensure_ascii=False) + "</script>"


def pagina(titulo, cuerpo, actual="", descripcion="", ruta="", extra_head="", migas=None, imagen="compartir.png"):
    sub = {
        "sueldos": [("sueldos.html", "Novedades de sueldos"), ("convenios.html", "Escalas por convenio"), ("guias.html#sueldos", "Guías de sueldos"),
                    ("sueldo-comercio.html", "Calculadora de sueldo de Comercio"), ("datos-al-dia.html#sueldos", "Datos del día de sueldos"), ("vencimiento-931.html", "Vencimientos del F.931"), ("comparador-escalas.html", "Aumentos vs. inflación")],
        "impuestos": [("impuestos.html", "Novedades de impuestos")] + [(f"impuesto-{s}.html", n) for s, n, _, _ in IMPUESTOS] + [("provincias-y-municipios.html", "Provincias y municipios"), ("guias.html#impuestos", "Guías de impuestos"), ("datos-al-dia.html#impuestos", "Datos del día de impuestos")],
        "guias": [(f"guias.html#{k}", v) for k, v in GRUPOS_GUIAS.items()] + [("guias.html", "Todas las guías"), ("glosario.html", "Glosario")],
        "datos-al-dia": [x for gid, nombre, items in grupos_datos() for x in [("#g", nombre)] + [(f"{sl}.html", ti) for sl, ti, _ in items][:7]],
    }
    menu = "".join(
        f'<div class="dd{" dd-datos" if k == "datos-al-dia" else ""}"><a href="{k}.html"{" aria-current=page" if k == actual else ""}>{v}</a>'
        f'<div class="dd-m">' + "".join((f'<span class="dd-g">{e(t)}</span>' if u == "#g" else f'<a href="{u}"{" class=sep" if ("guias.html" in u or "datos-al-dia.html#" in u) and k in ("sueldos", "impuestos") else ""}>{e(t)}</a>') for u, t in sub.get(k, [])) + '</div></div>'
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
<meta property="og:url" content="{sitio_url()}{ruta}"><meta property="og:image" content="{sitio_url()}{imagen}">
<meta name="twitter:card" content="summary_large_image">
{extra_head}
{datos_sitio(migas)}
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional" media="print" onload="this.media='all'"><noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional"></noscript>
<link rel="stylesheet" href="estilos.css?v={VERSION}">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="icon" href="/icono-96.png" type="image/png" sizes="96x96"><link rel="icon" href="/icono-192.png" type="image/png" sizes="192x192"><link rel="icon" href="/logo.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/icono-180.png"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#13271F"><meta name="robots" content="max-image-preview:large, max-snippet:-1">
</head><body>
<header class="cab"><div class="wrap fila">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<nav class="menu">{menu}<a class="chico" href="calculadoras.html">Calculadoras</a><a class="chico2" href="herramientas.html">Vencimientos</a></nav>
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
<script>(function(){{var chico=function(){{return window.matchMedia('(max-width:760px)').matches||window.matchMedia('(hover:none)').matches}};
document.querySelectorAll('.cab .menu .dd > a').forEach(function(a){{a.addEventListener('click',function(ev){{if(!chico())return;var dd=a.parentNode,ab=dd.classList.contains('abierto');
document.querySelectorAll('.cab .menu .dd.abierto').forEach(function(x){{x.classList.remove('abierto')}});if(!ab){{ev.preventDefault();dd.classList.add('abierto');
var m=dd.querySelector('.dd-m');m.style.top=document.querySelector('.cab').getBoundingClientRect().bottom+'px'}}}})}});
document.addEventListener('click',function(ev){{if(!ev.target.closest('.cab .menu .dd'))document.querySelectorAll('.cab .menu .dd.abierto').forEach(function(x){{x.classList.remove('abierto')}})}});}})();</script>
<script defer src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"></script>
<script defer src="vendor/purify.min.js"></script>
<script defer src="config.js?v={VERSION}"></script>
<script defer src="editor.js?v={VERSION}"></script>
<script defer src="app.js?v={VERSION}"></script>
</body></html>"""


ICONOS_SVG = {
    "recibo": '<rect x="10" y="6" width="34" height="48" rx="3"/><path d="M17 18h14M17 26h20M17 34h12M17 44h20"/><circle cx="46" cy="14" r="9" fill="currentColor"/><path d="M46 9v10M49 11.5c-1-1.2-5-1.5-5 .8 0 2.6 6 1.4 6 4.2 0 2.3-4 2.2-5.8.8" stroke="var(--pf)" stroke-width="1.6"/>',
    "calendario": '<rect x="6" y="10" width="48" height="44" rx="4"/><path d="M6 22h48M18 4v12M42 4v12"/><path d="M14 32h6M27 32h6M40 32h6M14 42h6M27 42h6" stroke-width="3"/><rect x="39" y="39" width="8" height="6" fill="currentColor"/>',
    "grafico": '<path d="M6 6v48h48"/><path d="M14 46V34M24 46V26M34 46V32M44 46V16" stroke-width="5"/><path d="M12 28l12-10 10 6 14-14"/>',
    "documento": '<path d="M10 4h24l12 12v38H10z"/><path d="M34 4v12h12M17 26h20M17 34h20M17 42h12"/><circle cx="44" cy="46" r="9"/><path d="M40 46l3 3 6-6"/>',
}


def clase_portada(n):
    return "guia" if n.get("tipo") == "guia" else (n.get("seccion") if n.get("seccion") in ("sueldos", "impuestos") else "profesion")


def portada_html(n, tam="chica"):
    """Portada liviana hecha con HTML y un ícono vectorial: no agrega descargas a la página."""
    import portadas
    icono = ICONOS_SVG[portadas.tema_icono(n)]
    ante = n.get("antetitulo") or ("Guía práctica" if n.get("tipo") == "guia" else "")
    dato = (n.get("dato") or "").strip()
    clave = (n.get("clave") or "").strip()
    titulo = portadas._norm(n.get("titulo", ""))
    nuevo = lambda t: t and portadas._norm(t) not in titulo  # que no repita lo que ya dice el título
    if not clave:  # notas viejas sin frase clave: primera oración del "En corto", acortada
        frase = re.split(r"(?<=[.;:])\s", (n.get("encorto") or "").strip())[0].rstrip(".;:")
        if 25 <= len(frase) and portadas._norm(frase[:35]) not in titulo:
            clave = frase if len(frase) <= 90 else frase[:87].rsplit(" ", 1)[0] + "…"
    if nuevo(clave):
        principal = f'<b class="p-clave">{e(clave)}</b>'
    elif nuevo(dato):
        principal = f'<b class="p-dato">{e(dato)}</b>'
    else:
        # sin dato nuevo: sección y tema chiquitos, sin repetir el título en grande
        sec = "Guía práctica" if n.get("tipo") == "guia" else SECCIONES.get(n.get("seccion"), "")
        tema = (ante.split("|")[0] or "").strip()
        # el tema va grande (y la sección chiquita arriba); si no hay tema, la sección misma va grande
        grande_txt = tema or sec
        principal = (f'<span class="p-sec">{e(sec)}</span>' if tema and portadas._norm(tema) != portadas._norm(sec) else "") + f'<b class="p-tema">{e(grande_txt)}</b>'
    return (f'<div class="portada p-{clase_portada(n)} p-{tam}" aria-hidden="true"><div class="p-tx">{principal}</div>'
            f'<svg viewBox="0 0 60 60" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{icono}</svg></div>')


def tarjeta(n, grande=False):
    clase = "tarjeta grande" if grande else "tarjeta"
    pastilla = ""
    return f"""<a class="{clase}" href="nota-{n['slug']}.html">{portada_html(n, "grande" if grande else "chica")}<div class="tx">
<p class="ante">{e(n['antetitulo'])}</p><h2>{e(n['titulo'])}</h2>
{f"<p class='resumen'>{e(n['encorto'])}</p>" if grande else ""}
<p class="meta">{pastilla}{fecha_larga(n['fecha'])} · <span data-contador="{n['slug']}"></span></p></div></a>"""


def lateral(notas):
    nicho = [c for j in JURIS if not j.get("portada", True) for c in j.get("venc_claves") or [] if c != "convenio multilateral"]
    prox = [x for x in proximos_vencimientos() if not any(re.search(r"\b" + re.escape(_N(c)) + r"\b", _N(x.get("concepto", ""))) for c in nicho)][:5]
    caja_venc = ('<section class="caja"><h3>Vencimientos que se vienen</h3><ul class="venc">' + "".join(
        f'<li><span>{e(x["concepto"])}{(" · " + e(x["detalle"])) if x.get("detalle") else ""}</span><b>{fecha_corta(x["fecha"])}</b></li>' for x in prox)
        + '</ul><a class="mas" href="herramientas.html">Ver todos</a></section>') if prox else \
        '<section class="caja"><h3>Vencimientos</h3><p class="ayuda">Agenda del mes</p><a class="mas" href="herramientas.html">Ver vencimientos</a></section>'
    return _lateral(notas, caja_venc)


def _lateral(notas, caja_venc):
    datos = "".join(
        f'<li><a href="{t["slug"]}.html">{e(t["titulo"])}</a><b>{e((ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {}).get("valor") or "").split(" (")[0][:28])}</b></li>'
        for t in TEMAS_RESP[:6])
    return f"""<aside class="lateral">
<section class="caja"><h3>Datos del día</h3><ul class="datos-lat">{datos}</ul><a class="mas" href="datos-al-dia.html">Ver todos</a></section>
<a class="caja caja-calc" href="aguinaldo.html"><b>Calculadora de aguinaldo</b><span>Diciembre 2026 · paso a paso, con descuentos y neto</span></a>
<a class="caja caja-calc" href="sueldo-comercio.html"><b>Calculadora de sueldo de Comercio</b><span>Con escala vigente, antigüedad, presentismo y neto</span></a>
{caja_venc}
<section class="caja" id="destacados" hidden><h3>Destacados de la comunidad</h3><ol id="ranking"></ol></section>
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
    # lastmod solo donde la página cambia de verdad todos los días (datos, dólar, índices, portadas);
    # las calculadoras y páginas fijas van sin fecha, para que Google no aprenda a ignorar nuestras fechas
    diarias = list(SECCIONES) + ["datos-al-dia", "dolar-hoy", "herramientas"] + [t["slug"] for t in TEMAS_RESP] + [b[0] for b in BCRA_RESP] + \
        [x[0] for x in DOLARES] + [o[0] for o in OBLIGACIONES] + urls_mes() + QUE_CAMBIA_URLS
    fijas = ["aguinaldo", "convenios", "guias", "calculadoras", "feriados", "sueldo-comercio", "sueldo-casas-particulares", "actualizacion", "dias-habiles",
             "plazo-fijo", "prestamos", "vacaciones", "liquidacion-final", "horas-extras", "iva", "conversor-dolar", "monotributo-categoria", "intereses-arca",
             "actualizacion-alquiler", "embargo-sueldo", "cuando-cambia-cada-dato", "glosario", "comparador-escalas", "agenda-vencimientos",
             "retencion-ganancias"] + JURIS_URLS + PARITARIAS_URLS + FERIADOS_URLS + [f"impuesto-{i[0]}" for i in IMPUESTOS]
    urls = [f"<url><loc>{base}</loc><lastmod>{hoy}</lastmod></url>"] + [
        f"<url><loc>{base}{k}.html</loc><lastmod>{hoy}</lastmod></url>" for k in diarias if k not in PAGINAS_FINAS] + [
        f"<url><loc>{base}{k}.html</loc></url>" for k in fijas if k not in PAGINAS_FINAS] + [
        f"<url><loc>{base}escala-{c['slug']}.html</loc><lastmod>{str(c.get('actualizado') or hoy)[:10]}</lastmod></url>" for c in convenios] + [
        f"<url><loc>{base}nota-{n['slug']}.html</loc><lastmod>{hoy if (es_guia(n) and 'aguinaldo' in n['slug']) else str(n.get('actualizado') or n['fecha'])[:10]}</lastmod></url>" for n in notas]
    mapa = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    limite = datetime.date.today() - datetime.timedelta(days=2)
    recientes = [n for n in notas if str(n["fecha"])[:10] >= limite.isoformat() and not es_guia(n)]
    noticias = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + "".join(
        f"<url><loc>{base}nota-{n['slug']}.html</loc><news:news><news:publication><news:name>Ramacontable</news:name>"
        f"<news:language>es</news:language></news:publication><news:publication_date>{str(n['fecha'])[:10]}</news:publication_date>"
        f"<news:title>{e(n['titulo'])}</news:title></news:news></url>" for n in recientes) + "</urlset>")
    bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
            "Perplexity-User", "Google-Extended", "Bingbot", "Applebot-Extended", "CCBot", "meta-externalagent", "DuckAssistBot"]
    robots = "".join(f"User-agent: {b}\nAllow: /\nDisallow: /admin.html\n\n" for b in bots)
    robots += f"User-agent: *\nAllow: /\nDisallow: /admin.html\n\nSitemap: {base}sitemap.xml\nSitemap: {base}sitemap-noticias.xml\n"
    return mapa, noticias, robots


def llms_txt(notas, convenios):
    """Resumen del sitio para asistentes de IA (formato llms.txt)."""
    base = sitio_url()
    l = ["# Ramacontable", "",
         "> Portal argentino para contadores y liquidadores de sueldos: novedades de ARCA y laborales, escalas salariales "
         "por convenio, vencimientos, guías y calculadoras gratuitas. Cada nota cita la fuente oficial y la fecha.", "",
         "## Secciones", f"- [Sueldos]({base}sueldos.html): novedades laborales y de liquidación de sueldos",
         f"- [Impuestos]({base}impuestos.html): novedades de ARCA y rentas", f"- [Guías]({base}guias.html): guías actualizadas por tema",
         f"- [Vencimientos]({base}vencimientos.html): próximos vencimientos impositivos y previsionales",
         f"- [Feriados]({base}feriados.html): feriados del año y cómo se pagan",
         f"- [Datos del día]({base}datos-al-dia.html): datos vigentes revisados todos los días", "",
         "## Datos al día (revisados a diario contra fuentes oficiales)"]
    l += [f"- [{t['titulo']}]({base}{t['slug']}.html): {(((RESP.get(t['slug']) or {}).get('datos') or {}).get('respuesta') or t['pregunta'])[:200]}" for t in TEMAS_RESP]
    l += [f"- [{b[2]}]({base}{b[0]}.html): serie oficial del BCRA" for b in BCRA_RESP]
    l += [f"- [Dólar hoy]({base}dolar-hoy.html): oficial, mayorista, MEP, CCL, tarjeta, cripto y blue (informativo), cada hora"]
    l += [f"- [Vencimientos de {o[1]} por terminación de CUIT]({base}{o[0]}.html)" for o in OBLIGACIONES]
    l += ["", "## Provincias y municipios", f"- [Impuestos provinciales y municipales]({base}provincias-y-municipios.html): Ingresos Brutos y tasas por jurisdicción"]
    l += [f"- [{j['titulo']}]({base}{j['ruta']}.html)" for j in JURIS]
    l += [f"- [{t['titulo']}]({base}{t['ruta']}.html): {t['descripcion']}" for j in JURIS for t in (j.get("tablas") or []) + (j.get("paginas") or [])]
    l += ["", "## Escalas salariales por convenio"]
    l += [f"- [{c.get('nombre', c['slug'])}]({base}escala-{c['slug']}.html)" for c in convenios]
    l += ["", "## Calculadoras"] + [f"- [{t}]({base}{a}.html)" for a, t in [
        ("sueldo-comercio", "Sueldo de Comercio"), ("sueldo-casas-particulares", "Casas particulares"), ("aguinaldo", "Aguinaldo"),
        ("liquidacion-final", "Liquidación final e indemnización"), ("vacaciones", "Vacaciones"), ("horas-extras", "Horas extras"),
        ("actualizacion", "Actualización por CER, UVA, dólar, inflación y tasas"), ("dias-habiles", "Días hábiles"),
        ("plazo-fijo", "Plazo fijo"), ("prestamos", "Préstamos"), ("iva", "IVA"), ("conversor-dolar", "Conversor de dólar"),
        ("monotributo-categoria", "Categoría del Monotributo"), ("intereses-arca", "Intereses resarcitorios de ARCA"),
        ("actualizacion-alquiler", "Actualización de alquiler (ICL / IPC)"), ("embargo-sueldo", "Embargo de sueldo (Decreto 484/87)"),
        ("retencion-ganancias", "Retención de Ganancias sobre el sueldo"), ("agenda-vencimientos", "Agenda de vencimientos por CUIT"),
        ("comparador-escalas", "Aumentos por convenio vs. inflación"), ("glosario", "Glosario contable, impositivo y laboral")]]
    l += [f"- [Planilla de vacaciones para varios empleados (Excel)]({base}planillas/planilla-vacaciones.xlsx): días por antigüedad, art. 153, valor del día y total"]
    l += [f"- [Planilla de liquidación final e indemnización (Excel)]({base}planillas/planilla-liquidacion-final.xlsx): días trabajados, SAC, vacaciones no gozadas, art. 245, preaviso e integración"]
    l += [f"- [Planilla de aguinaldo para varios empleados (Excel)]({base}planillas/planilla-aguinaldo-varios-empleados.xlsx): mejor remuneración del semestre, proporcional por días, tope del SAC, descuentos y neto"]
    l += ["", "## Últimas notas"] + [f"- [{n['titulo']}]({base}nota-{n['slug']}.html): {(n.get('encorto') or '')[:200]}"
                                     for n in notas[:40]]
    return "\n".join(l) + "\n"


def urls_indexnow(notas, convenios, minutos=90):
    """Páginas nuevas o cambiadas en la última hora y media, para avisar a Bing/IndexNow."""
    base = sitio_url()
    lim = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutos)).isoformat()[:16]
    def nuevo(v):
        v = str(v or "")
        return len(v) > 10 and v.replace(" ", "T")[:16] >= lim
    u = [f"{base}nota-{n['slug']}.html" for n in notas if nuevo(n.get("actualizado")) or nuevo(n.get("fecha"))]
    u += [f"{base}escala-{c['slug']}.html" for c in convenios if nuevo(c.get("actualizado"))]
    u += [f"{base}{sl}.html" for sl, r in RESP.items() if nuevo(r.get("cambiado"))]
    return ([base] if u else []) + u


def bloque_aportes(n, aportes):
    """Guías: opiniones + explicaciones por separado. Novedades: un solo bloque de comentarios, con explicaciones opcionales."""
    if es_guia(n):
        return GUIA_APORTES.replace("@PASOS@", pasos_estaticos(aportes or []))
    return f'''<section class="bloque-op bloque-com" id="opiniones"><span id="aplica"></span>
<h2 class="tit-bloque">Comentarios <span data-n="total">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="Dejá tu comentario o explicación sobre «{e(n.get("titulo") or "este tema")}»" required></textarea>
<button class="btn">Publicar</button></form>
<button type="button" class="link-expl" data-nuevo-paso>¿Querés subir una explicación con tablas, imágenes o PDF? Hacelo acá</button>
<div id="lista-pasos" class="lista lista-expl">{pasos_estaticos(aportes or [])}</div>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más comentarios</button>
<span hidden data-n="pasos">0</span><span hidden data-n="opiniones">0</span>
</section>'''


GUIA_APORTES = """<section class="bloque-op" id="opiniones">
<h2 class="tit-bloque">Opiniones <span data-n="opiniones">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="¿Algo para sumar o corregir en esta guía?" required></textarea><button class="btn">Publicar opinión</button></form>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más opiniones</button>
</section>
<section class="bloque-aplica" id="aplica">
<h2 class="tit-bloque">¿Cómo se aplica? <span data-n="pasos">0</span></h2>
<p class="ayuda">Explicá cómo se aplica esta guía: un caso práctico, una liquidación de ejemplo o una aclaración de la norma. Las más votadas quedan arriba.</p>
<div id="lista-pasos" class="lista">@PASOS@</div>
<button class="btn ancho" data-nuevo-paso>Subir una explicación</button>
</section>
"""


# ---------- Datos al día (páginas respuesta) ----------
RESP = {}       # slug -> fila de Supabase (datos verificados por la fábrica)
TEMAS_RESP = []  # respuestas/temas.json
BCRA_RESP = [   # páginas que se arman solas con la serie oficial del BCRA
    ("valor-uva-hoy", "uva", "Valor de la UVA hoy", "¿Cuánto vale la UVA hoy?", "UVA", "sueldos"),
    ("cer-hoy", "cer", "Valor del CER hoy", "¿Cuánto vale el CER hoy?", "CER", "impuestos"),
    ("inflacion-mensual-ipc", "ipc", "Inflación mensual (IPC)", "¿Cuánto fue la última inflación mensual?", "inflación", "impuestos"),
    ("icl-alquileres-hoy", "icl", "Índice ICL para alquileres hoy", "¿Cuánto vale el ICL hoy?", "ICL", "impuestos"),
    ("tasa-badlar-hoy", "badlar", "Tasa BADLAR hoy", "¿Cuál es la tasa BADLAR hoy?", "BADLAR", "impuestos"),
    ("tasa-tamar-hoy", "tamar", "Tasa TAMAR hoy", "¿Cuál es la tasa TAMAR hoy?", "TAMAR", "impuestos"),
    ("tasa-plazo-fijo-hoy", "plazo_fijo", "Tasa de plazo fijo hoy", "¿Cuánto paga un plazo fijo hoy?", "tasa de plazo fijo", "impuestos"),
]
DOLARES = [  # cotizaciones de mercado (DolarAPI); historial de ArgentinaDatos
    ("dolar-oficial-hoy", "oficial", "Dólar oficial hoy (Banco Nación)", "dólar oficial"),
    ("dolar-mayorista-hoy", "mayorista", "Dólar mayorista hoy", "dólar mayorista"),
    ("dolar-mep-hoy", "bolsa", "Dólar MEP hoy", "dólar MEP"),
    ("dolar-ccl-hoy", "contadoconliqui", "Dólar contado con liquidación (CCL) hoy", "dólar CCL"),
    ("dolar-tarjeta-hoy", "tarjeta", "Dólar tarjeta hoy", "dólar tarjeta"),
    ("dolar-cripto-hoy", "cripto", "Dólar cripto hoy", "dólar cripto"),
    ("dolar-blue-hoy", "blue", "Dólar blue hoy", "dólar blue"),
]
DOLAR = {}


def cargar_respuestas():
    global RESP, TEMAS_RESP
    try:
        TEMAS_RESP = json.load(open(os.path.join(RAIZ, "respuestas", "temas.json"), encoding="utf-8"))
    except Exception:
        TEMAS_RESP = []
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if url and key:
        try:
            req = urllib.request.Request(url + "/rest/v1/respuestas?select=*", headers={"apikey": key, "Authorization": "Bearer " + key})
            RESP = {r["slug"]: r for r in json.load(urllib.request.urlopen(req, timeout=30))}
        except Exception as ex:
            print("Aviso: no se pudieron leer los datos al día:", ex)
    # datos iniciales verificados a mano: se muestran hasta que la fábrica cargue el suyo en Supabase
    for archivo in glob.glob(os.path.join(RAIZ, "respuestas", "inicial", "*.json")) + glob.glob(os.path.join(RAIZ, "respuestas", "prueba-*.json")):
        r = json.load(open(archivo, encoding="utf-8"))
        RESP.setdefault(r["slug"], r)


def _fecha_hora(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(datetime.timezone(datetime.timedelta(hours=-3)))
        return f"{d.day}/{d.month}/{d.year} a las {d.hour:02d}:{d.minute:02d}"
    except Exception:
        return fecha_larga(str(iso)[:10])


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _num(x):
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ultimo_serie(clave):
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", f"serie-{clave}.json"), encoding="utf-8"))
        return sr["f"][-1], sr["v"][-1]
    except Exception:
        return None, None


def _ipc_fechas():
    try:
        return json.load(open(os.path.join(RAIZ, "respuestas", "ipc.json"), encoding="utf-8")).get("fechas", [])
    except Exception:
        return []


def ajustar_tramo(d):
    """Si el dato trae los tramos mes a mes ya fijados (salario mínimo), se toma solo el del mes actual."""
    tr = ((d.get("estructurado") or {}).get("tramos") or [])
    mes = datetime.date.today().strftime("%Y-%m")
    vig = [x for x in tr if str(x.get("desde", "")) <= mes and x.get("mensual")]
    if not vig:
        return d
    x = max(vig, key=lambda z: z["desde"])
    d = dict(d, monto=x["mensual"], mes_vigente=mes,
             valor=f"$ {_num(x['mensual'])} por mes" + (f" ($ {_num(x['hora'])} la hora)" if x.get("hora") else ""))
    sig = [z for z in tr if str(z.get("desde", "")) > mes]
    if sig:
        z = min(sig, key=lambda q: q["desde"])
        d["proximo"] = f"$ {_num(z['mensual'])} desde {MESES[int(z['desde'][5:7]) - 1]} {z['desde'][:4]}"
    return d


def bloque_dato_hoy(t, d):
    """Lo que cambia de verdad todos los días: equivalencias con el dólar y la UVA de hoy, días que faltan y cálculo anticipado."""
    hoy = datetime.date.today()
    filas = []
    monto = d.get("monto")
    dol = ((DOLAR.get("actual") or {}).get("oficial") or {}).get("venta")
    if isinstance(monto, (int, float)) and monto > 0:
        if dol:
            filas.append(f"Equivale a <b>US$ {_num(monto / dol)}</b> al dólar oficial de hoy (Banco Nación, $ {_num(dol)}).")
        fu, uva = _ultimo_serie("uva")
        if uva:
            filas.append(f"Equivale a <b>{_num(monto / uva)} UVA</b> (UVA del {fecha_corta(fu)}: $ {_num(uva)}).")
    c = t.get("ciclo") or {}
    if c.get("tipo") == "movilidad":
        prox = [x for x in _ipc_fechas() if x >= hoy.isoformat()]
        if prox:
            dias = (datetime.date.fromisoformat(prox[0]) - hoy).days
            filas.append(f"Próximo dato de inflación del INDEC: <b>{fecha_corta(prox[0])}</b> ({'hoy' if dias == 0 else f'faltan {dias} días'}). ANSES confirma los nuevos montos en los días siguientes.")
        fi, ipc = _ultimo_serie("ipc")
        mv = d.get("mes_vigente")
        if ipc is not None and fi and mv and isinstance(monto, (int, float)):
            y, m = int(mv[:4]), int(mv[5:7])
            ant = (y, m - 1) if m > 1 else (y - 1, 12)
            if (int(fi[:4]), int(fi[5:7])) == ant:
                sig = (y, m + 1) if m < 12 else (y + 1, 1)
                filas.append(f"<b>Cálculo anticipado para {MESES[sig[1] - 1]} {sig[0]}: $ {_num(monto * (1 + ipc / 100))}</b> "
                             f"(+{_num(ipc)}%, la inflación de {MESES[ant[1] - 1]}), según la fórmula de movilidad mensual del Decreto 274/2024. "
                             "Es un cálculo propio: se confirma con la resolución de ANSES.")
    if t["slug"].startswith("monotributo") or "simplificado" in t["slug"]:
        v = [x for x in proximos_vencimientos() if "monotrib" in x.get("concepto", "").lower()][:2]
        for x in v:
            dias = (datetime.date.fromisoformat(x["fecha"][:10]) - hoy).days
            filas.append(f"{e(x['concepto'])}: <b>{fecha_corta(x['fecha'])}</b> ({'hoy' if dias == 0 else f'faltan {dias} días'}).")
    if not filas:
        return ""
    return (f'<section class="dato-hoy"><h2>El dato hoy, {hoy.day}/{hoy.month}/{hoy.year}</h2><ul>'
            + "".join(f"<li>{x}</li>" for x in filas) + "</ul></section>")


def mes_links(t):
    pm = next((p for p in PAGINAS_MES if p[1] == t["slug"]), None)
    if not pm:
        return ""
    return ('<section class="relacionadas"><h2>Por mes</h2><ul>' + "".join(
        f'<li><a href="{pm[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html">{e(pm[2].format(mes=MESES[int(m[5:]) - 1] + " " + m[:4]))}</a></li>' for m in _meses_paginas()) + "</ul></section>")


def pagina_respuesta(t, r, notas, aportes=None, extra=""):
    d = ajustar_tramo((r or {}).get("datos") or {})
    hoy = datetime.date.today()
    hoy_blq = bloque_dato_hoy(t, d) if d.get("valor") else ""
    mes = f"{MESES[hoy.month - 1]} {hoy.year}"
    titulo_h = f"{t['titulo']} ({mes})" if (" hoy" in t["titulo"] or t.get("seccion") == "provincias") else f"{t['titulo']} hoy ({mes})"
    claves = [c.lower() for c in t.get("claves", [])]
    rel = [n for n in notas if any(c in (n["titulo"] + " " + n.get("encorto", "")).lower() for c in claves)][:5]
    if d.get("valor"):
        caja = (f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><b class="resp-v">{e(d["valor"])}</b>'
                f'<p>{e(d.get("respuesta", ""))}</p>'
                + (f'<p class="resp-meta">Rige desde: <b>{e(d["vigencia"])}</b></p>' if d.get("vigencia") else "")
                + (f'<p class="resp-meta">Próximo cambio: <b>{e(d["proximo"])}</b></p>' if d.get("proximo") else "")
                + (f'<p class="resp-meta">Norma: {e(d["norma"])}</p>' if d.get("norma") else "") + "</div>")
        revisado = (f'<p class="resp-rev">✔ <b>Vigente hoy, {hoy.day}/{hoy.month}/{hoy.year}.</b> Última verificación con las fuentes: {_fecha_hora(r.get("revisado"))} ('
                    + ", ".join(e(f["nombre"]) for f in (r.get("fuentes") or [])) + ")."
                    + (f" Cuándo cambia: {e(t['cuando'])}." if t.get("cuando") else "") + "</p>")
    else:
        caja = f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><p>Estamos verificando el dato vigente con las fuentes oficiales. Se publica apenas lo confirmen al menos dos fuentes.</p></div>'
        revisado = ""
    cuerpo = "".join(f"<p>{e(x)}</p>" for x in d.get("explicacion") or [])
    if d.get("tabla"):
        cuerpo += bloque({"tabla": d["tabla"]})
    hist = r.get("historial") if r else []
    if hist and len(hist) > 1:
        cuerpo += "<h2>Cómo fue cambiando</h2><div class=\"tabla\"><table><thead><tr><th>Desde</th><th>Valor</th><th>Norma</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{fecha_corta(h['fecha'])}</td><td>{e(h['valor'])}</td><td>{e(h.get('norma') or '')}</td></tr>" for h in hist) + "</tbody></table></div>"
    faq = preguntas_html({"preguntas": d.get("preguntas") or []})
    fuentes_html = ("<p class=\"fuente\"><b>Fuentes:</b> " + " · ".join(
        f'<a href="{e(f["url"])}" rel="nofollow noopener" target="_blank">{e(f["nombre"])}</a>' for f in (r.get("fuentes") or [])) + "</p>") if r else ""
    rel = rel[:3]
    rel_html = ('<section class="relacionadas novedades-dato"><h2>Últimas novedades sobre el tema</h2><ul>' + "".join(
        f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in rel) + "</ul></section>") if rel else ""
    jur = next((j for j in JURIS if j["slug"] == t.get("jurisdiccion")), None)
    otros = "".join(f'<li><a href="{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in TEMAS_RESP
                    if x["slug"] != t["slug"] and (x.get("seccion") != "provincias" or x.get("jurisdiccion") == t.get("jurisdiccion")))
    if jur:
        otros = f'<li><a href="{jur["ruta"]}.html">Todo sobre {e(jur["nombre"])}: datos, vencimientos y novedades</a></li><li><a href="provincias-y-municipios.html">Otras provincias y municipios</a></li>' + otros
    miga = (f'<a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{jur["ruta"]}.html">{e(jur["nombre"])}</a>'
            if t.get("seccion") == "provincias" and jur else '<a href="datos-al-dia.html">Datos del día</a>')
    migas_r = ([("Provincias y municipios", "provincias-y-municipios.html"), (jur["titulo_corto"], jur["ruta"] + ".html")]
               if t.get("seccion") == "provincias" and jur else [("Datos del día", "datos-al-dia.html")]) + [(t["titulo"], t["slug"] + ".html")]
    falsa_nota = {"slug": t["slug"], "titulo": t["titulo"].lower()}
    contenido = f"""<div class="grilla"><article class="nota respuesta" data-nota="dato-{t['slug']}">
<div class="nota-contenido">
<p class="miga">{miga}</p>
<h1>{e(titulo_h)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat() if hoy_blq else str((r or {}).get('cambiado') or hoy.isoformat())[:10])}</p>
{caja}{revisado}{hoy_blq}{rel_html}{cuerpo}{extra}{faq}{fuentes_html}
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación.</p>
</div>
{mes_links(t)}
<section class="relacionadas"><h2>Otros datos del día</h2><ul>{otros}</ul></section>
{bloque_aportes(falsa_nota, aportes)}
</article>{lateral(notas)}</div>"""
    url = sitio_url() + t["slug"] + ".html"
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": titulo_h, "inLanguage": "es-AR",
           "description": d.get("respuesta") or t["pregunta"], "mainEntityOfPage": url,
           "datePublished": str((r or {}).get("cambiado") or hoy.isoformat())[:10], "dateModified": hoy.isoformat() if hoy_blq else str((r or {}).get("cambiado") or hoy.isoformat())[:10],
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "icono-512.png"}}}]
    qs = ([{"p": t["pregunta"], "r": d["respuesta"]}] if d.get("respuesta") else []) + list(d.get("preguntas") or [])
    if qs:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]})
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    desc = (d.get("respuesta") or t["pregunta"])[:300]
    return pagina(f"{titulo_h}: {d.get('valor') or 'dato vigente'} | Ramacontable", contenido, "impuestos" if t.get("seccion") == "provincias" else "datos-al-dia",
                  desc, t["slug"] + ".html", head, migas_r)


def pagina_bcra(slug, clave, titulo, pregunta, corto, seccion, notas):
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", f"serie-{clave}.json"), encoding="utf-8"))
    except Exception:
        return None
    f, v = sr["f"], sr["v"]
    ult, fecha = v[-1], f[-1]
    num = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if clave == "ipc":
        valor = f"{num(ult)}% ({MESES[int(fecha[5:7]) - 1]} {fecha[:4]})"
        filas = [[f"{MESES[int(a[5:7]) - 1]} {a[:4]}", num(b) + "%"] for a, b in list(zip(f, v))[-12:][::-1]]
        resp = f"La última inflación mensual publicada fue de {num(ult)}%, correspondiente a {MESES[int(fecha[5:7]) - 1]} de {fecha[:4]}, según la serie oficial del BCRA (dato INDEC)."
        cab = ["Mes", "Inflación mensual"]
    elif sr.get("tipo") == "tna" or clave in ("badlar", "tamar", "plazo_fijo"):
        valor = f"{num(ult)}% TNA"
        filas = [[fecha_corta(a), num(b) + "%"] for a, b in list(zip(f, v))[-15:][::-1]]
        resp = f"La tasa {corto} al {fecha_corta(fecha)} es {num(ult)}% nominal anual, según la serie oficial del Banco Central (BCRA)."
        cab = ["Fecha", "TNA"]
    else:
        valor = ("$ " if clave.startswith("dolar") else "") + num(ult)
        filas = [[fecha_corta(a), num(b)] for a, b in list(zip(f, v))[-15:][::-1]]
        resp = f"El valor de {corto} al {fecha_corta(fecha)} es {valor}, según la serie oficial del Banco Central (BCRA)."
        cab = ["Fecha", "Valor"]
    t = {"slug": slug, "titulo": titulo, "pregunta": pregunta, "seccion": seccion, "claves": [corto]}
    r = {"datos": {"valor": valor, "respuesta": resp, "tabla": [cab] + filas,
                   "explicacion": [f"Dato tomado automáticamente de la API oficial de estadísticas del BCRA. Se actualiza solo cada hora.",
                                   "Para actualizar un monto por este índice entre dos fechas, usá la calculadora de actualización."]},
         "fuentes": [{"nombre": "BCRA (API de estadísticas)", "url": "https://www.bcra.gob.ar/PublicacionesEstadisticas/Principales_variables.asp"}],
         "revisado": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cambiado": fecha}
    html = pagina_respuesta(t, r, notas, None, '<p><a class="btn" href="actualizacion.html">Ir a la calculadora de actualización</a></p>' if clave != "ipc" else "")
    return html.replace("La fábrica lo rechequea todos los días.", "Se actualiza solo cada hora.")


def bajar_dolares(destino):
    """Cotizaciones del día (DolarAPI) y últimos 30 días (ArgentinaDatos). Si no responden, no se arman esas páginas."""
    global DOLAR
    import ssl
    def leer(url):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ramacontable-build"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()))
        except ssl.SSLError:
            import certifi
            return json.load(urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context(cafile=certifi.where())))
    try:
        actual = {d["casa"]: d for d in leer("https://dolarapi.com/v1/dolares")}
    except Exception as ex:
        print("Aviso: no pude leer las cotizaciones del dólar:", ex)
        return
    hist = {}
    for _, casa, *_ in DOLARES:
        try:
            serie = leer(f"https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}")
            hist[casa] = [[x["fecha"], x.get("compra"), x.get("venta")] for x in serie[-30:]]
            clave = {"bolsa": "dolar_mep", "contadoconliqui": "dolar_ccl", "blue": "dolar_blue", "cripto": "dolar_cripto"}.get(casa)
            if clave:
                pts = {x["fecha"][:10]: x["venta"] for x in serie if x.get("venta")}
                fs = sorted(pts)
                nombre = {"dolar_mep": "Dólar MEP", "dolar_ccl": "Dólar contado con liquidación", "dolar_blue": "Dólar blue (informativo)", "dolar_cripto": "Dólar cripto"}[clave]
                json.dump({"nombre": nombre, "tipo": "indice", "f": fs, "v": [pts[x] for x in fs]},
                          open(os.path.join(destino, f"serie-{clave}.json"), "w", encoding="utf-8"), separators=(",", ":"))
        except Exception as ex:
            print(f"Aviso: sin historial del dólar {casa}:", ex)
    DOLAR = {"actual": actual, "hist": hist}
    os.makedirs(destino, exist_ok=True)
    json.dump(DOLAR, open(os.path.join(destino, "dolares.json"), "w", encoding="utf-8"), ensure_ascii=False)


def pagina_dolar(slug, casa, titulo, corto, notas):
    d = (DOLAR.get("actual") or {}).get(casa)
    if not d or not d.get("venta"):
        return None
    num = lambda x: "-" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    fecha = str(d.get("fechaActualizacion") or "")
    informal = casa == "blue"
    valor = f"$ {num(d['venta'])} venta"
    resp = (f"El {corto} cotiza a $ {num(d.get('compra'))} para la compra y $ {num(d['venta'])} para la venta"
            f" (actualizado el {_fecha_hora(fecha)}).")
    expl = ["Las cotizaciones de mercado se toman de DolarAPI, que reúne los precios publicados por bancos, la bolsa y las plataformas, y se actualizan solas cada hora en esta página."]
    if informal:
        resp += " Es una cotización informativa del mercado informal: no es un tipo de cambio oficial."
        expl.insert(0, "El dólar blue es la cotización del mercado informal. La publicamos solo como dato informativo, porque es una referencia muy consultada; para operaciones y registraciones contables se usa el tipo de cambio oficial.")
    if casa == "tarjeta":
        expl.insert(0, "El dólar tarjeta es el oficial más las percepciones que se cobran en los consumos en moneda extranjera con tarjeta.")
    tabla = [["Cotización", "Compra", "Venta"]] + [[x.get("nombre", k) + (" (informativa)" if k == "blue" else ""), num(x.get("compra")), num(x.get("venta"))]
                                                    for k, x in (DOLAR.get("actual") or {}).items()]
    h = (DOLAR.get("hist") or {}).get(casa) or []
    filas_h = "".join(f"<tr><td>{fecha_corta(a)}</td><td>{num(c)}</td><td>{num(v)}</td></tr>" for a, c, v in h[::-1])
    extra = (f'<h2>Últimos 30 días</h2><div class="tabla"><table><thead><tr><th>Fecha</th><th>Compra</th><th>Venta</th></tr></thead><tbody>{filas_h}</tbody></table></div>' if filas_h else "")
    extra += '<h2>Todas las cotizaciones de hoy</h2>' + bloque({"tabla": tabla}) + '<p><a href="dolar-hoy.html">Ver todas las cotizaciones del dólar</a></p>'
    t = {"slug": slug, "titulo": titulo, "pregunta": f"¿A cuánto está el {corto} hoy?", "seccion": "impuestos", "claves": [corto]}
    r = {"datos": {"valor": valor, "respuesta": resp, "explicacion": expl},
         "fuentes": [{"nombre": "DolarAPI", "url": "https://dolarapi.com"}, {"nombre": "ArgentinaDatos (historial)", "url": "https://argentinadatos.com"}],
         "revisado": fecha or datetime.datetime.now(datetime.timezone.utc).isoformat(), "cambiado": fecha[:10] or datetime.date.today().isoformat()}
    return pagina_respuesta(t, r, notas, None, extra).replace("<b>Vigente hoy,", "<b>Cotización consultada hoy,")


def pagina_dolar_hub(notas):
    act = DOLAR.get("actual") or {}
    if not act:
        return None
    num = lambda x: "-" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    links = {casa: slug for slug, casa, *_ in DOLARES}
    filas = "".join(f'<tr><td><a href="{links.get(k, "dolar-hoy")}.html">{e(x.get("nombre", k))}</a>{" <small>(informativa, mercado informal)</small>" if k == "blue" else ""}</td>'
                    f'<td>{num(x.get("compra"))}</td><td>{num(x.get("venta"))}</td><td>{_fecha_hora(x.get("fechaActualizacion"))}</td></tr>' for k, x in act.items())
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>Dólar hoy: todas las cotizaciones</h1><p class="ayuda">Oficial, mayorista, MEP, contado con liquidación, tarjeta, cripto y blue (cotización informativa del mercado informal). Se actualiza sola cada hora. Fuente: DolarAPI.</p>
<div class="tabla"><table><thead><tr><th>Cotización</th><th>Compra</th><th>Venta</th><th>Actualizado</th></tr></thead><tbody>{filas}</tbody></table></div></div>{lateral(notas)}</div>"""
    return pagina("Dólar hoy: oficial, MEP, CCL, tarjeta, cripto y blue | Ramacontable", cuerpo, "datos-al-dia",
                  "Cotización del dólar hoy en Argentina: oficial Banco Nación, mayorista, MEP, CCL, tarjeta, cripto y blue informativo. Actualizado cada hora.",
                  "dolar-hoy.html", migas=[("Datos del día", "datos-al-dia.html"), ("Dólar hoy", "dolar-hoy.html")])


def grupos_datos():
    """[(id, nombre, [(slug, titulo, valor)])] para el menú, la página general y la barra lateral."""
    val = lambda sl: (ajustar_tramo((RESP.get(sl) or {}).get("datos") or {}).get("valor") or "")
    g = [("sueldos", "Sueldos", [(t["slug"], t["titulo"], val(t["slug"])) for t in TEMAS_RESP if t.get("seccion") == "sueldos"]),
         ("impuestos", "Impuestos", [(t["slug"], t["titulo"], val(t["slug"])) for t in TEMAS_RESP if t.get("seccion") == "impuestos"]),
         ("indices", "Índices y tasas", [(b[0], b[2], "") for b in BCRA_RESP]),
         ("dolar", "Dólar y cripto", [("dolar-hoy", "Dólar hoy: todas las cotizaciones", "")] + [(x[0], x[2], "") for x in DOLARES]),
         ("vencimientos", "Vencimientos del mes por CUIT", [(o[0], o[1], "") for o in OBLIGACIONES]),
         ("calendario", "Calendario", [(f"que-cambia-en-{MESES[int(m[5:]) - 1]}-{m[:4]}", f"Qué cambia en {MESES[int(m[5:]) - 1]} {m[:4]}", "") for m in meses_que_cambia()[-2:]]
          + [("cuando-cambia-cada-dato", "Cuándo cambia cada dato", "")])]
    return g


def datos_para_calculadoras():
    """sitio/datos/datos-del-dia.json: lo que usan las calculadoras (monto, tablas y fecha de verificación)."""
    out = {}
    for t in TEMAS_RESP:
        r = RESP.get(t["slug"]) or {}
        d = ajustar_tramo(r.get("datos") or {})
        if d.get("valor"):
            out[t["slug"]] = {"valor": d.get("valor"), "monto": d.get("monto"), "estructurado": d.get("estructurado"),
                              "mes_vigente": d.get("mes_vigente"), "norma": d.get("norma"), "revisado": str(r.get("revisado") or "")[:10]}
    return out


def proximo_cambio(t):
    hoy = datetime.date.today()
    c = t.get("ciclo") or {}
    if c.get("tipo") == "movilidad":
        prox = [x for x in _ipc_fechas() if x >= hoy.isoformat()]
        return f"INDEC: {fecha_corta(prox[0])}; ANSES, días después" if prox else "Mediados de cada mes"
    for v in c.get("ventanas") or []:
        ini = v.split("/")[0]
        d = hoy.replace(month=int(ini[:2]), day=int(ini[3:]))
        if d < hoy:
            continue
        return f"Desde {MESES[d.month - 1]} {d.year}"
    if c.get("ventanas"):
        ini = c["ventanas"][0].split("/")[0]
        return f"Desde {MESES[int(ini[:2]) - 1]} {hoy.year + 1}"
    if c.get("diario_desde"):
        x = c["diario_desde"]
        return f"Desde {MESES[int(x[5:7]) - 1]} {x[:4]}"
    return "Sin fecha fija"


def pagina_calendario_datos(notas):
    filas = "".join(f'<tr><td><a href="{t["slug"]}.html">{e(t["titulo"])}</a></td><td>{e(t.get("cuando", ""))}</td><td>{e(proximo_cambio(t))}</td></tr>' for t in TEMAS_RESP)
    filas += ('<tr><td><a href="dolar-hoy.html">Dólar (oficial, MEP, CCL, tarjeta)</a></td><td>Días hábiles de 10 a 17</td><td>Se actualiza cada hora</td></tr>'
              '<tr><td><a href="dolar-cripto-hoy.html">Dólar cripto</a></td><td>Todos los días, las 24 horas</td><td>Se actualiza cada hora</td></tr>'
              '<tr><td><a href="valor-uva-hoy.html">UVA, CER, ICL y tasas</a></td><td>El BCRA los publica todos los días</td><td>Todos los días</td></tr>')
    ipc = "".join(f"<li>{fecha_corta(x)}</li>" for x in _ipc_fechas() if x >= datetime.date.today().isoformat())
    qs = [{"p": "¿Cuándo aumentan las jubilaciones?", "r": "Todos los meses, por la inflación de dos meses antes (Decreto 274/2024). El INDEC publica la inflación a mitad de mes y ANSES confirma los nuevos haberes en los días siguientes."},
          {"p": "¿Cuándo se actualiza el Monotributo?", "r": "Dos veces por año. Los montos nuevos se conocen alrededor de mediados de enero y de julio, y la recategorización vence en febrero y agosto."},
          {"p": "¿Cuándo cambian las deducciones de Ganancias?", "r": "Dos veces por año: hay tablas para enero a junio y para julio a diciembre."}]
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>Cuándo cambia cada dato: calendario de actualizaciones</h1>
<p class="ayuda">Cuándo se actualizan la jubilación, la AUH, el Monotributo, Ganancias, el salario mínimo y los demás datos que usamos todos los días.</p>
<div class="tabla"><table><thead><tr><th>Dato</th><th>Cuándo cambia</th><th>Próximo cambio</th></tr></thead><tbody>{filas}</tbody></table></div>
{('<h2>Próximas publicaciones de la inflación (INDEC)</h2><ul>' + ipc + '</ul>') if ipc else ''}
{preguntas_html({"preguntas": qs})}
<p class="aviso">Las fechas de ANSES, Monotributo y Ganancias son estimadas según cómo se publicaron en los últimos años. Las del INDEC salen de su calendario oficial.</p>
</div>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False) + "</script>"
    return pagina("Cuándo cambia cada dato: jubilaciones, AUH, Monotributo, Ganancias y salario mínimo | Ramacontable", cuerpo, "datos-al-dia",
                  "Calendario de actualizaciones: cuándo aumentan las jubilaciones y la AUH, cuándo se actualiza el Monotributo, Ganancias y el salario mínimo.",
                  "cuando-cambia-cada-dato.html", ld, [("Datos del día", "datos-al-dia.html"), ("Cuándo cambia cada dato", "cuando-cambia-cada-dato.html")])


def pagina_glosario(notas):
    try:
        terms = json.load(open(os.path.join(RAIZ, "glosario", "terminos.json"), encoding="utf-8"))
    except Exception:
        return None
    terms.sort(key=lambda x: unicodedata.normalize("NFD", x[1].lower()))
    letras, items = [], []
    for slug, nombre, defi, link in terms:
        l = unicodedata.normalize("NFD", nombre[0].upper())[0]
        if l not in letras:
            letras.append(l); items.append(f'<h2 id="letra-{l}">{l}</h2>')
        items.append(f'<div class="termino" id="{slug}"><h3>{e(nombre)}</h3><p>{e(defi)}</p>'
                     + (f'<p><a href="{link}">Ver más →</a></p>' if link else "") + "</div>")
    indice = " ".join(f'<a href="#letra-{l}">{l}</a>' for l in letras)
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><h1>Glosario contable, impositivo y laboral</h1>
<p class="ayuda">Los términos que más se usan al liquidar sueldos e impuestos en Argentina, explicados en una línea y con el enlace a su dato o calculadora.</p>
<p class="indice-letras">{indice}</p>{''.join(items)}</div>{lateral(notas)}</div>"""
    ld = {"@context": "https://schema.org", "@type": "DefinedTermSet", "name": "Glosario contable, impositivo y laboral", "url": sitio_url() + "glosario.html",
          "hasDefinedTerm": [{"@type": "DefinedTerm", "name": n, "description": d, "url": f"{sitio_url()}glosario.html#{sl}"} for sl, n, d, _ in terms]}
    head = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    return pagina("Glosario contable e impositivo: SAC, SMVM, base imponible, Monotributo y más | Ramacontable", cuerpo, "",
                  "Glosario de términos contables, impositivos y laborales de Argentina: aguinaldo, base imponible, SIPA, F.931, Monotributo, ICL, UVA y más.",
                  "glosario.html", head, [("Glosario", "glosario.html")])


def pagina_comparador(convenios, notas):
    fi, _ = _ultimo_serie("ipc")
    ipc12 = None
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", "serie-ipc.json"), encoding="utf-8"))
        c = 1.0
        for v in sr["v"][-12:]:
            c *= 1 + v / 100
        ipc12 = (c - 1) * 100 if len(sr["v"]) >= 12 else None
    except Exception:
        pass
    hace = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    filas = []
    for cv in sorted(convenios, key=lambda x: x["nombre"]):
        h = [x for x in (cv.get("historial") or []) if str(x.get("fecha", "")) >= hace and isinstance(x.get("aumento_pct"), (int, float))]
        if h:
            acum = 1.0
            for x in sorted(h, key=lambda z: z["fecha"]):
                acum *= 1 + x["aumento_pct"] / 100
            acum = (acum - 1) * 100
            dif = f"{acum - ipc12:+.1f} p.p.".replace(".", ",") if ipc12 is not None else "-"
            filas.append((acum, f'<tr><td><a href="escala-{cv["slug"]}.html">{e(cv["nombre"])}</a></td><td>{len(h)}</td><td><b>{_num(acum)}%</b></td><td>{dif}</td><td>{e(h[-1].get("periodo", ""))}</td></tr>'))
        else:
            filas.append((-999, f'<tr><td><a href="escala-{cv["slug"]}.html">{e(cv["nombre"])}</a></td><td>-</td><td colspan="3">Juntando datos: se completa con cada acuerdo nuevo</td></tr>'))
    filas.sort(key=lambda x: -x[0])
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="convenios.html">Escalas por convenio</a></p>
<h1>Comparador de aumentos por convenio vs. inflación</h1>
<p class="ayuda">Cuánto aumentaron los básicos de cada convenio en los últimos 12 meses, acuerdo por acuerdo, comparado con la inflación del mismo período{f' ({_num(ipc12)}% según el INDEC, hasta {MESES[int(fi[5:7]) - 1]} {fi[:4]})' if ipc12 is not None and fi else ''}.</p>
<div class="tabla"><table><thead><tr><th>Convenio</th><th>Acuerdos</th><th>Aumento 12 meses</th><th>Contra la inflación</th><th>Último acuerdo</th></tr></thead><tbody>{''.join(f for _, f in filas)}</tbody></table></div>
<p class="aviso">El aumento acumulado sale de los porcentajes de cada acuerdo publicado; no incluye sumas no remunerativas ni adicionales. El comparador se completa a medida que la fábrica registra cada acuerdo nuevo.</p>
</div>{lateral(notas)}</div>"""
    return pagina("Aumentos por convenio vs. inflación: comparador de paritarias | Ramacontable", cuerpo, "sueldos",
                  "Compará cuánto aumentó cada convenio colectivo en los últimos 12 meses contra la inflación: Comercio, UOCRA, UOM, Sanidad y más.",
                  "comparador-escalas.html", migas=[("Escalas por convenio", "convenios.html"), ("Comparador", "comparador-escalas.html")])


OBLIGACIONES = [  # páginas fijas de vencimientos por terminación de CUIT (salen de la agenda confirmada)
    ("vencimiento-931", "F.931: aportes y contribuciones de empleadores", ["931", "empleador"], "sueldos"),
    ("vencimiento-casas-particulares", "Casas particulares (F.102)", ["casas particulares", "f.102", "102"], "sueldos"),
    ("vencimiento-autonomos", "Autónomos", ["autónomo", "autonomo"], "sueldos"),
    ("vencimiento-monotributo", "Monotributo", ["monotribut"], "impuestos"),
    ("vencimiento-iva", "IVA", ["iva"], "impuestos"),
    ("vencimiento-iibb-arba", "Ingresos Brutos ARBA", ["arba", "ingresos brutos"], "impuestos"),
]


def _terminaciones(detalle):
    t = str(detalle or "").lower()
    if "cuit" not in t:
        return None
    m = t.split("cuit", 1)[1]
    ds = []
    def rango(x):
        ds.extend(range(int(x.group(1)), int(x.group(2)) + 1)); return " "
    m = re.sub(r"(\d)\s*(?:a|al|-|–)\s*(\d)", rango, m)
    ds += [int(c) for c in re.findall(r"\d", m)]
    return sorted(set(ds)) or None


def pagina_obligacion(slug, nombre, claves, seccion, notas):
    hoy = datetime.date.today()
    items = [x for x in proximos_vencimientos() if any(c in (x.get("concepto", "")).lower() for c in claves)]
    provincial = lambda c: bool(re.search(r"\b(iibb|ingresos brutos|convenio multilateral|sifere)\b", _N(c)))
    items = [x for x in items if ("arba" in _N(x.get("concepto", ""))) if slug == "vencimiento-iibb-arba"] if slug == "vencimiento-iibb-arba" \
        else [x for x in items if not provincial(x.get("concepto", ""))]
    if slug == "vencimiento-iva":
        items = [x for x in items if "iva" in re.findall(r"[a-záéíóú]+", x.get("concepto", "").lower())]
    meses = {}
    for x in items:
        meses.setdefault(x["fecha"][:7], []).append(x)
    bloques = ""
    for mes in sorted(meses)[:2]:
        filas = []
        for x in sorted(meses[mes], key=lambda z: z["fecha"]):
            t = _terminaciones(x.get("detalle"))
            dias = (datetime.date.fromisoformat(x["fecha"][:10]) - hoy).days
            falta = "hoy" if dias == 0 else (f"faltan {dias} días" if dias > 0 else "")
            filas.append(f'<tr><td>{"Terminación " + ", ".join(map(str, t)) if t else "Todos"}</td><td>{e(x.get("concepto", ""))}{(" · " + e(x["detalle"])) if x.get("detalle") and not t else ""}</td>'
                         f'<td><b>{fecha_corta(x["fecha"])}</b></td><td>{falta}</td></tr>')
        bloques += (f'<h2>{MESES[int(mes[5:7]) - 1].capitalize()} {mes[:4]}</h2><div class="tabla"><table><thead><tr><th>CUIT</th><th>Obligación</th><th>Vence</th><th></th></tr></thead>'
                    f'<tbody>{"".join(filas)}</tbody></table></div>')
    if not bloques:
        bloques = '<div class="resp-caja"><p>Las fechas de este mes están en verificación: se publican cuando las confirman al menos dos fuentes.</p></div>'
    mes_txt = f"{MESES[hoy.month - 1]} {hoy.year}"
    ant = MESES[hoy.month - 2] if hoy.month > 1 else "diciembre"
    titulo = f"Vencimientos de {nombre}: {mes_txt}, por terminación de CUIT"
    faq = ""
    if slug == "vencimiento-931":
        # como se busca: "fecha de pago de aportes noviembre", "vencimiento 931 octubre"
        titulo = f"Fecha de pago de aportes de {mes_txt}: vencimiento del F.931 por terminación de CUIT"
        este = sorted(meses.get(hoy.strftime("%Y-%m"), []), key=lambda z: z["fecha"])
        resp = ("; ".join(f"{('CUIT ' + ', '.join(map(str, _terminaciones(x.get('detalle')) or []))) if _terminaciones(x.get('detalle')) else 'todos'}: {fecha_corta(x['fecha'])}" for x in este)
                or "las fechas están en verificación")
        faq = preguntas_html({"preguntas": [
            {"p": f"¿Cuándo se pagan los aportes en {mes_txt}?", "r": f"En {mes_txt} se pagan los aportes y contribuciones del período {ant} (F.931). Fechas por terminación de CUIT del empleador: {resp}."},
            {"p": "¿Qué período se paga cada mes?", "r": "Cada mes se presenta y paga el F.931 de las remuneraciones del mes anterior: en noviembre se pagan los aportes de octubre, en diciembre los de noviembre, y así."}]})
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<p class="ayuda">Fechas confirmadas por al menos dos fuentes (o por Ignacio Online), ordenadas por terminación de CUIT. Si un vencimiento cae en día inhábil, la fecha ya figura corrida.</p>
{f'<p>En {mes_txt} vence el pago de los aportes y contribuciones del período <b>{ant}</b>.</p>' if slug == "vencimiento-931" else ""}
{bloques}{faq}
<p><a class="btn sec" href="agenda-vencimientos.html">Armar mi agenda por CUIT y bajarla al calendario →</a></p>
<p class="aviso">Información de carácter general. Verificá siempre en el calendario oficial de ARCA o del organismo.</p>
</div>{lateral(notas)}</div>"""
    tit_pag = (f"Fecha de pago de aportes {mes_txt}: vencimiento F.931 por CUIT" if slug == "vencimiento-931"
               else f"Vencimiento {nombre} {mes_txt} por terminación de CUIT")
    desc = (f"Fecha de pago de aportes y contribuciones de {mes_txt} (período {ant}): vencimientos del F.931 según la terminación de CUIT del empleador."
            if slug == "vencimiento-931" else f"Fechas de vencimiento de {nombre} de {mes_txt} según la terminación de CUIT, confirmadas con varias fuentes.")
    return pagina(f"{tit_pag} | Ramacontable", cuerpo, "datos-al-dia", desc,
                  slug + ".html", migas=[("Datos del día", "datos-al-dia.html"), (f"Vencimientos {nombre}", slug + ".html")])


def bloque_aguinaldo(n, notas):
    """Guías del aguinaldo: cuenta regresiva, tope del SAC y novedades del tema (cambian de verdad cada día)."""
    if not (es_guia(n) and "aguinaldo" in n.get("slug", "")):
        return ""
    hoy = datetime.date.today()
    vto = datetime.date(hoy.year, 6, 30) if hoy.month <= 6 else datetime.date(hoy.year, 12, 18)
    dias = (vto - hoy).days
    cuota = "primera" if vto.month == 6 else "segunda"
    if dias > 0:
        cuenta = f"Faltan <b>{dias} días</b> para el vencimiento de la {cuota} cuota del aguinaldo ({fecha_corta(vto.isoformat())})."
    elif dias == 0:
        cuenta = f"<b>Hoy vence</b> la {cuota} cuota del aguinaldo."
    else:
        cuenta = f"La {cuota} cuota del aguinaldo venció el {fecha_corta(vto.isoformat())}: si no se pagó, el trabajador puede intimar el pago."
    r = RESP.get("tope-aportes-base-maxima") or {}
    d = r.get("datos") or {}
    bm = (d.get("estructurado") or {}).get("base_maxima")
    mv = d.get("mes_vigente") or ""
    tope = ""
    if bm:
        mes_txt = f"{MESES[int(mv[5:7]) - 1]} {mv[:4]}" if mv else "vigente"
        tope = (f"<li>Tope de aportes para el aguinaldo (50% de la base máxima de {mes_txt}): <b>$ {_num(bm / 2)}</b>."
                + ("" if mv[5:7] == f"{vto.month:02d}" else f" La base de {MESES[vto.month - 1]} se publica en los próximos días y se actualiza acá sola.") + "</li>")
    nov = [x for x in notas if x["slug"] != n["slug"] and "aguinaldo" in (x["titulo"] + " " + x.get("encorto", "")).lower()][:5]
    lis = "".join(f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a> <small>{fecha_corta(str(x["fecha"])[:10])}</small></li>' for x in nov)
    nombre_mes = "junio" if vto.month == 6 else "diciembre"
    dia_sem = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][vto.weekday()]
    return (f'<section class="dato-hoy"><h2>Aguinaldo de {nombre_mes} {vto.year}: se paga hasta el {dia_sem} {vto.day} de {nombre_mes}</h2>'
            f'<p class="nota-chica">Actualizado el {hoy.day}/{hoy.month}/{hoy.year}</p><ul><li>{cuenta}</li>{tope}</ul>'
            + '<p><a class="btn" href="planillas/planilla-aguinaldo-varios-empleados.xlsx" download>Descargar planilla de aguinaldo para varios empleados (Excel)</a></p>'
            + (f"<h3>Novedades del aguinaldo</h3><ul>{lis}</ul>" if lis else "") + "</section>")


PARITARIAS_URLS = []
PAGINAS_FINAS = set()  # páginas sin dato todavía: noindex y fuera del sitemap hasta que tengan contenido
NOI = '<meta name="robots" content="noindex,follow">'
FERIADOS_URLS = []
QUE_CAMBIA_URLS = []
MES_DESDE = "2026-11"  # primer mes con páginas propias (quedan publicadas para siempre)
PAGINAS_MES = [  # (prefijo de la URL, dato del día, título, pregunta)
    ("aumento-jubilados", "jubilacion-minima-y-bono", "Aumento de jubilados {mes}: cuánto cobra la mínima", "¿Cuánto cobra un jubilado con la mínima en {mes}?"),
    ("auh", "asignaciones-familiares-auh", "AUH {mes}: cuánto se cobra por hijo", "¿Cuánto es la AUH en {mes}?"),
    ("tope-aportes", "tope-aportes-base-maxima", "Tope de aportes y contribuciones {mes}", "¿Cuál es el tope de aportes de {mes}?"),
    ("salario-minimo", "salario-minimo-vital-y-movil", "Salario mínimo vital y móvil {mes}", "¿Cuánto es el salario mínimo en {mes}?"),
    ("seguro-de-desempleo", "seguro-de-desempleo-montos", "Seguro de desempleo {mes}: montos", "¿Cuánto se cobra de desempleo en {mes}?"),
    ("ffep", "ffep-fondo-enfermedades-profesionales", "FFEP {mes}: importe por trabajador", "¿Cuánto es el FFEP en {mes}?"),
]


def _meses_paginas():
    hoy = datetime.date.today()
    y, m = int(MES_DESDE[:4]), int(MES_DESDE[5:])
    fin = (hoy.year + (hoy.month // 12), hoy.month % 12 + 1)  # hasta el mes que viene
    out = []
    while (y, m) <= fin:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def valor_de_mes(t, mes):
    """(valor, texto, estado) del dato para un mes dado: vigente, tramo ya fijado, cálculo anticipado o historial."""
    r = RESP.get(t["slug"]) or {}
    d = r.get("datos") or {}
    tr = (d.get("estructurado") or {}).get("tramos") or []
    x = [z for z in tr if str(z.get("desde", "")) <= mes]
    if x:
        z = max(x, key=lambda q: q["desde"])
        v = f"$ {_num(z['mensual'])} por mes" + (f" ($ {_num(z['hora'])} la hora)" if z.get("hora") else "")
        return v, f"Monto fijado por {d.get('norma') or 'la resolución vigente'}.", "fijado"
    if d.get("mes_vigente") == mes or (not d.get("mes_vigente") and mes == datetime.date.today().strftime("%Y-%m")):
        return d.get("valor"), d.get("respuesta") or "", "vigente"
    mv = d.get("mes_vigente")
    if mv and mes > mv and (t.get("ciclo") or {}).get("tipo") == "movilidad" and isinstance(d.get("monto"), (int, float)):
        fi, ipc = _ultimo_serie("ipc")
        y, m = int(mv[:4]), int(mv[5:])
        ant = (y, m - 1) if m > 1 else (y - 1, 12)
        sig = f"{y + (m // 12)}-{m % 12 + 1:02d}"
        if ipc is not None and fi and (int(fi[:4]), int(fi[5:7])) == ant and mes == sig:
            return (f"$ {_num(d['monto'] * (1 + ipc / 100))} (cálculo anticipado)",
                    f"Cálculo propio con la fórmula de movilidad (Decreto 274/2024): inflación de {MESES[ant[1] - 1]} {_num(ipc)}%. Se confirma con la resolución de ANSES.", "anticipado")
        return None, "El monto de este mes todavía no se publicó: se conoce unos días después del dato de inflación del INDEC.", "pendiente"
    for h in r.get("historial") or []:
        if str(h.get("fecha", ""))[:7] in (mes, ):
            return h.get("valor"), f"Valor publicado en {MESES[int(mes[5:]) - 1]} ({h.get('norma') or ''}).", "historico"
    return None, "Para este mes el dato se publica en cuanto lo confirmen las fuentes.", "pendiente"


def pagina_mes(pref, slug_dato, tit, preg, mes, notas):
    t = next((x for x in TEMAS_RESP if x["slug"] == slug_dato), None)
    if not t:
        return None
    mes_txt = f"{MESES[int(mes[5:]) - 1]} {mes[:4]}"
    valor, texto, estado = valor_de_mes(t, mes)
    etiqueta = {"vigente": "Vigente", "fijado": "Ya fijado", "anticipado": "Cálculo anticipado", "historico": "Valor de ese mes", "pendiente": "Todavía no publicado"}[estado]
    titulo = tit.format(mes=mes_txt)
    pregunta = preg.format(mes=mes_txt)
    otros = "".join(f'<li><a href="{pref}-{MESES[int(m2[5:]) - 1]}-{m2[:4]}.html">{MESES[int(m2[5:]) - 1].capitalize()} {m2[:4]}</a></li>' for m2 in _meses_paginas() if m2 != mes)
    caja = (f'<div class="resp-caja"><span class="resp-p">{e(pregunta)}</span><b class="resp-v">{e(valor or "Todavía no publicado")}</b>'
            f'<p><span class="nivel">{etiqueta}</span> {e(texto)}</p></div>')
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a> / <a href="{t['slug']}.html">{e(t['titulo'])}</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
{caja}
<p><a class="btn" href="{t['slug']}.html">Ver el dato vigente hoy y su historial →</a></p>
<section class="relacionadas"><h2>Otros meses</h2><ul>{otros}</ul></section>
<p class="aviso">Información de carácter general. Verificá siempre en la norma oficial.</p>
</div>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": pregunta, "acceptedAnswer": {"@type": "Answer", "text": f"{valor}. {texto}" if valor else texto}}]}, ensure_ascii=False) + "</script>"
    if not valor:
        PAGINAS_FINAS.add(f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}")
    return pagina(f"{titulo}{': ' + valor if valor else ''} | Ramacontable", cuerpo, "datos-al-dia",
                  f"{pregunta} {valor or ''} {texto}"[:300], f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}.html", ld + ("" if valor else NOI),
                  [("Datos del día", "datos-al-dia.html"), (titulo, f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}.html")])


def urls_mes():
    return [f"{p[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}" for p in PAGINAS_MES for m in _meses_paginas()]


def pagina_paritaria(c, mes, notas):
    mes_txt = f"{MESES[int(mes[5:]) - 1]} {mes[:4]}"
    esc = c.get("escala") or {}
    periodo = esc.get("periodo") or ""
    nombre_mes = MESES[int(mes[5:]) - 1]
    cubre = bool(periodo) and nombre_mes in periodo.lower() and mes[:4] in periodo
    hist = sorted(c.get("historial") or [], key=lambda h: str(h.get("fecha", "")), reverse=True)
    if cubre:
        estado = f"La escala vigente para {mes_txt} es la de <b>{e(periodo)}</b>."
    elif periodo:
        estado = (f"Para {mes_txt} todavía no se publicó un acuerdo nuevo. La última escala cargada es la de <b>{e(periodo)}</b>; "
                  "la actualizamos en cuanto se homologue o la publiquen el gremio o las cámaras.")
    else:
        estado = f"Para {mes_txt} todavía no tenemos la escala confirmada con fuentes: se publica apenas la confirmen el gremio o dos portales."
    tabla = ""
    t = esc.get("tabla") or []
    if cubre and len(t) > 1:
        tabla = bloque({"tabla": t[:13]}) + ('<p class="nota-chica">Escala completa en la página del convenio.</p>' if len(t) > 13 else "")
    def fila_h(h):
        pct = (_num(h["aumento_pct"]) + "%") if isinstance(h.get("aumento_pct"), (int, float)) else "-"
        link = f'<a href="nota-{h["nota"]}.html">ver nota</a>' if h.get("nota") else ""
        return f"<tr><td>{e(h.get('periodo') or '')}</td><td>{pct}</td><td>{link}</td></tr>"
    filas_h = "".join(fila_h(h) for h in hist[:6])
    h_html = (f'<h2>Últimos acuerdos</h2><div class="tabla"><table><thead><tr><th>Período</th><th>Aumento</th><th></th></tr></thead><tbody>{filas_h}</tbody></table></div>' if filas_h else "")
    rel = [n for n in notas if c["nombre"].split(" (")[0].lower() in n["titulo"].lower()][:4]
    rel_html = ("<h2>Novedades del convenio</h2><ul>" + "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel) + "</ul>") if rel else ""
    titulo = f"Paritarias {c['nombre']} {mes_txt}: escala salarial y aumento"
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="convenios.html">Escalas por convenio</a> / <a href="escala-{c['slug']}.html">{e(c['nombre'])}</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · {e(c.get('cct') or '')} · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
<div class="resp-caja"><p>{estado}</p></div>
{tabla}
<p><a class="btn" href="escala-{c['slug']}.html">Ver la escala completa de {e(c['nombre'])} →</a></p>
{h_html}{rel_html}
<p class="aviso">Información de carácter general. Verificá siempre en el acuerdo homologado.</p>
</div>{lateral(notas)}</div>"""
    if not periodo:
        PAGINAS_FINAS.add(f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}")
    return pagina(f"{titulo} | Ramacontable", cuerpo, "sueldos",
                  f"Paritarias {c['nombre']} ({c.get('cct') or ''}) {mes_txt}: escala salarial vigente, aumentos y sumas no remunerativas.",
                  f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}.html", NOI if not periodo else "", migas=[("Escalas por convenio", "convenios.html"), (titulo, f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}.html")])


DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def pagina_feriados_anio(ruta, notas):
    d = json.load(open(ruta, encoding="utf-8"))
    anio = d["anio"]
    hoy = datetime.date.today().isoformat()
    def fila(x):
        f = datetime.date.fromisoformat(x["fecha"])
        cls = {"Inamovible": "t-ina", "Trasladable": "t-tra"}.get(x["tipo"], "t-no")
        return (f'<tr data-f="{x["fecha"]}"><td>{DIAS_SEM[f.weekday()].capitalize()} {f.day} de {MESES[f.month - 1]}</td><td>{e(x["nombre"])}</td>'
                f'<td><span class="tipo-f {cls}">{e(x["tipo"])}</span></td></tr>')
    lista = sorted(d["feriados"], key=lambda x: x["fecha"])
    prox = next((x for x in lista if x["fecha"] >= hoy), None)
    n_ina = sum(1 for x in lista if x["tipo"] == "Inamovible")
    fuentes = " · ".join(f'<a href="{e(f["url"])}" rel="nofollow noopener" target="_blank">{e(f["nombre"])}</a>' for f in d.get("fuente", []))
    qs = [{"p": f"¿Cuántos feriados hay en {anio}?", "r": f"El calendario {anio} tiene {n_ina} feriados inamovibles, {sum(1 for x in lista if x['tipo'] == 'Trasladable')} trasladables y {sum(1 for x in lista if x['tipo'] == 'No laborable')} días no laborables, sin contar los días con fines turísticos que fije el Gobierno."},
          {"p": f"¿Cuándo es Carnaval {anio}?", "r": "Carnaval " + str(anio) + ": " + " y ".join(f"{DIAS_SEM[datetime.date.fromisoformat(x['fecha']).weekday()]} {int(x['fecha'][8:])} de {MESES[int(x['fecha'][5:7]) - 1]}" for x in lista if x["nombre"] == "Carnaval") + "."},
          {"p": "¿Qué pasa con los feriados trasladables?", "r": "Según la Ley 27.399, los feriados trasladables que caen martes o miércoles pasan al lunes anterior, y los que caen jueves o viernes pasan al lunes siguiente. El Gobierno confirma los traslados y los días no laborables con fines turísticos por decreto."}]
    cuerpo = f"""<div class="grilla"><article class="nota calc">
<p class="ante">Calendario | Ley 27.399</p>
<h1>Feriados {anio} en Argentina: calendario completo</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
{f'<div class="encorto"><b>Primer feriado de {anio}</b><p>{e(prox["nombre"])}: {DIAS_SEM[datetime.date.fromisoformat(prox["fecha"]).weekday()]} {int(prox["fecha"][8:])} de {MESES[int(prox["fecha"][5:7]) - 1]}.</p></div>' if prox else ''}
<div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Feriado</th><th>Tipo</th></tr></thead><tbody>{''.join(fila(x) for x in lista)}</tbody></table></div>
<p class="ayuda">Los feriados trasladables figuran en su fecha original: el Gobierno confirma por decreto a qué lunes se mueven y si habrá días no laborables con fines turísticos (puentes). Lo actualizamos apenas se publique.</p>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> {fuentes}</p>
<p><a href="dias-habiles.html">Calculadora de días hábiles</a> · <a href="feriados.html">Feriados del año en curso</a></p>
</article>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False) + "</script>"
    return anio, pagina(f"Feriados {anio} en Argentina: calendario completo, inamovibles y trasladables | Ramacontable", cuerpo, "",
                        f"Calendario de feriados {anio} en Argentina: inamovibles, trasladables, Carnaval, Semana Santa y días no laborables.",
                        f"feriados-{anio}.html", ld, [("Feriados", "feriados.html"), (f"Feriados {anio}", f"feriados-{anio}.html")])


def meses_que_cambia():
    """Mes actual y, desde el día 20, también el que viene (las páginas anteriores quedan publicadas)."""
    hoy = datetime.date.today()
    ms = [m for m in _meses_paginas() if m <= hoy.strftime("%Y-%m")]
    sig = f"{hoy.year + (hoy.month // 12)}-{hoy.month % 12 + 1:02d}"
    if hoy.day >= 20:
        ms.append(sig)
    return ms


def pagina_que_cambia(mes, notas):
    y, m = int(mes[:4]), int(mes[5:])
    mes_txt = f"{MESES[m - 1]} {y}"
    items = []
    for pref, slug_dato, tit, _ in PAGINAS_MES:
        t = next((x for x in TEMAS_RESP if x["slug"] == slug_dato), None)
        if not t:
            continue
        valor, texto, estado = valor_de_mes(t, mes)
        if valor:
            items.append(f'<li><b>{e(t["titulo"])}:</b> {e(valor)}{" (cálculo anticipado)" if estado == "anticipado" and "anticipado" not in valor else ""}. '
                         f'<a href="{pref}-{MESES[m - 1]}-{y}.html">Ver detalle</a></li>')
    if m in (6, 12):
        vto = datetime.date(y, 6, 30) if m == 6 else datetime.date(y, 12, 18)
        items.insert(0, f'<li><b>Aguinaldo:</b> vence el {DIAS_SEM[vto.weekday()]} {vto.day} de {MESES[m - 1]}. '
                        '<a href="aguinaldo.html">Calculadora de aguinaldo</a></li>')
    fer = []
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        fer += [x for x in json.load(open(ruta, encoding="utf-8")).get("feriados", []) if x["fecha"].startswith(mes)]
    fer += [x for fila in VENC for x in fila.get("feriados") or [] if str(x.get("fecha", "")).startswith(mes) and not any(f["fecha"] == x["fecha"] for f in fer)]
    if mes == "2026-12" and not fer:
        fer = [{"fecha": "2026-12-08", "nombre": "Inmaculada Concepción de María"}, {"fecha": "2026-12-25", "nombre": "Navidad"}]
    fer_html = "".join(f"<li>{DIAS_SEM[datetime.date.fromisoformat(x['fecha']).weekday()].capitalize()} {int(x['fecha'][8:])}: {e(x['nombre'])}</li>" for x in sorted(fer, key=lambda z: z["fecha"]))
    venc = [x for x in proximos_vencimientos() if str(x["fecha"]).startswith(mes)]
    destac = [x for x in venc if any(k in x.get("concepto", "").lower() for k in ("931", "monotrib", "iva", "autónom", "casas particulares", "ganancias", "bienes personales"))][:12]
    venc_html = "".join(f"<li>{fecha_corta(x['fecha'])}: {e(x['concepto'])}{(' · ' + e(x['detalle'])) if x.get('detalle') else ''}</li>" for x in destac)
    nombre = MESES[m - 1]
    rel = [n for n in notas if nombre in n["titulo"].lower() and str(y) in n["titulo"]][:8]
    rel_html = "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel)
    titulo = f"Qué cambia en {mes_txt}: aguinaldo, jubilaciones, salario mínimo, feriados y vencimientos" if m in (6, 12) else \
        f"Qué cambia en {mes_txt}: jubilaciones, AUH, salario mínimo, feriados y vencimientos"
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
<p class="ayuda">Todo lo que cambia en {mes_txt} para liquidar sueldos e impuestos, en una sola página. Se actualiza sola a medida que se confirman los datos.</p>
{('<h2>Montos que cambian</h2><ul>' + ''.join(items) + '</ul>') if items else ''}
{('<h2>Feriados de ' + nombre + '</h2><ul>' + fer_html + '</ul>') if fer_html else ''}
{('<h2>Vencimientos destacados</h2><ul>' + venc_html + '</ul><p><a href="agenda-vencimientos.html">Armá tu agenda por CUIT →</a></p>') if venc_html else ''}
{('<h2>Novedades de ' + nombre + '</h2><ul>' + rel_html + '</ul>') if rel_html else ''}
<p class="aviso">Información de carácter general. Verificá siempre en las fuentes oficiales.</p>
</div>{lateral(notas)}</div>"""
    url = f"que-cambia-en-{nombre}-{y}"
    flaca = len(items) + (1 if fer_html else 0) + (1 if venc_html else 0) < 3
    if flaca:
        PAGINAS_FINAS.add(url)
    return url, pagina(f"{titulo} | Ramacontable", cuerpo, "datos-al-dia",
                       f"Qué cambia en {mes_txt}: montos de jubilaciones, AUH, salario mínimo y tope de aportes, feriados y vencimientos del mes, en una sola página.",
                       url + ".html", NOI if flaca else "", [("Datos del día", "datos-al-dia.html"), (titulo, url + ".html")])


def pagina_datos(notas):
    existe = lambda sl: os.path.exists(os.path.join(SALIDA, sl + ".html")) or any(t["slug"] == sl for t in TEMAS_RESP)
    bloques = ""
    for gid, nombre, items in grupos_datos():
        lis = "".join(f'<li><a href="{sl}.html"><b>{e(ti)}</b><span>{e(v or "Ver el dato")}</span></a></li>' for sl, ti, v in items if existe(sl))
        if lis:
            bloques += f'<h2 id="{gid}">{e(nombre)}</h2><ul class="lista-datos">{lis}</ul>'
    items = [bloques + '<p><a class="btn sec" href="cuando-cambia-cada-dato.html">Ver cuándo cambia cada dato →</a></p>']
    cuerpo = f"""<div class="grilla"><div><h1>Datos del día</h1>
<p class="ayuda">Los datos que más se consultan, en una página fija cada uno y siempre actualizados: la fábrica los rechequea todos los días contra las fuentes oficiales y solo publica lo que confirman al menos dos fuentes.</p>
{''.join(items)}</div>{lateral(notas)}</div>"""
    return pagina("Datos del día: salario mínimo, Monotributo, jubilación, dólar, UVA y más | Ramacontable", cuerpo, "datos-al-dia",
                  "Salario mínimo, jubilación mínima, AUH, Monotributo, Ganancias, UVA, CER y dólar oficial: los datos vigentes hoy, revisados todos los días.",
                  "datos-al-dia.html", migas=[("Datos del día", "datos-al-dia.html")])


# Enlaces internos automáticos: la primera mención de cada tema en una nota enlaza a su página fija
def _destinos_enlaces(convenios):
    d = []
    for t in TEMAS_RESP:
        for c in t.get("claves", []):
            d.append((c, t["slug"] + ".html"))
    for c in convenios:
        for nombre in {c.get("nombre", ""), *(c.get("alias") or [])}:
            if nombre and len(nombre) > 3:
                d.append((nombre, f"escala-{c['slug']}.html"))
    d += [("aguinaldo", "aguinaldo.html"), ("UVA", "valor-uva-hoy.html"), ("CER", "cer-hoy.html"),
          ("indemnización", "liquidacion-final.html"), ("liquidación final", "liquidacion-final.html"), ("horas extras", "horas-extras.html"),
          ("vacaciones", "vacaciones.html"), ("dólar blue", "dolar-blue-hoy.html"), ("dólar MEP", "dolar-mep-hoy.html"),
          ("contado con liquidación", "dolar-ccl-hoy.html"), ("dólar tarjeta", "dolar-tarjeta-hoy.html"), ("dólar oficial", "dolar-oficial-hoy.html"),
          ("ICL", "icl-alquileres-hoy.html"), ("BADLAR", "tasa-badlar-hoy.html"), ("TAMAR", "tasa-tamar-hoy.html"), ("días hábiles", "dias-habiles.html"), ("plazo fijo", "plazo-fijo.html")]
    return sorted(d, key=lambda x: -len(x[0]))


ENLACES = []


def enlazar(html_txt, propio=""):
    """Agrega como máximo 1 enlace por destino y 5 por nota, solo en texto de párrafos (nunca en títulos ni dentro de otro enlace)."""
    usados, puestos = set(), [0]
    def en_parrafo(m):
        txt = m.group(1)
        for frase, destino in ENLACES:
            if destino in usados or destino == propio or puestos[0] >= 5:
                continue
            rx = re.compile(r"(?<![\w>])(" + re.escape(e(frase)) + r")(?![\w<])", re.I)
            partes = re.split(r"(<a [^>]*>.*?</a>)", txt)
            for i, parte in enumerate(partes):
                if parte.startswith("<a "):
                    continue
                nuevo, n = rx.subn(lambda x: f'<a href="{destino}">{x.group(1)}</a>', parte, count=1)
                if n:
                    partes[i] = nuevo; usados.add(destino); puestos[0] += 1
                    break
            txt = "".join(partes)
        return "<p>" + txt + "</p>"
    return re.sub(r"<p>(.*?)</p>", en_parrafo, html_txt, flags=re.S)


def dato_de_nota(n):
    """Tema de datos del día que trata la nota (por sus palabras clave en título y resumen)."""
    txt = (n.get("titulo", "") + " " + n.get("encorto", "")).lower()
    for t in TEMAS_RESP:
        if any(c.lower() in txt for c in t.get("claves", [])):
            return t
    return None


_DUDOSA = re.compile(r"consultar|estimad|aproximad|a confirmar|s/d|sin dato", re.I)


def tabla_dudosa(b):
    return "tabla" in b and any(_DUDOSA.search(str(c)) for fila in b["tabla"] for c in fila)


def caja_dato_vigente(n):
    t = dato_de_nota(n)
    if not t:
        return ""
    r = RESP.get(t["slug"]) or {}
    d = ajustar_tramo(r.get("datos") or {})
    vieja = ""
    camb = str(r.get("cambiado") or "")[:10]
    if camb and str(n.get("actualizado") or n["fecha"])[:10] < camb:
        f = str(n["fecha"])[:10]
        vieja = f"<b>Esta nota es de {MESES[int(f[5:7]) - 1]} {f[:4]}.</b> Desde entonces los valores cambiaron. "
    return (f'<div class="dato-vigente">{vieja}Valor vigente hoy de <b>{e(t["titulo"])}</b>: '
            f'{e(d.get("valor") or "en verificación")}. <a href="{t["slug"]}.html">Ver la tabla vigente →</a></div>')


def pagina_nota(n, notas, aportes=None):
    verif = ("Elaborada con fuentes oficiales." if n.get("verificada")
             else "Pendiente de verificación con fuente oficial.")
    t_dato = dato_de_nota(n)
    extra_calc = bloque_aguinaldo(n, notas) + ('<div class="dato-vigente"><b>Calculalo:</b> <a href="aguinaldo.html">calculadora de aguinaldo</a> · '
                  '<a href="tope-aportes-base-maxima.html">tope de aportes vigente</a> · <a href="retencion-ganancias.html">retención de Ganancias</a></div>'
                  if "aguinaldo" in (n.get("titulo", "") + " " + n.get("slug", "")).lower() else "")
    cuerpo = extra_calc + enlazar("".join(
        (f'<p class="dato-vigente">La tabla completa y actualizada está en <a href="{t_dato["slug"]}.html">{e(t_dato["titulo"])}</a>.</p>' if t_dato
         else "") if tabla_dudosa(b) else bloque(b) for b in n["cuerpo"]), f"nota-{n['slug']}.html")
    sec = SECCIONES[n["seccion"]]
    previa = ""
    if n.get("actualiza"):
        previa = f'<p class="actualiza">Esta nota actualiza a: <a href="nota-{e(n["actualiza"])}.html">la nota anterior sobre el tema</a></p>'
    contenido = f"""<div class="grilla"><article class="nota" data-nota="{n['slug']}" data-actualizado="{e(str(n.get('actualizado') or ''))}">
<div class="nota-contenido">
{portada_html(n, "nota")}
<p class="miga">{f'<a href="guias.html">Guías</a> / <a href="guias.html#{n["seccion"]}">{RAMAS_GUIAS.get(n["seccion"], sec)}</a>' if es_guia(n) else f'<a href="{n["seccion"]}.html">{sec}</a>'}</p>
<p class="ante">{e(n['antetitulo'])}</p>
<h1>{e(n['titulo'])}</h1>
<p class="firma">Redacción Ramacontable · {('Guía actualizada al ' + fecha_larga(str(n.get('actualizado') or n['fecha'])[:10])) if es_guia(n) else fecha_larga(n['fecha'])}</p>
{previa}
{caja_dato_vigente(n)}
<div class="encorto"><b>En corto</b><p>{e(n['encorto'])}</p></div>
{cuerpo}
{preguntas_html(n)}
<p class="fuente"><b>Fuente:</b> {e(n['fuente'])}</p>
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. {verif}</p>
</div>

{relacionadas(n, notas)}
{bloque_aportes(n, aportes)}
</article>{lateral(notas)}</div>"""
    url = f"{sitio_url()}nota-{n['slug']}.html"
    ld = [{"@context": "https://schema.org", "@type": "Article" if es_guia(n) else "NewsArticle", "headline": n["titulo"][:110],
           "description": n.get("descripcion_seo") or n["encorto"], "datePublished": str(n["fecha"]),
           "dateModified": datetime.date.today().isoformat() if (es_guia(n) and "aguinaldo" in n["slug"]) else str(n.get("actualizado") or n["fecha"]), "inLanguage": "es-AR",
           "mainEntityOfPage": url, "articleSection": SECCIONES[n["seccion"]],
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "icono-512.png"}}}]
    if n.get("preguntas"):
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in n["preguntas"]]})
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    head += f'<meta property="og:type" content="article"><meta property="article:published_time" content="{e(str(n["fecha"]))}">'
    migas = ([("Guías", "guias.html"), (RAMAS_GUIAS.get(n["seccion"], "Guías"), f"guias.html#{n['seccion']}")] if es_guia(n)
             else [(SECCIONES[n["seccion"]], f"{n['seccion']}.html")]) + [(n["titulo"][:80], f"nota-{n['slug']}.html")]
    return pagina(n.get("seo_titulo") or f"{n['titulo']} | Ramacontable", contenido, n["seccion"],
                  n.get("descripcion_seo") or n["encorto"], f"nota-{n['slug']}.html", head, migas,
                  f"compartir/{n['slug']}.png" if n["slug"] in PORTADAS_OK else "compartir.png")


DESC_SECCION = {
    "sueldos": "Novedades de sueldos, escalas salariales por convenio, sumas no remunerativas, guías y calculadoras para liquidar.",
    "impuestos": "Novedades impositivas de ARCA y rentas provinciales: Ganancias, IVA, Monotributo, Bienes Personales, Ingresos Brutos y más.",
    "profesion": "Novedades para el ejercicio de la profesión contable: consejos profesionales, normas contables, sociedades y trámites.",
    "economia": "Novedades económicas que impactan en el trabajo del contador.",
}


# ---------- Provincias y municipios ----------
JURIS = []      # jurisdicciones con página propia (jurisdicciones/<slug>.json)
OTRAS_J = []    # provincias que por ahora solo muestran novedades (jurisdicciones/otras.json)
JURIS_URLS = []
TABLAS_URLS = []


def cargar_jurisdicciones():
    JURIS[:], OTRAS_J[:] = [], []
    for ruta in sorted(glob.glob(os.path.join(RAIZ, "jurisdicciones", "*.json"))):
        try:
            d = json.load(open(ruta, encoding="utf-8"))
        except Exception as ex:
            print("Aviso: no pude leer", ruta, ex)
            continue
        if os.path.basename(ruta) == "otras.json":
            OTRAS_J[:] = d.get("lista") or []
        elif d.get("slug") and d.get("ruta"):
            JURIS.append(d)
    JURIS.sort(key=lambda j: j.get("orden", 99))


def _de_jurisdiccion(n, claves, solo_titulo=False):
    txt = _N(n.get("titulo", "") + ("" if solo_titulo else " " + n.get("antetitulo", "") + " " + (n.get("tema") or "") + " " + n.get("encorto", "")))
    return any(re.search(r"\b" + re.escape(_N(c)) + r"\b", txt) for c in claves)


def nota_de_nicho(n):
    """Notas de una provincia o municipio que no se muestran en la portada (siguen en su sección y en su página)."""
    return any(not j.get("portada", True) and _de_jurisdiccion(n, j.get("claves") or [], True) for j in JURIS) or \
        any(_de_jurisdiccion(n, o.get("claves") or [], True) for o in OTRAS_J)


def _venc_de(claves):
    return [x for x in proximos_vencimientos() if any(re.search(r"\b" + re.escape(_N(c)) + r"\b", _N(x.get("concepto", "") + " " + x.get("detalle", ""))) for c in claves)]


def pagina_jurisdiccion(j, notas):
    hoy = datetime.date.today()
    temas = [t for t in TEMAS_RESP if t.get("jurisdiccion") == j["slug"]]
    cajas = ""
    for t in temas:
        d = ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {})
        if d.get("valor"):
            cajas += (f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><b class="resp-v">{e(d["valor"])}</b>'
                      f'<p>{e(d.get("respuesta", ""))}</p>' + (f'<p class="resp-meta">Norma: {e(d["norma"])}</p>' if d.get("norma") else "")
                      + f'<p><a class="btn sec" href="{t["slug"]}.html">Ver la tabla completa por categoría →</a></p></div>')
    fijos = "".join(bloque(b) for b in j.get("bloques") or [])
    fijos += "".join(f'<p><a class="btn" href="{t["ruta"]}.html">{e(t["titulo_corto"])}: buscá tu actividad →</a></p>' for t in j.get("tablas") or [])
    if j.get("paginas"):
        fijos += '<p>' + " · ".join(f'<a href="{pg["ruta"]}.html">{e(pg["titulo_corto"])} →</a>' for pg in j["paginas"]) + '</p>'
    venc = _venc_de(j.get("venc_claves") or [])
    venc_html = ""
    if venc:
        venc_html = ('<h2>Próximos vencimientos</h2><div class="tabla"><table><thead><tr><th>Vence</th><th>Obligación</th><th>CUIT</th></tr></thead><tbody>'
                     + "".join(f'<tr><td><b>{fecha_corta(x["fecha"])}</b></td><td>{e(x["concepto"])}</td><td>{e(x.get("detalle") or "Todas")}</td></tr>' for x in venc[:15])
                     + '</tbody></table></div><p class="ayuda">Fechas confirmadas por al menos dos fuentes o por el organismo. Si cae en día inhábil, ya figura corrida.</p>')
    rel = [n for n in notas if _de_jurisdiccion(n, j.get("claves") or [])]
    nov = ('<h2>Novedades de ' + e(j["nombre"]) + '</h2><div class="tarjetas">' + "".join(tarjeta(n) for n in rel[:12]) + "</div>") if rel else \
        f'<h2>Novedades de {e(j["nombre"])}</h2><p class="vacio">Cuando {e(j["organismo"])} publique una novedad para la profesión, aparece acá.</p>'
    of = " · ".join(f'<a href="{e(o["url"])}" rel="nofollow noopener" target="_blank">{e(o["nombre"])}</a>' for o in j.get("oficiales") or [])
    otras = "".join(f'<li><a href="{x["ruta"]}.html">{e(x["titulo_corto"])}</a></li>' for x in JURIS if x["slug"] != j["slug"])
    qs = []
    for t in temas:
        d = (RESP.get(t["slug"]) or {}).get("datos") or {}
        if d.get("respuesta"):
            qs.append({"p": t["pregunta"], "r": d["respuesta"]})
        qs += [q for q in d.get("preguntas") or [] if q.get("p") != t["pregunta"]][:1]
    cuerpo = f"""<div class="grilla"><article class="nota"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a></p>
<p class="ante">{e(j["organismo"])}</p>
<h1>{e(j["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<p>{e(j.get("intro", ""))}</p>
{cajas}{fijos}{venc_html}{preguntas_html({"preguntas": qs})}
{f'<p class="fuente"><b>Sitios oficiales:</b> {of}</p>' if of else ""}
<p class="aviso">Información de carácter general. Verificá siempre en el sitio oficial del organismo. Cada profesional es responsable de su aplicación.</p>
</div>
{nov}
<section class="relacionadas"><h2>Otras provincias y municipios</h2><ul>{otras}<li><a href="provincias-y-municipios.html">Ver todas</a></li></ul></section>
</article>{lateral(notas)}</div>"""
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    if not cajas and not fijos and not rel and not venc:
        PAGINAS_FINAS.add(j["ruta"])
        ld += NOI
    return pagina(f'{j["titulo"]} | Ramacontable', cuerpo, "impuestos", j["descripcion"], j["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html")])


def pagina_tabla_juris(j, t, notas):
    """Tabla grande de una jurisdicción (ej.: alícuotas de Seguridad e Higiene por actividad) con buscador."""
    d = json.load(open(os.path.join(RAIZ, t["archivo"]), encoding="utf-8"))
    filas = d["filas"]
    por = {f[0]: f for f in filas}
    dest = [por[c] for c in t.get("destacados") or [] if c in por]
    fila = lambda f: "<tr>" + "".join(f"<td>{'<b>' + e(x) + '</b>' if i == 2 else e(x)}</td>" for i, x in enumerate(f)) + "</tr>"
    cab = "".join(f"<th>{e(c)}</th>" for c in d["columnas"])
    if len(d["columnas"]) < 4:
        return _pagina_tabla_simple(j, t, d, filas, dest, fila, cab, notas)
    cuenta = {}
    for f in filas:
        cuenta[f[2]] = cuenta.get(f[2], 0) + 1
    gral, n_gral = max(cuenta.items(), key=lambda x: x[1])
    minimos = {}
    for f in filas:
        minimos[f[3]] = minimos.get(f[3], 0) + 1
    min_gral = max(minimos.items(), key=lambda x: x[1])[0]
    qs = [{"p": f"¿Cuál es la alícuota de Seguridad e Higiene en {j['nombre']} en 2026?",
           "r": f"Depende de la actividad. La más común es {gral} ({n_gral} de {len(filas)} actividades), con un mínimo de {min_gral} por mes. Va del 4‰ (actividades agropecuarias) al 75‰ (bancos y entidades financieras). {d['norma']}."},
          {"p": "¿Cuál es el mínimo mensual de la tasa?", "r": f"Para casi todas las actividades, {min_gral} por mes. Hay excepciones: algunas actividades tienen mínimo $ 0 (por ejemplo, servicios públicos, culturales o de organizaciones sin fines de lucro) y las salas de bingo y tragamonedas tienen mínimos más altos."},
          {"p": "¿Cómo encuentro mi actividad?", "r": "Buscala por el código de actividad que tenés en ARCA (NAES) o por una palabra de la descripción. Los códigos de 5 cifras son los mismos que en ARCA empiezan con 0."}]
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    cuerpo = f"""<div class="grilla"><article class="nota calc"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])} | {e(d["norma"])}</p>
<h1>{e(t["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · {e(d["vigencia"])}</p>
<div class="encorto"><b>En corto</b><p>En {e(j["nombre"])}, la alícuota más común de la Tasa por Inspección de Seguridad e Higiene 2026 es <b>{e(gral)}</b> con un mínimo de <b>{e(min_gral)} por mes</b>. Cada actividad tiene su alícuota máxima y su mínimo en el Anexo de la ordenanza: buscá la tuya abajo.</p></div>
<h2>Las actividades más buscadas</h2>
<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in dest)}</tbody></table></div>
<h2>Buscá tu actividad ({len(filas)} actividades)</h2>
<p><input id="busca-tabla" type="search" placeholder="Código NAES o palabra (ej.: 692000, peluquería, restaurante)" style="width:100%;padding:.7em;font-size:1rem" autocomplete="off"></p>
<p class="ayuda" id="busca-cuenta">{len(filas)} actividades</p>
<div class="tabla"><table id="tabla-grande"><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in filas)}</tbody></table></div>
<script>(function(){{var i=document.getElementById('busca-tabla'),t=document.getElementById('tabla-grande'),c=document.getElementById('busca-cuenta');
var n=function(s){{return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')}};
var rows=[].slice.call(t.tBodies[0].rows);rows.forEach(function(r){{r._t=n(r.textContent)+' 0'+r.cells[0].textContent}});
i.addEventListener('input',function(){{var q=n(i.value).trim().split(/\\s+/),k=0;rows.forEach(function(r){{var ok=q.every(function(w){{return r._t.indexOf(w)>=0}});r.style.display=ok?'':'none';if(ok)k++}});c.textContent=k+' actividades'}});}})();</script>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> <a href="{e(d["fuente"]["url"])}" rel="nofollow noopener" target="_blank">{e(d["fuente"]["nombre"])}</a>. {e(d.get("aclaracion", ""))}</p>
<p><a href="{j["ruta"]}.html">Más sobre {e(j["nombre"])}: Monotasa, novedades y vencimientos →</a></p>
<p class="aviso">Las alícuotas y mínimos del Anexo son máximos: la Municipalidad no puede cobrar más. Verificá siempre tu caso en la Municipalidad o con tu contador.</p>
</div></article>{lateral(notas)}</div>"""
    return pagina(f'{t["titulo"]} | Ramacontable', cuerpo, "impuestos", t["descripcion"], t["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (t["titulo_corto"], t["ruta"] + ".html")])


def _pagina_tabla_simple(j, t, d, filas, dest, fila, cab, notas):
    qs = d.get("preguntas") or []
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    cuerpo = f"""<div class="grilla"><article class="nota calc"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])} | {e(d["norma"])}</p>
<h1>{e(t["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · {e(d["vigencia"])}</p>
<div class="encorto"><b>En corto</b><p>{e(d.get("encorto", ""))}</p></div>
<h2>Las actividades más buscadas</h2>
<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in dest)}</tbody></table></div>
<h2>Buscá tu actividad ({len(filas)} actividades con alícuota especial)</h2>
<p><input id="busca-tabla" type="search" placeholder="Código o palabra (ej.: 471110, seguros, autos)" style="width:100%;padding:.7em;font-size:1rem" autocomplete="off"></p>
<p class="ayuda" id="busca-cuenta">{len(filas)} actividades</p>
<div class="tabla"><table id="tabla-grande"><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in filas)}</tbody></table></div>
<script>(function(){{var i=document.getElementById('busca-tabla'),t=document.getElementById('tabla-grande'),c=document.getElementById('busca-cuenta');
var n=function(s){{return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')}};
var rows=[].slice.call(t.tBodies[0].rows);rows.forEach(function(r){{r._t=n(r.textContent)}});
i.addEventListener('input',function(){{var q=n(i.value).trim().split(/\\s+/),k=0;rows.forEach(function(r){{var ok=q.every(function(w){{return r._t.indexOf(w)>=0}});r.style.display=ok?'':'none';if(ok)k++}});c.textContent=k+' actividades'}});}})();</script>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> <a href="{e(d["fuente"]["url"])}" rel="nofollow noopener" target="_blank">{e(d["fuente"]["nombre"])}</a>. {e(d.get("aclaracion", ""))}</p>
<p><a href="{j["ruta"]}.html">Más sobre {e(j["nombre"])}: alícuota general, mínimos y Monotasa →</a></p>
<p class="aviso">Información de carácter general. Verificá siempre tu caso en la Municipalidad o con tu contador.</p>
</div></article>{lateral(notas)}</div>"""
    return pagina(f'{t["titulo"]} | Ramacontable', cuerpo, "impuestos", t["descripcion"], t["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (t["titulo_corto"], t["ruta"] + ".html")])


def pagina_extra_juris(j, pg, notas):
    """Página propia de un tema de la jurisdicción (ej.: licencia de conducir, patente) con sus bloques y preguntas."""
    hoy = datetime.date.today()
    qs = pg.get("preguntas") or []
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    of = " · ".join(f'<a href="{e(o["url"])}" rel="nofollow noopener" target="_blank">{e(o["nombre"])}</a>' for o in j.get("oficiales") or [])
    otras = "".join(f'<li><a href="{x["ruta"]}.html">{e(x["titulo_corto"])}</a></li>' for x in (j.get("paginas") or []) + (j.get("tablas") or []) if x["ruta"] != pg["ruta"])
    cuerpo = f"""<div class="grilla"><article class="nota"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])}</p>
<h1>{e(pg["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<div class="encorto"><b>En corto</b><p>{e(pg.get("encorto", ""))}</p></div>
{"".join(bloque(b) for b in pg.get("bloques") or [])}
{preguntas_html({"preguntas": qs})}
{f'<p class="fuente"><b>Fuente:</b> {of}</p>' if of else ""}
<p class="aviso">Información de carácter general. Verificá siempre en la Municipalidad.</p>
</div>
<section class="relacionadas"><h2>Más de {e(j["nombre"])}</h2><ul><li><a href="{j["ruta"]}.html">{e(j["titulo_corto"])}: todas las tasas</a></li>{otras}</ul></section>
</article>{lateral(notas)}</div>"""
    return pagina(f'{pg["titulo"]} | Ramacontable', cuerpo, "impuestos", pg["descripcion"], pg["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (pg["titulo_corto"], pg["ruta"] + ".html")])


def pagina_provincias(notas):
    tarj = ""
    for j in JURIS:
        datos = [t for t in TEMAS_RESP if t.get("jurisdiccion") == j["slug"] and ((RESP.get(t["slug"]) or {}).get("datos") or {}).get("valor")]
        li = "".join(f'<li><a href="{t["slug"]}.html"><b>{e(t["titulo"])}</b><span>{e(ajustar_tramo(RESP[t["slug"]]["datos"])["valor"])}</span></a></li>' for t in datos)
        tarj += (f'<section class="rama-guias"><h2><a href="{j["ruta"]}.html">{e(j["titulo_corto"])}</a></h2>'
                 f'<p class="ayuda">{e(j["descripcion"])}</p>' + (f'<ul class="lista-guias">{li}</ul>' if li else "")
                 + f'<p><a class="mas" href="{j["ruta"]}.html">Ver todo de {e(j["nombre"])} →</a></p></section>')
    otras = ""
    for o in OTRAS_J:
        rel = [n for n in notas if _de_jurisdiccion(n, o.get("claves") or [])][:3]
        if rel:
            otras += f'<h3>{e(o["nombre"])} <small>({e(o["organismo"])})</small></h3><ul>' + "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel) + "</ul>"
    otras_html = ('<section class="rama-guias"><h2>Novedades de otras provincias</h2>' + otras + "</section>") if otras else \
        ('<section class="rama-guias"><h2>Otras provincias</h2><p class="ayuda">También seguimos las novedades de '
         + ", ".join(e(o["nombre"]) for o in OTRAS_J) + ". Cuando publiquen algo para la profesión, aparece acá.</p></section>")
    cuerpo = f"""<div class="grilla"><section><p class="miga"><a href="impuestos.html">Impuestos</a></p>
<h1 class="titsec">Impuestos provinciales y municipales</h1>
<p>Ingresos Brutos, regímenes simplificados, tasas municipales y vencimientos de cada provincia y municipio, con la norma y la fuente oficial de cada dato.</p>
{tarj}{otras_html}</section>{lateral(notas)}</div>"""
    return pagina("Impuestos provinciales y municipales: Ingresos Brutos y tasas por provincia | Ramacontable", cuerpo, "impuestos",
                  "Ingresos Brutos y regímenes simplificados de Buenos Aires, Córdoba y Santa Fe, tasas municipales como la Monotasa de La Plata, vencimientos y novedades por provincia.",
                  "provincias-y-municipios.html", migas=[("Impuestos", "impuestos.html"), ("Provincias y municipios", "provincias-y-municipios.html")])


def portada(notas, titulo_pag="Ramacontable | Comunidad contable", actual="", encabezado="", extra=""):
    if not notas:
        lista = '<p class="vacio">Todavía no hay notas en esta sección.</p>'
    else:
        lista = tarjeta(notas[0], grande=True) + '<div class="tarjetas">' + "".join(tarjeta(n) for n in notas[1:]) + "</div>"
    cab = f'<h1 class="titsec">{e(encabezado)}</h1>' if encabezado else ""
    desc = DESC_SECCION.get(actual, "Novedades contables, impositivas y laborales explicadas claro, escalas salariales, guías, calculadoras y vencimientos.")
    return pagina(titulo_pag, f'<div class="grilla"><section>{cab}{extra}{lista}</section>{lateral(notas)}</div>', actual, desc,
                  f"{actual}.html" if actual else "", migas=[(encabezado, f"{actual}.html")] if actual else None)


def main():
    if os.path.exists(SALIDA):
        shutil.rmtree(SALIDA)
    shutil.copytree(os.path.join(RAIZ, "web"), SALIDA)
    global VENC
    VENC = cargar_vencimientos()
    cargar_respuestas()
    cargar_jurisdicciones()
    notas = cargar_notas()
    with open(os.path.join(SALIDA, "config.js"), "w", encoding="utf-8") as f:
        f.write("window.RC_CONFIG=" + json.dumps({
            "url": os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
            "key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            "build": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }) + ";")
    escribir = lambda nombre, txt: open(os.path.join(SALIDA, nombre), "w", encoding="utf-8").write(txt)
    convenios = cargar_convenios()
    ENLACES[:] = _destinos_enlaces(convenios)
    todas = notas
    guias = [n for n in todas if es_guia(n)]
    notas = [n for n in todas if not es_guia(n)]
    try:
        catalogo = json.load(open(os.path.join(RAIZ, "guias", "catalogo.json"), encoding="utf-8"))
    except Exception:
        catalogo = []
    escribir("index.html", portada([n for n in notas if not nota_de_nicho(n)]))
    escribir("guias.html", pagina_guias(guias, notas, catalogo))
    for imp in IMPUESTOS:
        escribir(f"impuesto-{imp[0]}.html", pagina_impuesto(imp, notas, guias, catalogo))
    for k, v in SECCIONES.items():
        extra = ""
        if k == "sueldos":
            extra = ('<div class="conv-chips"><b>Escalas por convenio:</b> ' + " ".join(
                f'<a href="escala-{c["slug"]}.html">{e(c["nombre"])}</a>' for c in sorted(convenios, key=lambda c: PRINCIPALES.index(c["slug"]) if c["slug"] in PRINCIPALES else 99)[:5])
                + f' <a class="mas-chip" href="convenios.html">Más convenios ({len(convenios)}) →</a></div>')
        if k == "impuestos":
            extra = ('<div class="conv-chips"><b>Por impuesto:</b> ' + " ".join(
                f'<a href="impuesto-{s}.html">{e(n)}</a>' for s, n, _, _ in IMPUESTOS) + "</div>")
        if k in RAMAS_GUIAS:
            extra += tira_guias(guias, k)
        escribir(f"{k}.html", portada([n for n in notas if n["seccion"] == k], f"{v} | Ramacontable", k, v, extra))
    aportes = cargar_aportes()
    import portadas
    if portadas.disponible():
        portadas.bajar_fuentes()
        for n in todas:
            try:
                portadas.generar(n, os.path.join(SALIDA, "compartir", f"{n['slug']}.png"))
                PORTADAS_OK.add(n["slug"])
            except Exception as ex:
                print("Aviso: no pude armar la portada de", n["slug"], ex)
    else:
        print("Aviso: falta Pillow; las notas se comparten con la imagen general")
    for n in todas:
        escribir(f"nota-{n['slug']}.html", pagina_nota(n, guias if es_guia(n) else notas, aportes.get(n['slug'])))
    escribir("herramientas.html", pagina_vencimientos(notas))
    with open(os.path.join(RAIZ, "paginas", "terminos.html"), encoding="utf-8") as f:
        escribir("terminos.html", pagina("Términos y privacidad | Ramacontable", f.read()))
    with open(os.path.join(RAIZ, "paginas", "aguinaldo.html"), encoding="utf-8") as f:
        escribir("aguinaldo.html", pagina("Calculadora de aguinaldo diciembre 2026 (SAC): cálculo paso a paso | Ramacontable", f.read(), "",
                 "Calculá el aguinaldo de diciembre 2026: mensualizados y jornalizados, proporcional por días, descuentos y neto, con el cálculo paso a paso.",
                 "aguinaldo.html", herramienta_ld("Calculadora de aguinaldo (SAC)", "Calculá el aguinaldo con el cálculo paso a paso, descuentos y neto.", "aguinaldo.html"),
                 [("Calculadoras", "calculadoras.html"), ("Aguinaldo", "aguinaldo.html")]))
    with open(os.path.join(RAIZ, "paginas", "nota-dinamica.html"), encoding="utf-8") as f:
        escribir("nota.html", pagina("Nota | Ramacontable", f.read()))
    with open(os.path.join(RAIZ, "paginas", "admin.html"), encoding="utf-8") as f:
        escribir("admin.html", pagina("Administración | Ramacontable", f.read()))
    escribir("convenios.html", pagina_convenios(convenios, notas))
    if os.environ.get("RC_SIN_SERIES") != "1":
        bajar_series(os.path.join(SALIDA, "datos"))
    escribir_feriados(os.path.join(SALIDA, "datos"))
    if os.environ.get("RC_SIN_SERIES") != "1":
        bajar_dolares(os.path.join(SALIDA, "datos"))
    for t in TEMAS_RESP:
        escribir(t["slug"] + ".html", pagina_respuesta(t, RESP.get(t["slug"]), notas, aportes.get("dato-" + t["slug"])))
    for x in DOLARES:
        h = pagina_dolar(*x, notas)
        if h:
            escribir(x[0] + ".html", h)
    h = pagina_dolar_hub(notas)
    if h:
        escribir("dolar-hoy.html", h)
    for b in BCRA_RESP:
        h = pagina_bcra(*b, notas)
        if h:
            escribir(b[0] + ".html", h)
    for o in OBLIGACIONES:
        escribir(o[0] + ".html", pagina_obligacion(*o, notas))
    for pm in PAGINAS_MES:
        for m in _meses_paginas():
            h = pagina_mes(*pm, m, notas)
            if h:
                escribir(f"{pm[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html", h)
    for c in convenios:
        for m in _meses_paginas():
            escribir(f"paritarias-{c['slug']}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html", pagina_paritaria(c, m, notas))
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        anio, h = pagina_feriados_anio(ruta, notas)
        escribir(f"feriados-{anio}.html", h)
        FERIADOS_URLS.append(f"feriados-{anio}")
    for m in meses_que_cambia():
        url, h = pagina_que_cambia(m, notas)
        escribir(url + ".html", h)
        QUE_CAMBIA_URLS.append(url)
    escribir("cuando-cambia-cada-dato.html", pagina_calendario_datos(notas))
    for j in JURIS:
        escribir(j["ruta"] + ".html", pagina_jurisdiccion(j, notas))
        for pg in j.get("paginas") or []:
            escribir(pg["ruta"] + ".html", pagina_extra_juris(j, pg, notas))
            TABLAS_URLS.append(pg["ruta"])
        for t in j.get("tablas") or []:
            try:
                escribir(t["ruta"] + ".html", pagina_tabla_juris(j, t, notas))
                TABLAS_URLS.append(t["ruta"])
            except Exception as ex:
                print("Aviso: no pude armar la tabla", t.get("ruta"), ex)
    escribir("provincias-y-municipios.html", pagina_provincias(notas))
    JURIS_URLS[:] = ["provincias-y-municipios"] + [j["ruta"] for j in JURIS] + TABLAS_URLS
    g = pagina_glosario(notas)
    if g:
        escribir("glosario.html", g)
    escribir("comparador-escalas.html", pagina_comparador(convenios, notas))
    escribir(os.path.join("datos", "vencimientos.json"), json.dumps(proximos_vencimientos(), ensure_ascii=False))
    escribir("datos-al-dia.html", pagina_datos(notas))
    os.makedirs(os.path.join(SALIDA, "datos"), exist_ok=True)
    escribir(os.path.join("datos", "datos-del-dia.json"), json.dumps(datos_para_calculadoras(), ensure_ascii=False))
    por_slug = {c["slug"]: c for c in convenios}
    def calc_conv(archivo, salida_html, slug, titulo, desc):
        c = por_slug.get(slug) or {}
        datos = dict(c.get("escala") or {}, slug=slug)
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            cuerpo = f.read().replace('<script src="sueldo.js', '<script>window.RC_ESCALA=' + json.dumps(datos, ensure_ascii=False).replace("</", "<\\/") + ';</script><script src="sueldo.js')
        escribir(salida_html, pagina(titulo, cuerpo, "", desc, salida_html, herramienta_ld(titulo.split(":")[0].split(" | ")[0], desc, salida_html),
                                     [("Calculadoras", "calculadoras.html"), (titulo.split(":")[0].split(" | ")[0], salida_html)]))
    calc_conv("sueldo-comercio.html", "sueldo-comercio.html", "comercio", "Calculadora de sueldo Empleados de Comercio 2026: neto con antigüedad y presentismo | Ramacontable",
              "Calculá el sueldo de comercio con la escala vigente: básico por categoría, antigüedad, presentismo, sumas no remunerativas, descuentos y neto.")
    calc_conv("sueldo-casas.html", "sueldo-casas-particulares.html", "casas-particulares", "Calculadora de sueldo de empleadas domésticas 2026: por hora y mensual | Ramacontable",
              "Calculá el sueldo de casas particulares por categoría, con o sin retiro, mensual o por hora, con antigüedad y zona desfavorable.")
    CALCS = [("actualizacion.html", "Calculadora de actualización de montos por inflación, CER, UVA, dólar y tasas", "Actualizá montos y deudas entre dos fechas con datos oficiales del BCRA: inflación, CER, UVA, ICL, dólar oficial y tasas."),
             ("dias-habiles.html", "Calculadora de días hábiles 2026 con feriados", "Contá días hábiles entre dos fechas o calculá el vencimiento de un plazo, descontando sábados, domingos y feriados nacionales."),
             ("plazo-fijo.html", "Simulador de plazo fijo: intereses y TEA", "Calculá los intereses de un plazo fijo, la TEA y cuánto tenés si lo renovás, con la tasa promedio del BCRA."),
             ("prestamos.html", "Calculadora de préstamos: cuota y cuadro de amortización", "Calculá la cuota de un préstamo en sistema francés o alemán, el total de intereses y el cuadro de amortización."),
             ("vacaciones.html", "Calculadora de vacaciones 2026: días y cuánto se cobra", "Calculá los días de vacaciones según antigüedad y cuánto se cobra: sueldo ÷ 25 y plus vacacional (LCT arts. 150 a 157)."),
             ("liquidacion-final.html", "Calculadora de liquidación final e indemnización por despido 2026", "Calculá la liquidación final por renuncia o despido: indemnización art. 245, preaviso, integración, SAC y vacaciones proporcionales."),
             ("horas-extras.html", "Calculadora de horas extras al 50% y al 100%", "Calculá el valor de las horas extras al 50% y al 100% a partir del sueldo y la jornada (art. 201 LCT)."),
             ("iva.html", "Calculadora de IVA: agregar o quitar IVA", "Sumá o quitá el IVA de un importe con alícuotas del 21%, 10,5%, 27% y otras."),
             ("conversor-dolar.html", "Conversor de dólar a pesos: oficial, MEP, CCL, tarjeta, cripto y blue", "Convertí pesos a dólares y dólares a pesos con las cotizaciones de hoy: oficial, mayorista, MEP, CCL, tarjeta, cripto y blue."),
             ("monotributo-categoria.html", "Calculadora de categoría del Monotributo 2026", "Cargá lo que facturaste en los últimos 12 meses y mirá en qué categoría del Monotributo estás y cuánto pagás por mes."),
             ("intereses-arca.html", "Calculadora de intereses resarcitorios de ARCA", "Calculá los intereses por pagar tarde un impuesto o aporte a ARCA, con la tasa vigente y los días de atraso."),
             ("actualizacion-alquiler.html", "Calculadora de actualización de alquiler por ICL o IPC", "Calculá cuánto aumenta tu alquiler por ICL o por inflación (IPC) entre dos fechas, con datos oficiales del BCRA."),
             ("agenda-vencimientos.html", "Agenda de vencimientos por CUIT", "Cargá la terminación de CUIT de tus clientes y mirá solo sus vencimientos de ARCA, con descarga al calendario."),
             ("retencion-ganancias.html", "Calculadora de retención de Ganancias sobre el sueldo 2026", "Estimá cuánto te retienen de Ganancias por mes en el sueldo, con las deducciones y la escala vigentes."),
             ("embargo-sueldo.html", "Calculadora de embargo de sueldo 2026 (Decreto 484/87)", "Calculá cuánto se puede embargar de un sueldo según el salario mínimo vigente: inembargable hasta 1 SMVM, 10% y 20% del excedente.")]
    for archivo, titulo, desc in CALCS:
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            escribir(archivo, pagina(titulo + " | Ramacontable", f.read(), "", desc, archivo, herramienta_ld(titulo, desc, archivo),
                                     [("Calculadoras", "calculadoras.html"), (titulo.split(":")[0], archivo)]))
    for archivo, titulo, desc in [("calculadoras.html", "Calculadoras de sueldos y aguinaldo | Ramacontable", "Calculadoras gratuitas para liquidar sueldos: comercio, casas particulares y aguinaldo, con escalas vigentes."),
                                  ("feriados.html", "Feriados 2026 Argentina: calendario completo y cómo se pagan | Ramacontable", "Calendario de feriados 2026 en Argentina: inamovibles, trasladables y días no laborables, y cómo se liquida trabajar un feriado.")]:
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            cuerpo = f.read()
        if archivo == "feriados.html":
            extra = [x for fila in VENC for x in fila.get("feriados") or [] if f'data-f="{x["fecha"]}"' not in cuerpo]
            if extra:
                filas = "".join(f'<tr data-f="{e(x["fecha"])}"><td>{int(x["fecha"][8:])}/{int(x["fecha"][5:7])}</td><td>{e(x["nombre"])}'
                                + (f' ({e(x["norma"])})' if x.get("norma") else "") + f'</td><td><span class="tipo-f t-no ">{e(x.get("tipo",""))}</span></td></tr>' for x in extra)
                cuerpo = cuerpo.replace("</tbody></table></div>", "</tbody></table></div>" + '<h2>Feriados y días no laborables agregados durante el año</h2><div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Detalle</th><th>Tipo</th></tr></thead><tbody>' + filas + "</tbody></table></div>", 1)
        escribir(archivo, pagina(titulo, cuerpo, "", desc, archivo))
    for c in convenios:
        escribir(f"escala-{c['slug']}.html", pagina_convenio(c, notas, aportes.get("convenio-" + c["slug"])))
    PARITARIAS_URLS[:] = [f"paritarias-{c['slug']}-{MESES[int(m[5:]) - 1]}-{m[:4]}" for c in convenios for m in _meses_paginas()]
    mapa, noticias, robots = sitemaps(todas, convenios)
    escribir("sitemap.xml", mapa)
    escribir("sitemap-noticias.xml", noticias)
    escribir("robots.txt", robots)
    escribir("llms.txt", llms_txt(todas, convenios))
    clave_in = "rc" + __import__("hashlib").sha1(sitio_url().encode()).hexdigest()[:30]
    escribir(clave_in + ".txt", clave_in)
    escribir("indexnow.json", json.dumps({"key": clave_in, "urls": urls_indexnow(todas, convenios)}))
    escribir(".nojekyll", "")
    print(f"Listo: {len(notas)} notas en {SALIDA}")


if __name__ == "__main__":
    main()
